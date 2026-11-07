import io
import json
import sqlite3
import unittest
import zipfile

from app.facebook import migrate as facebook_migrate, import_archive, find_messages
from app.person_ids import migrate as people_migrate, account_person
from app.manual import migrate as manual_migrate, display_name, employment
from app.context import migrate as context_migrate
from app.employment import migrate as employment_migrate
from app.identities import migrate as identity_migrate
from app.person_ids import merge_people


def archive():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        root = "Fb archief/"
        z.writestr(root + "friends/your_friends.json", json.dumps({
            "friends_v2": [{"name": "Ilse Wintermans", "timestamp": 1234567890}],
        }))
        z.writestr(root + "inbox/123456/message_1.json", json.dumps({
            "participants": [{"name": "Martin"}, {"name": "Ilse Wintermans"}],
            "title": "Ilse Wintermans",
            "messages": [
                {"sender_name": "Ilse Wintermans", "timestamp_ms": 1570000000000,
                 "content": "Zullen we weer eens afspreken?"},
                {"sender_name": "Martin", "timestamp_ms": 1570000010000,
                 "content": "Goed idee!"}
            ],
        }))
    return out.getvalue()


class FacebookTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE contacts(url TEXT PRIMARY KEY,first_name TEXT,last_name TEXT,
          company TEXT, position TEXT);
        CREATE TABLE instagram_accounts(username TEXT PRIMARY KEY);
        CREATE TABLE contact_messages(contact_url TEXT,message_key TEXT);
        CREATE TABLE employment_history(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          contact_url TEXT,company TEXT,position TEXT,first_seen_at TEXT,
          last_seen_at TEXT,superseded_at TEXT);
        INSERT INTO contacts VALUES('https://linkedin.com/in/ilse',
          'Ilse','Wintermans','Werk','Docent');
        """)
        identity_migrate(self.db)
        people_migrate(self.db)
        context_migrate(self.db)
        manual_migrate(self.db)
        facebook_migrate(self.db)

    def test_import_twice_is_idempotent_and_searchable(self):
        counts = import_archive(self.db, archive())
        self.assertEqual(counts["friends"], 1)
        self.assertEqual(counts["messages"], 2)
        self.assertEqual(counts["threads"], 1)
        found = find_messages(self.db, "weer eens afspreken")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["sender_name"], "Ilse Wintermans")
        self.assertEqual(import_archive(self.db, archive())["messages"], 0)
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM facebook_messages").fetchone()[0], 2)

    def test_facebook_identity_not_autolinked_and_manual_merge(self):
        import_archive(self.db, archive())
        li = account_person(self.db,"linkedin","https://linkedin.com/in/ilse")
        # The LinkedIn account is not seeded by importer itself, so seed it explicitly.
        from app.person_ids import ensure_account
        li = ensure_account(self.db,"linkedin","https://linkedin.com/in/ilse")
        fb = account_person(self.db,"facebook","name:ilse wintermans")
        self.assertNotEqual(li, fb)
        self.assertEqual(display_name(self.db, fb), "Ilse Wintermans")
        merge_people(self.db,li,fb)
        self.assertEqual(account_person(self.db,"facebook","name:ilse wintermans"),li)

    def test_malformed_archive_rejected(self):
        with self.assertRaises(ValueError):
            import_archive(self.db,b"not a zip")


if __name__ == "__main__":
    unittest.main()
