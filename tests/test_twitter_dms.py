import sqlite3
import unittest

from app.person_ids import migrate as migrate_people, ensure_account
from app.twitter import migrate as migrate_twitter
from app.twitter_dms import conversations, thread


class TwitterDmBrowserTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        migrate_people(self.db)
        migrate_twitter(self.db)
        self.db.execute("INSERT INTO twitter_accounts(user_id,is_self) VALUES ('100',1)")
        self.db.execute("INSERT INTO twitter_accounts(user_id) VALUES ('200')")
        self.db.execute("INSERT INTO twitter_accounts(user_id) VALUES ('300')")
        for uid in ("100","200","300"):
            ensure_account(self.db,"twitter",uid)
        self.db.execute("INSERT INTO twitter_handles VALUES ('200','oudegebruiker','mention','','')")
        self.db.executemany("""INSERT INTO twitter_dms
            (dm_id,conversation_id,sender_id,recipient_id,created_at,content)
            VALUES (?,?,?,?,?,?)""",[
            ("1","100-200","100","200","2010-01-02T12:00:00+00:00","Hoi"),
            ("2","100-200","200","100","2010-01-02T12:01:00+00:00","Antwoord"),
            ("3","100-300","300","100","2011-01-02T12:01:00+00:00","Vergeten account <script>"),
        ])

    def test_all_conversations_including_unknown_handles(self):
        html=conversations(self.db)
        self.assertIn("2 gesprekken",html)
        self.assertIn("oudegebruiker",html)
        self.assertIn("Twitter-ID 300",html)
        self.assertIn("conversation_id=100-300",html)

    def test_threads_show_both_sides_and_escape_text(self):
        html=thread(self.db,"100-200")
        self.assertIn("Hoi",html)
        self.assertIn("Antwoord",html)
        self.assertIn("Jij",html)
        other=thread(self.db,"100-300")
        self.assertIn("&lt;script&gt;",other)
        self.assertNotIn("<script>",other)

    def test_missing_thread_returns_none(self):
        self.assertIsNone(thread(self.db,"does-not-exist"))


if __name__=="__main__":
    unittest.main()
