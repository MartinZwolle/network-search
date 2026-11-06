"""Regression tests for scope and idempotence of the Instagram archive importer."""
import io
import json
import sqlite3
import unittest
import zipfile
from app.instagram import migrate, import_archive


class InstagramImportTests(unittest.TestCase):
    def test_scope_and_reimport(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        migrate(db)
        buffer = io.BytesIO()
        payloads = {
            "connections/followers_and_following/following.json":
                {"relationships_following": [{"title": "example_person", "string_list_data": []}]},
            "connections/followers_and_following/followers_1.json":
                [{"title": "", "string_list_data": [{"value": "example_person"}]}],
            "your_instagram_activity/messages/inbox/person_123/message_1.json":
                {"thread_path": "inbox/person_123", "messages": [
                    {"sender_name": "Example", "timestamp_ms": 1700000000000, "content": "Hallo"}]},
            "your_instagram_activity/messages/message_requests/spam_456/message_1.json":
                {"messages": [{"sender_name": "Spam", "timestamp_ms": 1700000000000,
                              "content": "NEVER_IMPORT"}]},
            "connections/contacts/synced_contacts.json": {"contacts": ["NEVER_IMPORT"]},
        }
        with zipfile.ZipFile(buffer, "w") as z:
            for path, body in payloads.items():
                z.writestr(path, json.dumps(body))
        data = buffer.getvalue()
        for _ in range(2):
            result = import_archive(db, data)
            self.assertEqual(result["following"], 1)
            self.assertEqual(result["followers"], 1)
        account = db.execute("SELECT * FROM instagram_accounts").fetchone()
        self.assertEqual((account["follows"], account["follower"]), (1, 1))
        rows = db.execute("SELECT content FROM instagram_messages").fetchall()
        self.assertEqual([row["content"] for row in rows], ["Hallo"])


if __name__ == "__main__":
    unittest.main()
