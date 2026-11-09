import sqlite3
import unittest
from app.identities import compact, migrate, candidates, link, unlink, reject, restore, resolve_contact, all_candidates
from app.person_ids import migrate as migrate_people, sync as sync_people


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE contacts(url TEXT PRIMARY KEY, first_name TEXT, last_name TEXT, company TEXT DEFAULT '', position TEXT DEFAULT '');
        CREATE TABLE instagram_accounts(username TEXT PRIMARY KEY, follows INTEGER DEFAULT 1, follower INTEGER DEFAULT 0);
        INSERT INTO contacts VALUES ('https://linkedin.com/in/ilse', 'Ilse', 'Wintermans');
        INSERT INTO instagram_accounts(username) VALUES ('ilsewintermans');
        INSERT INTO instagram_accounts(username) VALUES ('ilsesomethingelse');
        """)
        migrate(self.db)
        migrate_people(self.db)
        sync_people(self.db)

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

    def test_reject_and_restore(self):
        contacts = self.db.execute("SELECT * FROM contacts").fetchall()
        ig = self.db.execute("SELECT * FROM instagram_accounts").fetchall()
        reject(self.db, contacts[0]["url"], "ilsewintermans")
        self.assertEqual(len(candidates(self.db, contacts, ig)), 0)
        self.assertEqual(len(all_candidates(self.db)), 0)
        restore(self.db, contacts[0]["url"], "ilsewintermans")
        self.assertEqual(len(candidates(self.db, contacts, ig)), 1)
        self.assertEqual(len(all_candidates(self.db)), 1)

    def test_manual_linking(self):
        url = resolve_contact(self.db, "Ilse Wintermans")
        self.assertEqual(url, "https://linkedin.com/in/ilse")
        self.assertEqual(resolve_contact(self.db, url), url)
        link(self.db, url, "ilsesomethingelse")
        self.assertEqual(
            self.db.execute("SELECT instagram_username FROM profile_links").fetchone()[0],
            "ilsesomethingelse"
        )
        with self.assertRaises(ValueError):
            resolve_contact(self.db, "Not Found")

    def test_unknown_account_refused(self):
        with self.assertRaises(ValueError):
            link(self.db, "https://linkedin.com/in/ilse", "unknown")


if __name__ == "__main__":
    unittest.main()
