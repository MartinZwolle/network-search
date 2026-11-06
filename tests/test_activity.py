"""Run: python -m unittest discover -s tests -v"""
import sqlite3
import unittest
from app.activity import parse_date, year_counts, contact_timeline, network_activity


class ActivityTests(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(parse_date("2024-04-10 09:03:00 UTC").year, 2024)
        self.assertEqual(parse_date("2025-03-01T14:00:00Z").year, 2025)
        self.assertIsNone(parse_date(""))
        self.assertIsNone(parse_date("not a date"))

    def test_year_counts(self):
        rows = [{"date": "2021-01-01"}, {"date": "2021-06-12"},
                {"date": "2022-01-01"}, {"date": "unknown"}]
        self.assertEqual(year_counts(rows), ([(2022, 1), (2021, 2)], 1))
        self.assertIn("2021", contact_timeline(rows, []))

    def test_network_counts_group_messages_once(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript("""
        CREATE TABLE contacts(url TEXT, first_name TEXT, last_name TEXT);
        CREATE TABLE messages(message_key TEXT, date TEXT, sender_url TEXT);
        CREATE TABLE contact_messages(contact_url TEXT, message_key TEXT);
        INSERT INTO contacts VALUES ('a','Alex','Example'),('b','Bea','Example');
        INSERT INTO messages VALUES ('m1','2020-01-01','a');
        INSERT INTO contact_messages VALUES ('a','m1'),('b','m1');
        """)
        html = network_activity(db)
        self.assertIn("2020", html)
        self.assertIn(">1</strong>", html)  # One message, even with two contacts.


if __name__ == "__main__":
    unittest.main()
