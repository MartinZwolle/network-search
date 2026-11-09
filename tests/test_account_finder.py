import sqlite3
import unittest

from app.account_finder import find, render
from app.person_ids import migrate as migrate_people, ensure_account
from app.twitter import migrate as migrate_twitter


class AccountFinderTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.db.row_factory=sqlite3.Row
        migrate_people(self.db)
        migrate_twitter(self.db)
        self.db.execute("""CREATE TABLE contacts(
            url TEXT PRIMARY KEY,first_name TEXT,last_name TEXT)""")
        self.db.execute("""CREATE TABLE facebook_people(
            fb_key TEXT PRIMARY KEY,display_name TEXT)""")
        self.db.execute("INSERT INTO contacts VALUES ('https://linkedin.com/in/jan','Jan','Jansen')")
        self.db.execute("INSERT INTO facebook_people VALUES ('name:jan jansen','Jan Jansen')")
        self.db.execute("INSERT INTO twitter_handles VALUES ('123','jan_jansen','reply','','')")
        for platform,key in [
            ("linkedin","https://linkedin.com/in/jan"),
            ("facebook","name:jan jansen"),("instagram","janjansen"),
            ("twitter","123")]:
            ensure_account(self.db,platform,key)

    def test_search_all_platforms(self):
        results=find(self.db,"all","jan")
        self.assertEqual({p for p,_,_ in results},
                         {"linkedin","facebook","instagram","twitter"})

    def test_wildcards_are_literal(self):
        self.assertEqual(find(self.db,"all","%%"),[])

    def test_search_form_does_not_auto_link(self):
        person=ensure_account(self.db,"linkedin","https://linkedin.com/in/jan")
        html=render(self.db,person,"twitter","jan")
        self.assertIn("jan_jansen",html)
        self.assertIn('action="/person/',html)
        self.assertIn('method="post"',html)
        self.assertIn("bewust",html.lower())


if __name__=="__main__":
    unittest.main()
