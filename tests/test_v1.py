"""Version 1 regression checks for navigation, reviews and identity safety."""
import sqlite3
import unittest

from app.person_ids import migrate as migrate_people, ensure_account, detach_account
from app.reviewed import migrate as migrate_reviewed, mark, reviewed
from app.twitter import migrate as migrate_twitter
from app.timeline_all import render as render_timeline
from app.ui import polish


class VersionOneTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.db.row_factory=sqlite3.Row
        migrate_people(self.db)

    def test_consistent_header_and_navigation(self):
        page='<!doctype html><html lang="nl"><title>Test</title><style>h1{}</style><h1>Twitter ontdekken</h1></html>'
        html=polish(page,"/twitter/explore")
        self.assertEqual(html.count('class="farley-shell"'),1)
        self.assertIn("Twitter ontdekken",html)
        self.assertIn('aria-current="page">Twitter-archief',html)
        self.assertIn('href="/matches"',html)
        self.assertIn('href="/tags"',html)
        self.assertEqual(html.count("<h1"),1)

    def test_home_still_has_original_header(self):
        page='<html><style></style><header><h1>Farley File</h1><nav><a href="/">Home</a></nav></header></html>'
        html=polish(page,"/")
        self.assertIn("<h1>Farley File</h1>",html)
        self.assertEqual(html.count("<header"),1)
        self.assertIn('href="/twitter"',html)

    def test_review_persists_and_follows_person_merges(self):
        migrate_reviewed(self.db)
        first=ensure_account(self.db,"twitter","100")
        other=ensure_account(self.db,"instagram","test")
        mark(self.db,first,True)
        self.assertIn(first,reviewed(self.db))
        self.db.execute("INSERT INTO farley_aliases(old_id,current_id) VALUES(?,?)",
                        (first,other))
        self.assertIn(other,reviewed(self.db))
        mark(self.db,other,False)
        # The old record must also be cleared when an alias was reviewed.
        self.assertNotIn(other,reviewed(self.db))

    def test_detaching_instagram_clears_legacy_link_and_keeps_other_accounts(self):
        self.db.execute("CREATE TABLE profile_links(linkedin_url TEXT,instagram_username TEXT)")
        pid=ensure_account(self.db,"linkedin","https://linkedin.com/in/test")
        ig=ensure_account(self.db,"instagram","test")
        self.db.execute("UPDATE farley_accounts SET person_id=? WHERE platform='instagram'",
                        (pid,))
        self.db.execute("INSERT INTO profile_links VALUES(?,?)",
                        ("https://linkedin.com/in/test","test"))
        new=detach_account(self.db,pid,"instagram","test")
        self.assertNotEqual(new,pid)
        self.assertEqual(self.db.execute(
            "SELECT person_id FROM farley_accounts WHERE platform='linkedin'"
        ).fetchone()[0],pid)
        self.assertEqual(self.db.execute(
            "SELECT person_id FROM farley_accounts WHERE platform='instagram'"
        ).fetchone()[0],new)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM profile_links").fetchone()[0],0)

    def test_twitter_timeline_provenance(self):
        migrate_twitter(self.db)
        pid=ensure_account(self.db,"twitter","200")
        self.db.execute("""INSERT INTO twitter_tweets
            (tweet_id,author_id,created_at,content,reply_to_user_id)
            VALUES ('10','100','2010-06-01T10:00:00+00:00','Hallo Twitter','200')""")
        self.db.execute("""INSERT INTO twitter_dms
            (dm_id,conversation_id,sender_id,recipient_id,created_at,content)
            VALUES ('20','100-200','200','100','2010-06-02T10:00:00+00:00','Geheim')""")
        html=render_timeline(self.db,pid,"twitter")
        self.assertIn("Hallo Twitter",html)
        self.assertIn("Twitter-DM-gesprek",html)
        self.assertIn("Alleen je eigen tweet",html)
        self.assertNotIn("Geheim",html)  # DM content stays on its own page


if __name__=="__main__":
    unittest.main()
