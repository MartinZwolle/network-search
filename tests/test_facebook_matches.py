import sqlite3
import unittest
from app.person_ids import migrate as migrate_people, ensure_account, merge_people
from app.context import migrate as migrate_context
from app.manual import migrate as migrate_manual
from app.facebook import migrate as migrate_facebook
from app.identities import migrate as migrate_identities, migrate_facebook_matches, facebook_candidates, reject_facebook_match


class FacebookMatchTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE contacts(url TEXT PRIMARY KEY, first_name TEXT,
                last_name TEXT, company TEXT, position TEXT);
            CREATE TABLE instagram_accounts(username TEXT PRIMARY KEY);
            CREATE TABLE employment_history(id INTEGER PRIMARY KEY,
                contact_url TEXT, company TEXT, position TEXT, first_seen_at TEXT);
            INSERT INTO contacts VALUES('https://linkedin.com/in/jan', 'Jan',
                'Jansen', '', '');
        """)
        migrate_identities(self.db)
        migrate_people(self.db)
        migrate_context(self.db)
        migrate_manual(self.db)
        migrate_facebook(self.db)
        migrate_facebook_matches(self.db)
        self.li = ensure_account(self.db, "linkedin", "https://linkedin.com/in/jan")
        self.fb = ensure_account(self.db, "facebook", "name:jan jansen")
        self.db.execute(
            "INSERT INTO facebook_people VALUES('name:jan jansen','Jan Jansen','',1)"
        )

    def test_suggest_only_without_automatic_merging(self):
        matches = facebook_candidates(self.db)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["target_person_id"], self.li)
        self.assertNotEqual(matches[0]["facebook_person_id"], self.li)

    def test_reject_persists(self):
        reject_facebook_match(self.db, "name:jan jansen", self.li)
        self.assertEqual(facebook_candidates(self.db), [])

    def test_confirmed_merge_disappears_from_candidates(self):
        merge_people(self.db, self.li, self.fb)
        self.assertEqual(facebook_candidates(self.db), [])


if __name__ == "__main__":
    unittest.main()
