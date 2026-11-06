import sqlite3
import unittest

from app.context import migrate as context_migrate, save as save_context, get as get_context
from app.employment import migrate as employment_migrate, observe
from app.identities import migrate as identity_migrate
from app.manual import (migrate as manual_migrate, create_person, rename_person,
                        display_name, search_manual, save_job, employment, delete_manual_job)
from app.person_ids import (migrate as people_migrate, sync as sync_people,
                            account_person, merge_people)


class ManualPeopleTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE contacts(
          url TEXT PRIMARY KEY,first_name TEXT,last_name TEXT,email TEXT,
          company TEXT,position TEXT,connected_on TEXT
        );
        CREATE TABLE instagram_accounts(
          username TEXT PRIMARY KEY,follows INTEGER,follower INTEGER
        );
        INSERT INTO contacts VALUES
          ('https://linkedin.com/in/alex','Alex','Test','','Wehkamp','Engineer','');
        """)
        employment_migrate(self.db)
        identity_migrate(self.db)
        people_migrate(self.db)
        context_migrate(self.db)
        manual_migrate(self.db)
        sync_people(self.db)

    def test_person_without_social_account_can_be_found_and_renamed(self):
        pid = create_person(self.db, "  Petra   de  Vries  ")
        self.assertEqual(display_name(self.db, pid), "Petra de Vries")
        self.assertEqual(len(search_manual(self.db, "Petra")), 1)
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM farley_accounts WHERE person_id=?", (pid,)
        ).fetchone()[0], 0)
        rename_person(self.db, pid, "Petra van Dijk")
        self.assertEqual(display_name(self.db, pid), "Petra van Dijk")
        sync_people(self.db)
        self.assertEqual(display_name(self.db, pid), "Petra van Dijk")

    def test_jobs_before_and_after_current_date(self):
        pid = create_person(self.db, "Petra de Vries")
        save_job(self.db, pid, "School", "Docent", "2003-08-01", "2010-07-31")
        save_job(self.db, pid, "Toekomst", "Directeur", "2028-01-01")
        jobs = employment(self.db, pid)
        self.assertEqual({j["started"] for j in jobs}, {"2003-08-01", "2028-01-01"})
        historic = next(j for j in jobs if j["company"] == "School")
        save_job(self.db, pid, "College", "Docent", "2002-08-01",
                 "2010-07-31", job_id=historic["id"])
        self.assertIn("College", [j["company"] for j in employment(self.db,pid)])
        delete_manual_job(self.db, pid, historic["id"])
        self.assertNotIn("College", [j["company"] for j in employment(self.db,pid)])
        with self.assertRaises(ValueError):
            save_job(self.db, pid, "Bad", "Dates", "2028-01-01", "2027-01-01")

    def test_imported_jobs_edit_without_modifying_source(self):
        pid = account_person(self.db, "linkedin", "https://linkedin.com/in/alex")
        original = self.db.execute("SELECT * FROM employment_history").fetchone()
        save_job(self.db, pid, "Handmatig aangepast", "CTO",
                 "2018-01-01", "2022-12-31", history_id=original["id"])
        save_context(self.db,pid,how_known="Wehkamp",network_tags="#wehkamp")
        # A later import changes the raw LinkedIn observation, but not the correction.
        observe(self.db, "https://linkedin.com/in/alex", "Andere werkgever", "Lead",
                "2029-01-01T00:00:00Z")
        jobs = employment(self.db,pid)
        corrected = next(j for j in jobs if j["id"] == original["id"] and j["kind"] == "import")
        self.assertEqual(corrected["company"], "Handmatig aangepast")
        self.assertEqual(corrected["started"], "2018-01-01")
        self.assertEqual(get_context(self.db,pid)["how_known"], "Wehkamp")
        raw = self.db.execute(
            "SELECT company FROM employment_history WHERE id=?", (original["id"],)
        ).fetchone()
        self.assertEqual(raw["company"], "Wehkamp")
        sync_people(self.db)
        self.assertEqual(get_context(self.db,pid)["how_known"], "Wehkamp")

    def test_attach_to_person_preserves_manual_notes_and_id(self):
        pid = create_person(self.db, "Alex Test")
        save_context(self.db,pid,how_known="Collega")
        save_job(self.db,pid,"Wehkamp","Product owner","2010-01-01")
        original_social = account_person(self.db, "linkedin", "https://linkedin.com/in/alex")
        merge_people(self.db,pid,original_social)
        self.assertEqual(account_person(self.db,"linkedin","https://linkedin.com/in/alex"),pid)
        self.assertEqual(display_name(self.db,pid),"Alex Test")
        self.assertEqual(get_context(self.db,pid)["how_known"],"Collega")
        self.assertEqual(len(employment(self.db,pid)),2)
        sync_people(self.db)
        self.assertEqual(account_person(self.db,"linkedin","https://linkedin.com/in/alex"),pid)


if __name__ == "__main__":
    unittest.main()
