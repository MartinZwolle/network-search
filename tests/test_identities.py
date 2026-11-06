import sqlite3
import unittest
from app.identities import compact, migrate, candidates, link, unlink


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE contacts(url TEXT PRIMARY KEY, first_name TEXT, last_name TEXT);
        CREATE TABLE instagram_accounts(username TEXT PRIMARY KEY);
        INSERT INTO contacts VALUES ('https://linkedin.com/in/ilse', 'Ilse', 'Wintermans');
        INSERT INTO instagram_accounts VALUES ('ilsewintermans');
        INSERT INTO instagram_accounts VALUES ('ilsesomethingelse');
        """)
        migrate(self.db)

    def test_compact_search_and_confirmation(self):
        self.assertEqual(compact("Ilse Wintermans"), "ilsewintermans")
        contacts = self.db.execute("SELECT * FROM contacts").fetchall()
        ig = self.db.execute("SELECT * FROM instagram_accounts").fetchall()
        self.assertEqual(len(candidates(self.db, contacts, ig)), 1)
        link(self.db, contacts[0]["url"], "ilsewintermans")
        self.assertEqual(len(candidates(self.db, contacts, ig)), 0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM profile_links").fetchone()[0], 1)
        unlink(self.db, contacts[0]["url"], "ilsewintermans")
        self.assertEqual(len(candidates(self.db, contacts, ig)), 1)

    def test_unknown_account_refused(self):
        with self.assertRaises(ValueError):
            link(self.db, "https://linkedin.com/in/ilse", "unknown")


if __name__ == "__main__":
    unittest.main()
