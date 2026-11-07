import sqlite3
import unittest

from app.context import migrate as migrate_context, save as save_context
from app.facebook import migrate as migrate_facebook
from app.identities import migrate as migrate_identities, migrate_facebook_matches
from app.manual import migrate as migrate_manual, create_person
from app.person_ids import migrate as migrate_people, ensure_account, merge_people
from app.smart_matches import migrate, candidates, reject, normalized


class SmartMatchTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.db.row_factory=sqlite3.Row
        self.db.executescript("""
        CREATE TABLE contacts(url TEXT PRIMARY KEY,first_name TEXT,last_name TEXT,
            company TEXT,position TEXT);
        CREATE TABLE instagram_accounts(username TEXT PRIMARY KEY);
        CREATE TABLE employment_history(id INTEGER PRIMARY KEY,
            contact_url TEXT,company TEXT,position TEXT,first_seen_at TEXT);
        """)
        migrate_identities(self.db)
        migrate_people(self.db)
        migrate_context(self.db)
        migrate_manual(self.db)
        migrate_facebook(self.db)
        migrate_facebook_matches(self.db)
        migrate(self.db)

    def linkedin(self,url,first,last,company=""):
        self.db.execute("INSERT INTO contacts VALUES (?,?,?,?,?)",
                        (url,first,last,company,""))
        return ensure_account(self.db,"linkedin",url)

    def facebook(self,name):
        key="name:"+name.casefold()
        self.db.execute("INSERT INTO facebook_people VALUES (?,?,?,?)",
                        (key,name,"",1))
        return ensure_account(self.db,"facebook",key)

    def test_accent_normalization_and_explanation(self):
        li=self.linkedin("https://linkedin.com/in/jose","José","García","CNV")
        fb=self.facebook("Jose Garcia")
        rows=candidates(self.db)
        self.assertEqual(len(rows),1)
        self.assertEqual({rows[0]["source_id"],rows[0]["target_id"]},{li,fb})
        self.assertIn("Dezelfde volledige naam",rows[0]["reasons"])
        self.assertEqual(rows[0]["target_id"],li)

    def test_company_supports_near_spelling_not_name_alone(self):
        li=self.linkedin("https://linkedin.com/in/marian","Marianne","Bakker","CNV")
        manual=create_person(self.db,"Mariane Bakker")
        self.assertEqual(candidates(self.db),[])
        # a shared employer is independent evidence for a similar surname/name
        self.db.execute("INSERT INTO farley_manual_jobs"
                        "(person_id,company,title,started,ended,note,created_at)"
                        " VALUES (?,?,?,?,?,?,?)",
                        (manual,"CNV","Adviseur","","","","2026-01-01"))
        rows=candidates(self.db)
        self.assertEqual(len(rows),1)
        self.assertIn("Sterk gelijkende naam",rows[0]["reasons"])
        self.assertTrue(any("Werkgever" in r for r in rows[0]["reasons"]))

    def test_shared_employer_different_people_not_match(self):
        self.linkedin("https://linkedin.com/in/a","Anna","Jansen","Wehkamp")
        self.facebook("Pieter Jansen")
        self.assertEqual(candidates(self.db),[])

    def test_rejection_is_persistent(self):
        li=self.linkedin("https://linkedin.com/in/jan","Jan","Jansen","")
        fb=self.facebook("Jan Jansen")
        self.assertEqual(len(candidates(self.db)),1)
        reject(self.db,li,fb)
        self.assertEqual(candidates(self.db),[])
        reject(self.db,fb,li)
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM farley_match_rejections").fetchone()[0],1)

    def test_confirmed_merge_disappears_and_preserves_manual_context(self):
        li=self.linkedin("https://linkedin.com/in/ilse","Ilse","Wintermans","")
        manual=create_person(self.db,"Ilse Wintermans")
        save_context(self.db,manual,how_known="Via muziek",network_tags="#muziek")
        self.assertEqual(len(candidates(self.db)),1)
        merge_people(self.db,li,manual)
        self.assertEqual(candidates(self.db),[])
        self.assertEqual(self.db.execute(
            "SELECT how_known FROM farley_context WHERE person_id=?", (li,)
        ).fetchone()[0],"Via muziek")

    def test_two_different_linkedin_accounts_not_suggested(self):
        self.linkedin("https://linkedin.com/in/jan1","Jan","Jansen")
        self.linkedin("https://linkedin.com/in/jan2","Jan","Jansen")
        self.assertEqual(candidates(self.db),[])

    def test_ig_handle_matches_full_name(self):
        li=self.linkedin("https://linkedin.com/in/karin","Karin","Janssen","")
        ig=ensure_account(self.db,"instagram","karinjanssen")
        rows=candidates(self.db)
        self.assertEqual(len(rows),1)
        self.assertEqual({rows[0]["target_id"],rows[0]["source_id"]},{li,ig})
        self.assertIn("Gebruikersnaam lijkt op de volledige naam",rows[0]["reasons"])

    def test_different_facebook_keys_never_merged(self):
        self.facebook("Jan Jansen")
        self.facebook("Ján Jansen")
        self.assertEqual(candidates(self.db),[])


if __name__=="__main__":
    unittest.main()
