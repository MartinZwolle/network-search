import sqlite3
import unittest
from app.person_ids import migrate as migrate_people, ensure_account
from app.twitter import migrate as migrate_twitter
from app.twitter_explore import page, _year_options, _people

class ExploreTwitterTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.db.row_factory=sqlite3.Row
        migrate_people(self.db)
        migrate_twitter(self.db)
        self.db.execute("INSERT INTO twitter_accounts(user_id,is_self) VALUES ('1',1)")
        self.db.execute("INSERT INTO twitter_accounts(user_id) VALUES ('2')")
        ensure_account(self.db,"twitter","2")
        self.db.execute("INSERT INTO twitter_handles VALUES ('2','oudaccount','reply','','')")
        for n in range(3):
            self.db.execute("""INSERT INTO twitter_tweets
                (tweet_id,author_id,created_at,content,reply_to_user_id)
                VALUES (?,?,?,?,?)""",(str(n+10),"1","2010-06-01T10:00:00+00:00",
                                    "Hallo "+str(n),"2"))
        self.db.execute("""INSERT INTO twitter_dms
            (dm_id,conversation_id,sender_id,recipient_id,created_at,content)
            VALUES ('20','1-2','2','1','2010-06-02T10:00:00+00:00','Privétekst')""")

    def test_year_and_reply_count(self):
        years=_year_options(self.db)
        self.assertEqual(years[0]["year"],"2010")
        self.assertEqual(years[0]["tweets"],3)
        self.assertEqual(years[0]["replies"],3)
        self.assertEqual(years[0]["dms"],1)

    def test_browsing_without_query(self):
        html=page(self.db,2010,"replies",1)
        self.assertIn("oudaccount",html)
        self.assertIn("Hallo 0",html)
        self.assertIn("Twitter ontdekken",html)
        self.assertNotIn("Privétekst",html)

    def test_dm_filter(self):
        html=page(self.db,2010,"dms",1)
        self.assertIn("Privétekst",html)
        self.assertNotIn("Hallo 0",html)

if __name__=="__main__":
    unittest.main()
