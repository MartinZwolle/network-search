import sqlite3
import unittest

from app.context import migrate as migrate_context, save, get, person_tags, parse_network_tags
from app.identities import migrate as migrate_identities, link
from app.person_ids import migrate as migrate_people, sync, account_person


class FarleyContextTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE contacts(url TEXT PRIMARY KEY, first_name TEXT,last_name TEXT);
        CREATE TABLE instagram_accounts(username TEXT PRIMARY KEY,follows INTEGER,follower INTEGER);
        INSERT INTO contacts VALUES ('https://linkedin.com/in/rogier','Rogier','Brouwer');
        INSERT INTO instagram_accounts VALUES ('brouwerijrobier',1,1);
        """)
        migrate_identities(self.db)
        migrate_people(self.db)
        migrate_context(self.db)
        sync(self.db)

    def test_overlapping_groups_and_persistent_profile(self):
        pid = account_person(self.db,"linkedin","https://linkedin.com/in/rogier")
        save(self.db, pid, how_known="Oud-collega", background="Brouwer",
             interests="Bier, muziek, bier", remember="Vraag naar de nieuwe IPA",
             network_tags="#wehkamp, #bierproefclub")
        self.assertEqual(person_tags(self.db,pid), ["bierproefclub","wehkamp"])
        self.assertEqual(get(self.db,pid)["interests"],"Bier, muziek")
        link(self.db,"https://linkedin.com/in/rogier","brouwerijrobier")
        self.assertEqual(get(self.db,pid)["how_known"],"Oud-collega")
        self.assertEqual(person_tags(self.db,pid),["bierproefclub","wehkamp"])
        sync(self.db)
        self.assertEqual(person_tags(self.db,pid),["bierproefclub","wehkamp"])

    def test_merge_preserves_both_sets_of_tags_and_notes(self):
        li = account_person(self.db,"linkedin","https://linkedin.com/in/rogier")
        ig = account_person(self.db,"instagram","brouwerijrobier")
        save(self.db,li,how_known="Collega",network_tags="#wehkamp")
        save(self.db,ig,background="Instagram-brouwer",network_tags="#bierproefclub")
        link(self.db,"https://linkedin.com/in/rogier","brouwerijrobier")
        self.assertEqual(person_tags(self.db,li),["bierproefclub","wehkamp"])
        self.assertEqual(get(self.db,li)["background"],"Instagram-brouwer")
        self.assertEqual(get(self.db,li)["how_known"],"Collega")

    def test_bad_tag(self):
        with self.assertRaises(ValueError):
            parse_network_tags("#tag!bad")


if __name__ == "__main__":
    unittest.main()
