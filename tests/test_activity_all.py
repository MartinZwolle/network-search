import sqlite3
import unittest

from app.activity_all import gather, render
from app.person_ids import migrate as migrate_people, ensure_account
from app.facebook import migrate as migrate_fb
from app.instagram import migrate as migrate_ig
from app.context import migrate as migrate_context
from app.manual import migrate as migrate_manual
from app.twitter import migrate as migrate_twitter
from app.reviewed import migrate as migrate_reviewed


class CrossPlatformActivityTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.db.row_factory=sqlite3.Row
        self.db.executescript("""
        CREATE TABLE contacts(url TEXT PRIMARY KEY, first_name TEXT, last_name TEXT);
        CREATE TABLE messages(message_key TEXT PRIMARY KEY, date TEXT);
        CREATE TABLE contact_messages(contact_url TEXT, message_key TEXT,
            PRIMARY KEY(contact_url,message_key));
        CREATE TABLE employment_history(id INTEGER PRIMARY KEY,
            contact_url TEXT, company TEXT, position TEXT, first_seen_at TEXT);
        INSERT INTO contacts VALUES('https://linkedin.com/in/ilse','Ilse','Wintermans');
        INSERT INTO messages VALUES('li1','2018-01-01');
        INSERT INTO contact_messages VALUES('https://linkedin.com/in/ilse','li1');
        """)
        migrate_people(self.db)
        migrate_context(self.db)
        migrate_manual(self.db)
        migrate_ig(self.db)
        migrate_fb(self.db)
        migrate_twitter(self.db)
        migrate_reviewed(self.db)
        self.li=ensure_account(self.db,"linkedin","https://linkedin.com/in/ilse")
        self.fb=ensure_account(self.db,"facebook","name:jan jansen")
        self.db.execute("INSERT INTO facebook_people VALUES('name:jan jansen','Jan Jansen','',1)")
        self.db.execute("INSERT INTO facebook_threads VALUES('t1','Chat','[]',0)")
        self.db.execute("INSERT INTO facebook_messages VALUES('fb1','t1','Jan Jansen','name:jan jansen',1527811200000,'Hoi')")
        self.db.execute("INSERT INTO facebook_messages VALUES('fb2','t1','Jan Jansen','name:jan jansen',1527811201000,'Hallo')")
        self.db.execute("INSERT INTO facebook_messages VALUES('fb3','t1','Jan Jansen','name:jan jansen',1527811202000,'Dag')")
        self.db.execute("INSERT INTO instagram_accounts VALUES('rosa',1,1,'2020-01-01')")
        self.ig=ensure_account(self.db,"instagram","rosa")
        self.db.execute("INSERT INTO instagram_messages VALUES('ig1','thread1','rosa','2019-01-01','Hoi')")
        self.db.commit()

    def test_annual_counts_across_platforms(self):
        annual,people,unknown=gather(self.db)
        self.assertEqual(annual[2018]["LinkedIn"],1)
        self.assertEqual(annual[2018]["Facebook"],3)
        self.assertEqual(annual[2019]["Instagram"],1)
        self.assertEqual(people[self.fb]["messages"],3)
        self.assertEqual(people[self.li]["messages"],1)
        self.assertEqual(people[self.ig]["messages"],1)
        self.assertEqual(sum(unknown.values()),0)

    def test_filter_links_and_real_profiles(self):
        page=render(self.db,"all")
        self.assertIn("LinkedIn",page)
        self.assertIn("Instagram",page)
        self.assertIn("Facebook",page)
        self.assertIn("/person/"+str(self.fb),page)
        self.assertIn('href="/activity?source=facebook"',page)
        self.assertIn("geen volledig beeld",page)
        facebook=render(self.db,"facebook")
        self.assertIn("Facebook",facebook)
        self.assertIn("Schakel naar",facebook)


if __name__ == "__main__":
    unittest.main()
