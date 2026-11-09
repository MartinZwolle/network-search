"""Persistent, person-level decisions for the contacts-to-review list."""
from datetime import datetime, timezone
from app.person_ids import resolve

def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS farley_reviewed (
        person_id INTEGER PRIMARY KEY,
        reviewed_at TEXT NOT NULL
    )""")

def mark(db, person_id, reviewed):
    pid=resolve(db,person_id)
    if not db.execute("SELECT 1 FROM farley_people WHERE id=?", (pid,)).fetchone():
        raise ValueError("Persoon niet gevonden")
    if reviewed:
        db.execute("""INSERT INTO farley_reviewed(person_id,reviewed_at)
            VALUES(?,?) ON CONFLICT(person_id) DO UPDATE SET
            reviewed_at=excluded.reviewed_at""",
            (pid,datetime.now(timezone.utc).isoformat(timespec="seconds")))
    else:
        # A completed old identity may now redirect to this merged person.
        # Clearing it must clear every historical alias as well.
        for row in db.execute("SELECT person_id FROM farley_reviewed").fetchall():
            if resolve(db,row["person_id"]) == pid:
                db.execute("DELETE FROM farley_reviewed WHERE person_id=?",
                           (row["person_id"],))

def reviewed(db):
    # Resolve after merges; old completed person remains completed.
    return {resolve(db,row["person_id"]):row["reviewed_at"]
            for row in db.execute("SELECT person_id,reviewed_at FROM farley_reviewed")}
