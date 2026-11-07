import sqlite3
import unittest

from app.message_people import linkedin_key, contact_lookup, author_profile
from app.person_ids import migrate, sync
from app.identities import migrate as migrate_identities


class MessageSenderLinkTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE contacts(url TEXT PRIMARY KEY);
            CREATE TABLE instagram_accounts(username TEXT PRIMARY KEY);
            INSERT INTO contacts VALUES('https://www.linkedin.com/in/ilse-wintermans/');
            INSERT INTO contacts VALUES('https://www.linkedin.com/in/other');
        """)
        migrate_identities(self.db)
        migrate(self.db)
        sync(self.db)

    def test_link_same_person_using_url_path(self):
        lookup = contact_lookup(self.db)
        msg = {"sender_url": "https://nl.linkedin.com/in/ilse-wintermans?trk=foo"}
        expected = self.db.execute(
            "SELECT person_id FROM farley_accounts WHERE account_key LIKE '%ilse-wintermans%'"
        ).fetchone()[0]
        self.assertEqual(author_profile(msg, lookup), expected)

    def test_do_not_guess_by_name_or_unknown_url(self):
        lookup = contact_lookup(self.db)
        self.assertIsNone(author_profile({"sender_url": ""}, lookup))
        self.assertIsNone(author_profile({"sender_url": "https://linkedin.com/in/unknown"}, lookup))
        self.assertIsNone(author_profile({"sender_url": "https://example.com/profile/ilse"}, lookup))

    def test_profile_key_case_and_trailing_slash(self):
        self.assertEqual(linkedin_key("linkedin.com/in/ILSE-WINTERMANS/"),
                         "/in/ilse-wintermans")


if __name__ == "__main__":
    unittest.main()
