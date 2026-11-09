import sqlite3
import unittest

from app.identities import migrate as migrate_identities, link
from app.people import merged_contacts, profile, profile_url
from app.context import migrate as migrate_context
from app.manual import migrate as migrate_manual
from app.person_ids import migrate as migrate_people, sync as sync_people, details as person_details, account_person, add_note


class PeopleTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE contacts(
                url TEXT PRIMARY KEY, first_name TEXT, last_name TEXT,
                company TEXT, position TEXT
            );
            CREATE TABLE instagram_accounts(
                username TEXT PRIMARY KEY, follows INTEGER, follower INTEGER
            );
            CREATE TABLE contact_messages(contact_url TEXT, message_key TEXT);
            CREATE TABLE messages(
                message_key TEXT, sender_url TEXT, date TEXT,
                sender TEXT, subject TEXT, content TEXT, conversation_id TEXT
            );
            CREATE TABLE employment_history(
                contact_url TEXT, company TEXT, position TEXT,
                first_seen_at TEXT, superseded_at TEXT, id INTEGER PRIMARY KEY
            );
            INSERT INTO contacts VALUES(
                'https://linkedin.com/in/ilse', 'Ilse', 'Wintermans', 'School', 'Docent'
            );
            INSERT INTO instagram_accounts VALUES('ilsewintermans', 1, 1);
        """)
        migrate_identities(self.db)
        migrate_people(self.db)
        migrate_context(self.db)
        migrate_manual(self.db)
        sync_people(self.db)

    def linkedin_search_rows(self):
        return self.db.execute(
            "SELECT c.*, 0 AS message_count FROM contacts c"
        ).fetchall()

    def instagram_search_rows(self):
        return self.db.execute("SELECT * FROM instagram_accounts").fetchall()

    def test_two_unlinked_profiles(self):
        results = merged_contacts(
            self.db, self.linkedin_search_rows(), self.instagram_search_rows()
        )
        self.assertEqual(len(results), 2)
        self.assertIn("linkedin_url=", profile_url(linkedin_url="https://linkedin.com/in/ilse"))
        self.assertIn("instagram_username=", profile_url(instagram_username="ilsewintermans"))

    def test_persistent_id_and_obsidian_notes(self):
        pid = account_person(self.db, "instagram", "ilsewintermans")
        add_note(self.db, pid, "Gesprek", "obsidian://open?vault=Notes&file=Ilse")
        link(self.db, "https://linkedin.com/in/ilse", "ilsewintermans")
        linked_pid = account_person(self.db, "linkedin", "https://linkedin.com/in/ilse")
        self.assertEqual(person_details(self.db, pid)[0], linked_pid)
        note = self.db.execute("SELECT person_id FROM farley_notes").fetchone()
        self.assertEqual(note["person_id"], linked_pid)

    def test_linked_profiles_are_single_person(self):
        link(self.db, "https://linkedin.com/in/ilse", "ilsewintermans")
        results = merged_contacts(
            self.db, self.linkedin_search_rows(), self.instagram_search_rows()
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], "linkedin")
        # Instagram-only search also returns the same canonical person.
        results = merged_contacts(self.db, [], self.instagram_search_rows())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1]["first_name"], "Ilse")
        by_instagram = profile(
            self.db, instagram_username="ilsewintermans",
            footer=lambda: "", profile_key=lambda _: "",
        )
        by_linkedin = profile(
            self.db, linkedin_url="https://linkedin.com/in/ilse",
            footer=lambda: "", profile_key=lambda _: "",
        )
        self.assertEqual(by_instagram, by_linkedin)
        self.assertIn("Sociaal account koppelen", by_instagram)

    def test_instagram_only_profile_can_search_linkedin(self):
        html = profile(
            self.db, instagram_username="ilsewintermans", find="Ilse",
            footer=lambda: "", profile_key=lambda _: "",
        )
        self.assertIn("Sociaal account koppelen", html)
        self.assertIn("Ilse Wintermans", html)


if __name__ == "__main__":
    unittest.main()
