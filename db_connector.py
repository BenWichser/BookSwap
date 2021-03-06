import sqlite3
from flask import g, session, redirect, url_for, flash
import requests
import logging

log = logging.getLogger('app.sub')

DATABASE = 'DatabaseSpecs/test-db.db'


def get_db():
    """
    get_db opens the connection to the Sqlite database file.
    """
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db


class EditionDuplicationError(Exception):
    """Raised when we are about to insert an entry into the Books table with an OLEditionKey that already exists"""
    pass


class BookSwapDatabase:
    """
    This class is intended to deal with everything-SQL related:
        opening and closing connections to the database
        running queries and returning the results
        adding/deleting rows given criteria

    So that the routes in app.py don't have to touch the SQL themselves,
    and repeated functionality can be consolidated here
    """

    def __init__(self):
        self.db = get_db()
        self.db.row_factory = sqlite3.Row  # This allows us to access values by column name later on

    def accept_trade(self, user_books_id):
        """
        Accept_Trade performs the database work necessary for accepting the trade:
            Listing user has book moved from their pending trades list to their
                active trades list
        Accepts:
            user_books_id (int):  UserBooksId number of requested book
        Returns:
            None
        """
        c = self.db.cursor()
        # Change Trade state
        try:
            c.execute("""
                    UPDATE
                        Trades
                    SET
                        statusId = 3
                    WHERE
                        userBookId = ?
                        """,
                      (user_books_id,))
            self.db.commit()
            log.info(f"trade for book {user_books_id} changed to 'accepted by user'")
        except sqlite3.Error as e:
            log.error(
                f"Error {e}.  Failed to change the trade status for UserBooks book number {user_books_id}")
            flash("Error marking trade as accepted", "warning")
            raise Exception
        return

    def book_not_received_by_requester(self, user_books_id, user_num):
        """
        Book_not_received_by_requester completes the trade request:
            changes Trades.statusId to not completed (7)
            awards points to requester 
        Accepts:
            user_books_id (int): UserBooks.id
            user_num (int): Users.id
        Returns:
            None
        """
        c = self.db.cursor()
       # award points to requester
        try:
            c.execute("""
                    UPDATE 
                        Users
                    SET
                        points = points + (
                            SELECT
                                points
                            FROM
                                UserBooks
                            WHERE
                                id = ?
                                )
                    WHERE
                        id = ?
                    """,
                    ( user_books_id, user_num) )
            self.db.commit()
        except sqlite3.Error as e:
            log.error(f"Awarding points to receiving user for book {user_books_id} -- {e}")
            raise Exception
        # Change Trade to failed (7)
        try:
            c.execute("""
                    UPDATE
                        Trades
                    SET
                        statusId = 7
                    WHERE
                        userBookId = ?
                    """, 
                    ( user_books_id, ))
            self.db.commit()
        except sqlite3.Error as e:
            log.error("Changing trade status on book {user_books_id} -- {e}")
            raise Exception
         # job's done
        return

    def book_received_by_requester(self, user_books_id, user_num):
        """
        Book_received_by_requester completes the trade request:
            changes Trades.statusId to completed (6)
            awards points to sender 
        Accepts:
            user_books_id (int): UserBooks.id
            user_num (int): Users.id
        Returns:
            None
        """
        c = self.db.cursor()
       # award points to sender
        try:
            c.execute("""
                    UPDATE 
                        Users
                    SET
                        points = points + (
                            SELECT
                                points
                            FROM
                                UserBooks
                            WHERE
                                id = ?
                                )
                    WHERE
                        id = (
                            SELECT
                                userId
                            From
                                UserBooks
                            WHERE
                                id = ?
                                )
                    """,
                    ( user_books_id, user_books_id) )
            self.db.commit()
        except sqlite3.Error as e:
            log.error(f"Awarding points to sending user for book {user_books_id} -- {e}")
            raise Exception
        # Change Trade to complted (6)
        try:
            c.execute("""
                    UPDATE
                        Trades
                    SET
                        statusId = 6
                    WHERE
                        userBookId = ?
                    """, 
                    ( user_books_id, ))
            self.db.commit()
        except sqlite3.Error as e:
            log.error("Changing trade status on book {user_books_id} -- {e}")
            raise Exception
         # job's done
        return

    def cancel_trade_by_requester(self, user_books_id, user_num):
        """
        Cancel_trade_by_requester cancels the trade request:
            removes Trades row, 
            returns points to requester
            marks book as available
        Accepts:
            user_books_id (int): UserBooks.id
            user_num (int): Users.id
        Returns:
            None
        """
        c = self.db.cursor()
       # return points to requester
        try:
            c.execute("""
                    UPDATE 
                        Users
                    SET
                        points = points + (
                            SELECT
                                points
                            FROM
                                UserBooks
                            WHERE
                                id = ?
                                )
                    WHERE
                        id = ?
                    """,
                    ( user_books_id, user_num) )
            self.db.commit()
        except sqlite3.Error as e:
            log.error(f"Returning points to User {user_num} for book {user_books_id} -- {e}")
            raise Exception
        # Mark book as available
        try:
            c.execute("""
                    UPDATE
                        UserBooks
                    SET
                        available = 1
                    WHERE
                        id = ?
                    """,
                    (user_books_id, ))
            self.db.commit()
        except sqlite3.Error as e:
            log.error(f"Setting book {user_books_id} as available -- {e}")
            raise Exception
        # Delete trade entry
        try:
            c.execute("""
                    DELETE FROM 
                        Trades 
                    WHERE
                        Trades.userBookId = ?
                    """, 
                    ( user_books_id, ))
            self.db.commit()
        except sqlite3.Error as e:
            log.error("Deleting trade on book {user_books_id} -- {e}")
            raise Exception
         # job's done
        return
                        

    def close(self):
        """
        Closes the db connection
        :return: Nothing
        """
        self.db.close()

    def get_account_settings(self, user_id):
        """
        Gets account settings for a given user.
        Returned as a sqlite3.Row which can be accessed by key.
        """
        c = self.db.cursor()
        c.execute("""SELECT 
                    username, 
                    email,
                    fName, 
                    lName, 
                    streetAddress, 
                    city, 
                    state, 
                    postCode, 
                    points 
                FROM Users WHERE id=?;""", (user_id,))
        rows = c.fetchall()
        if len(rows) == 0:
            session.clear()
            return redirect(url_for('login'))
        if len(rows) > 1:
            raise KeyError("User ID did not return only one row")
        return rows[0]

    def get_all_open_requests(self, user_num):
        """
        Returns a list of all of a user's open requests.
        Accepts:
            user_num (int): Users.id
        Returns:
            list of Row objects
        """
        c = self.db.cursor()
        try:
            c.execute("""
                    SELECT
                        Trades.statusId AS statusId,
                        Books.title AS title,
                        Books.author AS author,
                        UserBooks.points AS points,
                        Users.username AS username,
                        Books.coverImageUrl AS coverImageUrl,
                        Trades.dateInitiated AS dateInitiated,
                        Books.isbn AS isbn,
                        UserBooks.id AS userBooksId,
                        CAST ((julianday('now') - julianday(Trades.dateInitiated)) AS INTEGER) AS tradeAge
                    FROM
                        Trades INNER JOIN 
                        UserBooks on Trades.userBookId = UserBooks.id INNER JOIN
                        Books on UserBooks.bookId = Books.id INNER JOIN
                        Users on UserBooks.userId = Users.id
                    WHERE
                        Trades.statusId IN (2, 3, 4, 5, 6, 7) AND
                        Trades.userRequestedId = ?
                    ORDER BY
                        dateInitiated ASC
                        """,
                      (user_num,))
            rows = c.fetchall()
        except sqlite3.Error as e:
            log.error(f"Receiving open trades from database -- {e}")
            raise Exception
        return rows

    def get_book_qualities(self):
        """
        Returns a list of tuples containing (quality ID, copy quality description)
        :return: dict
        """
        c = self.db.cursor()
        c.execute("""SELECT id, qualityDescription FROM CopyQualities;""")
        rows = c.fetchall()
        out = []
        for row in rows:
            out.append((row["id"], row["qualityDescription"]))
        return out

    def get_listed_books(self, user_num):
        """
        Returns the rows corresponding to the books that user_id has listed as
        available for swapping.
        :param user_num: the ID of the user whose listed books to return
        :return: a list of sqlite3.Row objects corresponding to the listed books
        """
        c = self.db.cursor()
        c.execute("""
                    SELECT 
                        B.title AS Title, 
                        B.ISBN AS ISBN, 
                        B.author AS Author, 
                        UB.points AS Points,
                        CQ.qualityDescription AS Quality,
                        UB.id AS id,
                        B.coverImageUrl AS Cover 
                        FROM 
                            UserBooks UB 
                        INNER JOIN 
                            Books B on UB.bookId = B.id 
                        INNER JOIN 
                        CopyQualities CQ ON UB.copyQualityId = CQ.id 
                        WHERE 
                            userId = ?
                        AND
                            UB.available == 1
                    """,
                  (user_num,))
        rows = c.fetchall()
        self.db.commit()
        return rows

    def get_num_open_trades(self, user_num: int) -> int:
        """
        Returns number of trade requests this user has agreed to, but are not 
            yet completed.
        """
        try:
            c = self.db.cursor()
            c.execute("""
                    SELECT
                        COUNT (*)
                    FROM
                        Trades INNER JOIN
                        UserBooks on Trades.userBookId = UserBooks.Id
                    WHERE
                        UserBooks.userId = ?
                        AND
                        Trades.statusId = 3
                        """,
                      (user_num,))
            rows = c.fetchall()
            if len(rows) != 1:
                log.error(f"Received wrong number of data from database")
                raise Exception
            return rows[0][0]
        except sqlite3.Error as e:
            log.error(f"database error {e}")
            raise Exception

    def get_num_trade_requests(self, user_num: int) -> int:
        """
        Returns number of trade requests this user has, as the listing user.
        """
        try:
            c = self.db.cursor()
            c.execute("""
                    SELECT
                        COUNT (*)
                    FROM
                        Trades INNER JOIN
                        UserBooks on Trades.userBookId = UserBooks.Id
                    WHERE
                        UserBooks.userId = ?
                        AND
                        Trades.statusId = 2
                        """,
                      (user_num,))
            rows = c.fetchall()
            if len(rows) != 1:
                log.error(f"Received wrong number of data from database")
                raise Exception
            return rows[0][0]
        except sqlite3.Error as e:
            log.error(f"database error {e}")
            raise Exception

    def get_trade_age(self, user_books_id):
        """
        Get_trade_age gets the age of the trade.
        Accepts:
            user_books_id (int): UserBooks.id
        Returns:
            Row object with 'tradeAge' key
        """
        try:
            c = self.db.cursor()
            c.execute("""
                    SELECT
                        CAST ((julianday('now') - julianday(Trades.dateInitiated)) AS INTEGER) AS tradeAge
                    FROM
                        Trades
                    WHERE
                        Trades.userBookId = ?
                    """,
                    (user_books_id, ))
            print("GET TRADE AGE")
            rows = c.fetchall()
        except sqlite3.Error as e:
                log.error(f"Getting trade age -- {e}")
                raise Exception
        if len(rows) != 1:
            log.error("Wrong number of responses for trade age")
            raise Exception
        return rows[0]

    def get_userBooksID(self, user_num):
        """
        Returns the UserBooks.id attribute for each of the user's books
        """
        c = self.db.cursor()
        c.execute("""SELECT id FROM UserBooks WHERE userId=?""", (user_num,))
        rows = c.fetchall()
        self.db.commit()
        return rows

    def get_trade_status(self, user_books_id):
        """
        Get_trade_status gets the trade status of a particular UserBooks entry.
        Accepts:
            user_books_id (int): UserBooks.id
        Returns:
            Trades.statusId (int)
        """
        c = self.db.cursor()
        try:
            c.execute("""
                    SELECT 
                        Trades.statusId
                    FROM
                        Trades
                    WHERE
                        Trades.userBookId = ?
                    """,
                    (user_books_id, ))
            rows = c.fetchall()
        except sqlite3.Error as e:
            log.error(f"Getting trade status for UserBooks entry {user_books_id} -- {e}")
            raise Exception
        if len(rows) != 1:
            log.error(f"Wrong number of trades for UaserBooks entry {user_books_id}")
            raise Exception
        return rows[0]


    def get_trade_info(self, user_num):
        c = self.db.cursor()
        c.execute("""
                SELECT  Trades.statusId StatusId,
                        Trades.dateInitiated AS StartDate,
                        Books.title AS Title,
                        Books.author AS Author,
                        Books.isbn AS ISBN,
                        CopyQualities.qualityDescription AS Quality,
                        UserBooks.points AS Points,
                        U1.username AS Owner,
                        U2.username AS Requester,
                        UserBooks.id AS userBooksId,
                        Books.coverImageUrl as coverImageUrl
                FROM    Users U1 INNER JOIN
                        UserBooks on U1.id = UserBooks.userId INNER JOIN
                        Trades on UserBooks.id = Trades.userBookId INNER JOIN
                        Books on Books.id = UserBooks.bookId INNER JOIN
                        CopyQualities ON UserBooks.CopyQualityId = CopyQualities.Id INNER JOIN
                        Users U2 on U2.id = Trades.userRequestedId
                WHERE
                        UserBooks.userId = ?
                """, (user_num,))
        rows = c.fetchall()
        self.db.commit()
        return rows


    def get_trade_requester(self, user_books_id):
        """
        Get_trade_requester gets the Trades.requestedId
        Accepts:
            user_books_id (int): Trades.userBooksId
        Returns:
            Trades.requestedId (int)
        """
        c = self.db.cursor()
        try:
            c.execute("""
                    SELECT
                        Trades.userRequestedId AS userRequestedId
                    FROM
                        Trades
                    WHERE
                        Trades.userBookId = ?
                    """,
                    ( user_books_id, ))
            rows = c.fetchall()
        except sqlite3.Error as e:
            log.error(f"Confirming user as requesting user -- {e}")
            raise Exception
        if len(rows) != 1:
            log.error(f"Wrong number of Trades entries for {user_books_id}")
            raise Exception
        return rows[0]


    def get_or_add_ol_book_details(self, search_result):
        """
        Does the same thing as get_ol_book_details, but if the book is not yet stored then finds the first english
        language paperback/hardcover Edition of the Work corresponding to the given key in the Open Library API and
        then inserts its details into the Books table.
        To do this a dict called 'search result' corresponding to the JSON search result returned by Open Library is
        required. To clarify: there is currently no way to add details for an Open Library Work, given a Work Key,
        unless we have access to the information from the search result.  

        :returns a dict of the attributes for the Books row
        """
        # Get the Work Key from the search result
        work_key = search_result['key'].split('/')[2]
        # First check if it exists
        local = self.get_ol_book_details(work_key)
        if local is not None:
            return local
        # Get the info of the first printed, english-language, edition, to store
        d = {'title': search_result['title'] if 'title' in search_result else 'Unknown Title',
             'author': search_result['author_name'][0] if 'author_name' in search_result else 'Unknown Author',
             'OLWorkKey': work_key}
        editions = search_result['edition_key']
        # Check the editions 10 at a time
        n = len(editions)
        edition_key = None
        isbn = None
        i = 0
        while (i < (n // 10) + 1) and (edition_key is None):
            batch = editions[i:i + 10]
            url = 'https://openlibrary.org/api/books'
            payload = {'format': 'json',
                       'jscmd': 'details',
                       'bibkeys': ','.join(batch)}
            r = requests.get(url, params=payload)
            data = r.json()
            for candidate in data.keys():
                details = data[candidate]['details']
                if 'languages' in details and 'covers' in details and 'isbn_13' in details:
                    languages = details['languages']
                    if len(languages) == 1 and languages[0]['key'] == '/languages/eng':
                        edition_key = candidate
                        isbn = int(details['isbn_13'][0].replace('-', '').replace(' ', ''))
                        break
            i += 10
        # Note that edition_key could still be None if we didn't find a suitable one, that's fine
        # Insert the book info now
        d['OLEditionKey'] = edition_key
        d['ISBN'] = isbn
        if edition_key is not None:
            d['coverImageUrl'] = "http://covers.openlibrary.org/b/olid/" + edition_key + "-L.jpg"
            # Check if we are about to duplicate an edition key
            local_edition = self.get_ol_edition_details(edition_key)
            if local_edition is not None:
                raise EditionDuplicationError()
        else:
            d['coverImageUrl'] = None
        c = self.db.cursor()
        print(
            f'About to insert Books row with OLWorkKey value {work_key} and OLEditionKey value {edition_key} - the '
            f'book is {d["title"]} by {d["author"]}')
        c.execute(
            """INSERT INTO Books (title, author, ISBN, OLWorkKey, OLEditionKey, coverImageUrl) VALUES (?, ?, ?, ?, ?, 
            ?)""",
            (d['title'], d['author'], isbn, work_key, edition_key, d['coverImageUrl']))
        self.db.commit()
        d['id'] = c.lastrowid  # ID of the recently inserted Books row
        return d

    def get_ol_book_details(self, work_key):
        """
        Returns the Books table attributes for a given Work, as defined by Open Library. If the volume has not yet
        been locally stored in the database, None is returned, and 'get_or_add_ol_book_details' must be called instead.
        :param work_key: the Open Library Works Key (eg 'OL27448W') associated with the volume.
        :returns a sqlite Row or a dict of the Book's attributes, with the keys: 'id', 'title', 'author', 'isbn',
        'OLEditionKey', 'OLWorkKey'
        """
        c = self.db.cursor()
        c.execute(
            """SELECT id, title, author, ISBN, OLWorkKey, OLEditionKey, coverImageUrl FROM Books WHERE OLWorkKey=?""",
            (work_key,))
        rows = c.fetchall()
        if len(rows) > 1:
            # This should not happen!
            raise LookupError(
                "Multiple Books found to correspond to a single work key - this should never "
                "happen!")
        elif len(rows) == 1:
            return rows[0]
        elif len(rows) == 0:
            # Book does not exist - must call 'get_or_add_ol_book_details' with a list of Edition keys
            return None

    def get_ol_edition_details(self, edition_key):
        """
        Returns the Books table attributes for a given Edition, as defined by Open Library. If the volume has not yet
        been locally stored in the database, None is returned, and 'get_or_add_ol_book_details' must be called instead.
        :param edition_key: the Open Library Editions Key associated with the volume.
        :returns a sqlite Row or a dict of the Book's attributes, with the keys: 'id', 'title', 'author', 'isbn',
        'OLEditionKey', 'OLWorkKey'
        """
        c = self.db.cursor()
        c.execute(
            """SELECT id, title, author, ISBN, OLWorkKey, OLEditionKey, coverImageUrl FROM Books WHERE 
            OLEditionKey=?""",
            (edition_key,))
        rows = c.fetchall()
        if len(rows) > 1:
            # This should not happen!
            raise LookupError(
                "Multiple Books found to correspond to a single edition key - this should never "
                "happen!")
        elif len(rows) == 1:
            return rows[0]
        elif len(rows) == 0:
            # Book does not exist - must call 'get_or_add_ol_book_details' with a list of Edition keys
            return None

    def search_books_openlibrary(self, title=None, author=None, isbn=None, num_results=1, book_id_ignorelist=[]):
        """
        Searches for books that match the provided details, and then returns the results. The search is conducted on
        the Open Library API. This method automatically searches for matching books and stores a local copy of the
        details in the Books table if it does not exist. What is returned is easy to work with:
        a list of sqlite.Row objects corresponding to selections from the Books table, so all the keys
        are the names of attributes of the Books table.
            Example:
            result = search_books_openlibrary(title="Lord", author="Tolkien", num_results=1)
            book_id = result[0]['id']
            image_url = result[0]['coverImageUrl']
            Open Library works by creating a 'Work' for each book, which has a 1:M relationship
        with 'Editions'. For example, the first Harry Potter book is a single 'Work' corresponding to 191 'Editions'
        that come in different languages and formats. Here we fetch some details from the Work (author, title) and
        others from the Edition - using the first English paperback/hardback edition.
        :param title: String, search is done for books whose title contains this
        :param author: Search is done for books whose author contains this string
        :param isbn: Must be a STRING
        :param num_results: int, the number of results to return
        :param book_id_ignorelist: a list of book IDs to not include in the results

        :return: A 'num_results' long list of dicts/sqlite.Rows corresponding to search results.
                    Each row has the following keys:
                    'id' - from the Books table
                    'title'
                    'OLWorkKey' (a unique open library key for the work - not a specific edition)
                    'OLEditionKey' (as above, but for a specific edition - could be None if no suitable edition found)
                    'author'
                    'coverImageUrl'
        """
        # Clean inputs and get the search results
        url = "http://openlibrary.org/search.json"
        if title == '':
            title = None
        if author == '':
            author = None
        payload = {'title': title, 'author': author, 'isbn': isbn}
        r = requests.get(url, params=payload)  # auto-ignores 'None' values
        if r.status_code != 200:
            results = []
        else:
            results = r.json()['docs'][:num_results]
        out = []
        # Return the book info
        for idx, result in enumerate(results):
            print(f'Processing search result number {idx}')
            book_info = self.get_or_add_ol_book_details(result)  # This does the heavy lifting
            if book_info['id'] not in book_id_ignorelist:
                out.append(book_info)
        return out

    def user_add_book_by_id(self, book_id, user_num, copyquality, points):
        """
        'user_id' user lists the book matching 'id' as available to swap.
        Nothing happens on failure.
        """
        c = self.db.cursor()
        c.execute("""INSERT INTO UserBooks (userId, bookId, copyQualityId, points) VALUES (?, ?, ?, ?)""",
                  (user_num, book_id, copyquality, points))
        cur_points = c.execute("SELECT points FROM Users WHERE id = ?", (user_num,)).fetchone()['points']
        cur_points += 0.1
        c.execute("""UPDATE Users SET points = (?) WHERE id = (?)""", (cur_points, user_num))
        self.db.commit()
        return

    def user_add_book_to_wishlist_by_id(self, book_id, user_num):
        """
        'user_id' lists the book matching 'book_id' on their wishlist
        """
        c = self.db.cursor()
        # Get the wishlist ID
        c.execute("""SELECT id FROM Wishlists WHERE userId = ?;""", (user_num,))
        wishlist_id = c.fetchone()['id']

        # If the book is already in the wishlist, don't add it
        c.execute("""SELECT * FROM WishlistsBooks WHERE wishlistId = ? AND bookId = ?;""", (wishlist_id, book_id))
        if c.fetchall():
            flash("Book already in your wishlist", "warning")
            log.warning(f"Book {book_id} already in " +
                        f"user {user_num}'s wishlist")
        # otherwise, add book to the wishlist
        else:
            c.execute("""INSERT INTO WishlistsBooks (wishlistId, bookId) VALUES (?, ?);""", (wishlist_id, book_id))
            self.db.commit()
            flash("Book successfully added to your wishlist", "success")
            log.info(f"Book {book_id} added to wishlist {wishlist_id}")

    def user_add_book_by_isbn(self, isbn, user_num, copyquality):
        """
        'user_id' user lists the book matching 'isbn' as available to swap.
        Nothing happens on failure.

        This method delegates the job of getting the Books.id value for a given volume to another method,
        and only deals with the job of creating the required UserBooks entry. It is that other method that interfaces
        with the Google Books API.

        :param copyquality: ID corresponding to the quality of the book copy
        :param user_num: database ID of the user to add the book to
        :param isbn: ISBN of the book to be listed as available to swap
        :return: Nothing
        """
        self.db.row_factory = sqlite3.Row  # This allows us to access values by column name later on
        c = self.db.cursor()
        # First get book ID
        c.execute("""SELECT id FROM Books WHERE ISBN=?""", (isbn,))
        rows = c.fetchall()
        # TODO handle multiple matches better
        if len(rows) != 1:
            log.warning("Warning: no matching book found when trying to list a book")
            return
        book_id = rows[0]["id"]
        c.execute("""INSERT INTO UserBooks (userId, bookId, copyQualityId) VALUES (?, ?, ?)""",
                  (user_num, book_id, copyquality))
        self.db.commit()

    def get_username_id(self, username):
        """
        Get_username_id checks to see if the user's entered username matches
            a used username or a used email, and returns the user's id.
        Accepts:
            username (str): Users.username or Users.email
        Returns:
            Users.id if the user's username works, false otherwise
        """
        c = self.db.cursor()
        try:
            c.execute("""
                    SELECT
                        id
                    FROM
                        Users
                    WHERE
                        username = ?
                    """,
                      (username,))
            rows = c.fetchall()
            if len(rows) == 1:
                return rows[0][0]
        except sqlite3.Error as e:
            log.error(f"Error checking username.  Error was {e}")
            raise Exception
        try:
            c.execute("""
                    SELECT
                        id
                    FROM
                        Users
                    WHERE
                        email = ?
                    """,
                      (username,))
            rows = c.fetchall()
            if len(rows) == 1:
                return rows[0][0]
        except sqlite3.Error as e:
            log.error(f"Error checking email.  Error was {e}")
            raise Exception
        return None

    def is_username_available(self, username):
        """
        Checks if username is not yet taken in database.
        Accepts:
            username (string): Username we are checking for
        Returns:
            True if username is not yet used, false if it is already used.
        """
        c = self.db.cursor()
        c.execute("""
                SELECT id FROM Users WHERE username = ?
                """,
                  (username,))
        rows = c.fetchall()
        available = (len(rows) == 0)
        return available

    def set_account_information(self, user_id, req):
        """
        Changes the user account information.
        Accepts:
            user_id (int): user id number
            req (JSON): body of request from user
        Returns:
            True if successful change, false if not
        """
        c = self.db.cursor()
        try:
            c.execute("""
                    UPDATE Users
                    SET 
                        username = ?,
                        email = ?,
                        fName = ?,
                        lName = ?,
                        streetAddress = ?,
                        city = ?,
                        state = ?,
                        postCode = ?
                    WHERE
                        id = ?
                    """,
                      (
                          req['username'],
                          req['email'],
                          req['fName'],
                          req['lName'],
                          req['streetAddress'],
                          req['city'],
                          req['state'],
                          req['postCode'],
                          user_id
                      )
                      )
            self.db.commit()
        except sqlite3.Error as e:
            log.error(e)
            raise Exception

    def get_password(self, user_num):
        """
        Checks if the password is correct.
        Accepts:
            user_num (int): User id of logged in user
        Returns:
            user's password
        """
        c = self.db.cursor()
        try:
            c.execute("SELECT password FROM Users WHERE id = ?",
                      (user_num,))
            results = c.fetchone()
            return results[0]
        except sqlite3.Error as e:
            log.error(e)
            raise Exception

    def set_book_points(self, book_id, points):
        """
        Changes the number of points for book
        Accepts:
            book_id (int): UserBooks.id
            points (int): UserBooks.points
        """
        c = self.db.cursor()
        try:
            c.execute("""
                    UPDATE
                        UserBooks
                    SET
                        points = ?
                    WHERE
                        id = ?
                    """,
                      (points, book_id))
            self.db.commit()
        except sqlite3.Error as e:
            log.error(f"Error changing points of book.  Error {e}")
            raise Exception

    def set_password(self, user_num, password):
        """
        Changes the user password.
        Accepts:
            user_num (int): Logged in user ID number in Users table
            password (string): new password
        Returns:
            None
        """
        c = self.db.cursor()
        try:
            c.execute("UPDATE Users SET password = ? WHERE id = ?",
                      (password, user_num))
            self.db.commit()
            return
        except sqlite3.Error as e:
            log.error(e)
            raise Exception

    def get_recent_additions(self, num):
        """
        Returns the most recent available additions to the site.
        Accepts:
            num (int): Number of recent additions to be returned
        Returns:
            Array of Row objects
        """
        c = self.db.cursor()
        try:
            c.execute("""SELECT
                    title,
                    author,
                    ISBN,
                    externalLink,
                    IFNULL(coverImageUrl, '/static/images/book.png') AS coverImageUrl,
                    CopyQualities.qualityDescription AS copyQuality,
                    Users.username AS listingUser,
                    UserBooks.id AS userBooksId,
                    UserBooks.userId AS userId,
                    CAST ((julianday('now') - julianday(UserBooks.dateCreated)) AS INTEGER) AS timeHere,
                    UserBooks.points as pointsNeeded
                    FROM Books 
                    INNER JOIN UserBooks 
                        on Books.id = UserBooks.bookId
                    INNER JOIN CopyQualities 
                        on UserBooks.copyQualityId = CopyQualities.id
                    INNER JOIN Users
                        on UserBooks.userId = Users.id
                    WHERE UserBooks.available == 1
                    ORDER BY
                    UserBooks.dateCreated DESC
                    LIMIT ?""",
                      (num,))
            recent_books = c.fetchall()
            return recent_books
        except sqlite3.Error as e:
            log.error(e)
            return {}

    def get_books_by_ISBN(self, ISBN):
        """
        Checks UserBooks table for all books with ISBN.
        Accepts:
            ISBN (string): ISBN search criteria
        Returns:
            Array of Row objects
        """
        c = self.db.cursor()
        try:
            c.execute("""SELECT
                    title,
                    author,
                    ISBN,
                    externalLink,
                    Users.username as listingUser,
                    CopyQualities.qualityDescription as copyQuality,
                    CAST ((julianday('now') - julianday(UserBooks.dateCreated)) AS INTEGER) AS timeHere,
                    UserBooks.points as pointsNeeded,
                    UserBooks.id as userBooksId,
                    UserBooks.userId AS userId,
                    Books.id AS booksId,
                    IFNULL(coverImageUrl, '/static/images/book.png') AS coverImageUrl
                    FROM Books
                    INNER JOIN UserBooks
                        on Books.id = UserBooks.bookId
                    INNER JOIN CopyQualities
                        on UserBooks.copyQualityId = CopyQualities.id
                    INNER JOIN Users
                        on UserBooks.userId = Users.id
                    WHERE
                        ISBN = ? AND
                        UserBooks.available == 1
                    ORDER BY
                        UserBooks.dateCreated
                        """,
                      (ISBN,))
            isbn_match = c.fetchall()
            log.info("BSDB: Get_Books_By_ISBN (local) Results")
            self.print_results(isbn_match)
            return isbn_match
        except sqlite3.Error as e:
            log.error(e)
            return {}

    def get_books_by_author_and_title(self, author, title):
        """
        Checks Books table for books with both author and title match.
        Accepts:
            author (string): author search criteria
            title (string): title search criteria
        Returns:
            Array of Row objects
        """
        c = self.db.cursor()
        if len(author) == 0 or len(title) == 0:
            return {}
        try:
            c.execute("""SELECT
                    title,
                    author,
                    ISBN,
                    externalLink,
                    Users.username as listingUser,
                    CopyQualities.qualityDescription as copyQuality,
                    CAST ((julianday('now') - julianday(UserBooks.dateCreated)) AS INTEGER) AS timeHere,
                    UserBooks.points as pointsNeeded,
                    UserBooks.id as userBooksId,
                    UserBooks.userId AS userId,
                    Books.id AS booksId,
                    IFNULL(coverImageUrl, '/static/images/book.png') AS coverImageUrl
                    FROM Books
                    INNER JOIN UserBooks
                        on Books.id = UserBooks.bookId
                    INNER JOIN CopyQualities
                        on UserBooks.copyQualityId = CopyQualities.id
                    INNER JOIN Users
                        on UserBooks.userId = Users.id
                    WHERE
                        author LIKE '%'||?||'%'
                    AND
                        title LIKE '%'||?||'%'
                    AND
                        UserBooks.available == 1
                    ORDER BY
                        author = ? DESC,
                        title = ? DESC,
                        author LIKE ?||'%' DESC,
                        author LIKE '%'||? DESC,
                        author
                        """,
                      (author, title, author, title, author, author))
            author_and_title_match = c.fetchall()
            log.info("BSDB: get_books_by_author_and_title (local) Results")
            self.print_results(author_and_title_match)
            return author_and_title_match
        except sqlite3.Error as e:
            log.error(e)
            return {}

    def get_books_by_author_or_title(self, author, title):
        """
        Checks Books table for books with author or title match.
        Accepts:
            author (string): author search criteria
            title (string): title search criteria
        Returns:
            Array of Row objects
        """
        if len(author) == len(title) == 0:
            return {}
        query_start = """
            SELECT 
                title, 
                author, 
                ISBN, 
                externalLink,
                Users.username as listingUser,
                UserBooks.userId AS userId,
                CopyQualities.qualityDescription as copyQuality,
                Books.id AS booksId,
                CAST 
                    ((julianday('now') - julianday(UserBooks.dateCreated)) 
                        AS INTEGER) AS timeHere,
                UserBooks.points as pointsNeeded,
                UserBooks.id as userBooksId,
                IFNULL(coverImageUrl, '/static/images/book.png') AS coverImageUrl
            FROM Books
            INNER JOIN UserBooks
                on Books.id = UserBooks.bookId
            INNER JOIN CopyQualities
                on UserBooks.copyQualityId = CopyQualities.id
            INNER JOIN Users
                on UserBooks.userId = Users.id
            """
        query_middle = " WHERE UserBooks.available == 1 AND ("
        query_end = " ORDER BY "
        params = []
        author_exists = title_exists = False
        if len(author) > 0:
            author_exists = True
        if len(title) > 0:
            title_exists = True
        if author_exists:
            query_middle += "author LIKE '%'||?||'%' "
            params.append(author)
            if title_exists:
                query_middle += " OR "
        if title_exists:
            query_middle += "title LIKE '%'||?||'%'"
            query_end += " title = ? DESC,"
            params += [title, title]
        if author_exists:
            query_end += " author = ? DESC,"
            params.append(author)
        if title_exists:
            query_end += " title LIKE ?||'%' DESC,"
            params.append(title)
        if author_exists:
            query_end += " author LIKE ?||'%' DESC,"
            params.append(author)
        if title_exists:
            query_end += " title LIKE '%'||? DESC,"
            params.append(title)
        if author_exists:
            query_end += " author LIKE '%'||? DESC,"
            params.append(author)
        query_middle += ")"
        query_end += " author"
        query = query_start + query_middle + query_end
        params = tuple(params)
        c = self.db.cursor()
        try:
            c.execute(query, params)
            author_or_title_match = c.fetchall()
            log.info("BSDB: get_books_by_author_or_title (local) Results")
            self.print_results(author_or_title_match)
            return author_or_title_match
        except sqlite3.Error as e:
            log.error(e)
            return {}

    def print_results(self, rows):
        """
        Prints results.
        Accepts:
            rows (Row objects): returns from SQL query
        Returns:
            None
        """
        print("Printing Search Results:")
        i = 1
        for row in rows:
            print(f"\t Result #{i}:")
            for key in row.keys():
                print(f"\t\t {key}: {row[key]}")
            i += 1
        return

    def get_available_copies(self, book_id, user_num):
        """
        Get_copies returns the available copies of the requested book that are
            not in the library of the given user.
        Accepts:
            book_id (int): Books.id
            user_num (int): Users.id
        Returns:
            List of Rows
        """
        c = self.db.cursor()
        try:
            c.execute("""
                    SELECT
                        UserBooks.id AS userBooksId,
                        UserBooks.userId AS userId,
                        UserBooks.points AS points,
                        CAST 
                            ((julianday('now') - 
                                    julianday(UserBooks.dateCreated)) 
                                AS INTEGER) AS timeHere,
                        Books.title AS title,
                        Books.author AS author,
                        Books.coverImageUrl AS coverImageUrl,
                        Users.username AS username,
                        CopyQualities.qualityDescription AS qualityDescription
                    FROM
                        UserBooks INNER JOIN 
                        Books on UserBooks.bookId = Books.id INNER JOIN
                        CopyQualities on UserBooks.copyQualityId = 
                                    CopyQualities.id INNER JOIN
                        Users on UserBooks.userId = Users.id
                    WHERE
                        Books.id = ? AND
                        UserBooks.available = 1 AND
                        UserBooks.userId != ?
                        """,
                      (book_id, user_num))
            rows = c.fetchall()
            log.info(f"Fetched all available books for Book {book_id} that are not owned by {user_num}")
        except sqlite3.Error as e:
            log.error(f"Error fetching available books for Book {book_id} that are not owned by{user_num} -- {e}")
            raise Exception
        return rows

    def get_wishlists_by_userid(self, user_id):
        """
        Get_wishlists_by_userid returns all the wishlists associated with a
            user.
        Accepts:
            user_id (int): Users.id
        Returns:
            List of sqlite3 Row objects
        """
        c = self.db.cursor()
        try:
            c.execute("""
                        SELECT 
                            id
                        FROM 
                            Wishlists 
                        WHERE 
                            userId = ?""",
                      (user_id,))
            rows = c.fetchall()
        except sqlite3.Error as e:
            log.error(f"{e}")
            log.error(f"Error getting wishlists for user {user_id}")
            raise Exception
        return rows

    def get_book_details_for_wishlist(self, wishlist_id):
        """
        Get_book_details_for_wishlsts gets the necessary information for a row
            on the `user/my-wishlist` page.
        Accepts:
            wishlist_id (int): Wishlists.id
        Returns:
            List of sqlite3 Row objects
        """
        c = self.db.cursor()
        try:
            c.execute("""
                        SELECT
                            Books.title AS title, 
                            Books.coverImageUrl AS coverImageUrl,
                            Books.author AS author,
                            Books.ISBN AS ISBN,
                            COUNT(UserBooks.id) AS numberAvailable,
                            min(UserBooks.points) AS minPoints,
                            WishlistsBooks.wishlistId AS wishlistId,
                            Books.id AS bookId
                        FROM 
                            WishlistsBooks 
                                INNER JOIN 
                            Books 
                                ON
                                    WishlistsBooks.bookId=Books.id 
                                INNER JOIN
                            Wishlists
                                ON
                                    WishlistsBooks.wishlistId = Wishlists.id
                                LEFT JOIN
                            UserBooks
                                ON
                                    WishlistsBooks.bookId = UserBooks.bookId 
                        WHERE
                            WishlistsBooks.wishlistId = ? 
                                AND
                            (
                                UserBooks.userId IS NULL OR
                                (
                                    UserBooks.userId != Wishlists.userId
                                        AND
                                    UserBooks.available = 1
                                )
                            )
                        GROUP BY
                            WishlistsBooks.bookId""",
                      (wishlist_id,))
            rows = c.fetchall()
        except sqlite3.Error as e:
            log.error(f"Error getting books in wishlist {wishlist_id} -- {e}")
            raise Exception
        return rows

    def get_current_user_points(self, user_num):
        """
        Get_current_user_points returns the number of points of the requested
            user.
        Accepts:
            user_num (int): User ID number
        Returns:
            Number of points that user has (int)
        """
        c = self.db.cursor()
        try:
            c.execute("""
                    SELECT
                        points
                    FROM
                        Users
                    WHERE
                        Users.id = ?
                    """,
                      (user_num,))
            values = c.fetchone()
            return values[0]
        except sqlite3.Error as e:
            log.error(e)
            raise Exception

    def request_book(self, book, user_num):
        """
        Request_book places a request on UserBook entry `book`, for user 
            `user_num`.
        Accepts:
            book (dict):  UserBook information
            user_num (int): User ID of requester
        Returns:
            points left for requesting user (int)
        """
        c = self.db.cursor()
        # Make sure user still has enough points
        try:
            points_available = self.get_current_user_points(user_num)
        except sqlite3.Error as e:
            log.error(f"Error trying to confirm user {user_num} has sufficient points. {e}")
            raise Exception
        #TODO: Fix 'POINTSNEEDED"
        if points_available < book['pointsNeeded']:
            log.warning(f"Requesting user does not have sufficient points for the trade.")
            raise Exception
        # Make sure book is still available
        try:
            c.execute("""
                    SELECT
                        available
                    FROM
                        UserBooks
                    WHERE
                        id = ?
                    """,
                      (book['userBooksId'],))
            availability = c.fetchone()[0]
            if availability != 1:
                log.warning(f"Book with UserBooks id {book['userBooksId']} is not available.")
                raise Exception
        except sqlite3.Error as e:
            log.error(
                f"Failed to see if book with UserBooks id {book['userBooksId']} is available or not -- {e}")
            raise Exception
        # Insert trade
        try:
            c.execute("""
                INSERT INTO Trades
                    (userRequestedId, userBookId, statusId)
                VALUES
                    (?, ?, ?)
                """,
                      (user_num, book['userBooksId'], 2))
            self.db.commit()
        except sqlite3.Error as e:
            log.error(f"{e}")
            raise Exception
        # Update Requesting User's points
        try:
            c.execute("""
                UPDATE
                    Users
                SET
                    points = points - ?
                WHERE
                    id = ?
                """,
                      (book['pointsNeeded'], user_num))
            self.db.commit()
        except sqlite3.Error as e:
            log.error(f"{e}")
            raise Exception
        # Update availability of UserBook entry
        try:
            c.execute("""
                UPDATE
                    UserBooks
                SET
                    available = 0
                WHERE
                    id = ?
                """,
                      (book['userBooksId'],))
            self.db.commit()
        except sqlite3.Error as e:
            log.error(f"{e}")
            raise Exception
        # Get current user's current point value
        try:
            c.execute("""
                SELECT
                    points
                FROM
                    Users
                WHERE
                    id = ?
                """,
                      (user_num,))
            row = c.fetchone()
            points_available = row[0]
        except sqlite3.Error as e:
            log.error(f"{e}")
            raise Exception
        return points_available

    def reject_trade(self, user_books_id):
        """
        Reject_Trade performs the database work necessary for rejecting the trade:
            Listing user has book removed from their pending trades list
            Requesting user has their points restored
            Book marked as available once more
        Accepts:
            user_books_id (int):  UserBooksId number of requested book
        Returns:
            None
        """
        c = self.db.cursor()
        # Change Trade state
        try:
            c.execute("""
                    UPDATE
                        Trades
                    SET
                        statusId = 4
                    WHERE
                        userBookId = ?
                        """,
                      (user_books_id,))
            self.db.commit()
            log.info(f"trade for book {user_books_id} changed to 'rejected by user'")
        except sqlite3.Error as e:
            log.error(
                f"Error {e}.  Failed to change the trade status for UserBooks book number {user_books_id}")
            flash("Error marking trade as rejected", "warning")
            raise Exception
        # Return points to requesting User
        try:
            c.execute("""
                    UPDATE
                        Users
                    SET
                        points = points + (
                            SELECT 
                                points
                            FROM 
                                UserBooks 
                            WHERE
                                id = ?
                                )
                    WHERE
                        id =  (
                            SELECT
                                userRequestedId
                            FROM
                                Trades
                            WHERE
                                userBookId = ?
                                )
                    """,
                      (user_books_id, user_books_id))
            self.db.commit()
            log.info(f"User received their points back")
        except sqlite3.Error as e:
            log.error(
                f"Error {e}.  Failed to return points to the requesting user for book number {user_books_id}")
            flash("Error returning points to requesting user", "warning")
            raise Exception
        # Set book as available
        try:
            c.execute("""
                    UPDATE
                        UserBooks
                    SET
                        available = 1
                    WHERE
                        id = ?
                    """,
                      (user_books_id,))
            self.db.commit()
            log.info(f" Book {user_books_id} set as avialable again")
        except sqlite3.Error as e:
            log.error(
                f"Error {e}.  Failed to set the book number {user_books_id} as available.")
            flash("Error marking the book as available", "warning")
            raise Exception
        return

    def get_login_user(self, username):
        self.db.row_factory = sqlite3.Row

        # Username check
        user = self.db.execute("SELECT * FROM Users WHERE username = ?",
                               (username,)).fetchone()
        if user is None:
            user = self.db.execute("SELECT * FROM Users WHERE email = ?",
                                   (username,)).fetchone()

        return user

    def is_user_book_owner(self, user_num, user_books_id):
        """
        Is_user_book_owner confirms that the user is the owner of the book.
        Accepts:
            user_num (int): Users.id
            user_books_id: UserBooks.id
        Returns:
            True if the user is the book owner, false otherwise
        """
        c = self.db.cursor()
        try:
            c.execute("""
                    SELECT
                        userId
                    FROM
                        UserBooks
                    WHERE
                        id = ?
                    """,
                      (user_books_id,))
            rows = c.fetchall()
            if len(rows) != 1:
                log.error(
                    f"Wrong number of book owners for UserBooks number {user_books_id}")
                raise Exception
            owner = rows[0]
            return owner[0] == user_num
        except sqlite3.Error:
            log.error(f"Wrong book owner for UserBooks number {user_books_id}")
            raise Exception


def get_bsdb() -> BookSwapDatabase:
    return BookSwapDatabase()
