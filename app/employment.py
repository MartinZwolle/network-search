"""Track observed LinkedIn employment changes, without guessing employment dates.

Snapshots represent *when our importer observed* a company/position, not
when someone actually started or left a job.
"""
from datetime import datetime, timezone


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalized(value):
    return " ".join((value or "").split()).casefold()


def migrate(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS employment_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      contact_url TEXT NOT NULL,
      company TEXT NOT NULL DEFAULT '',
      position TEXT NOT NULL DEFAULT '',
      first_seen_at TEXT NOT NULL,
      last_seen_at TEXT NOT NULL,
      superseded_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_employment_history_contact
      ON employment_history(contact_url, id DESC);
    """)
    timestamp = now_utc()
    # On upgrade, the existing contacts form the baseline. An old
    # LinkedIn export contains no actual job-start date.
    db.execute("""
      INSERT INTO employment_history
        (contact_url, company, position, first_seen_at, last_seen_at)
      SELECT url, COALESCE(company, ''), COALESCE(position, ''), ?, ?
      FROM contacts c
      WHERE (TRIM(COALESCE(company,'')) <> '' OR TRIM(COALESCE(position,'')) <> '')
        AND NOT EXISTS (SELECT 1 FROM employment_history h
                        WHERE h.contact_url = c.url)
    """, (timestamp, timestamp))


def observe(db, url, company, position, timestamp):
    """Record a new employment observation, never erasing with blank CSV fields."""
    latest = db.execute("""
      SELECT * FROM employment_history WHERE contact_url=?
      ORDER BY id DESC LIMIT 1
    """, (url,)).fetchone()
    # LinkedIn can omit a field temporarily; do not interpret omission as a job change.
    company = (company or "").strip() or (latest["company"] if latest else "")
    position = (position or "").strip() or (latest["position"] if latest else "")
    if not company and not position:
        return
    if latest and normalized(company) == normalized(latest["company"]) and normalized(position) == normalized(latest["position"]):
        db.execute("UPDATE employment_history SET last_seen_at=? WHERE id=?",
                   (timestamp, latest["id"]))
        return
    if latest:
        db.execute("UPDATE employment_history SET superseded_at=? WHERE id=?",
                   (timestamp, latest["id"]))
    db.execute("""
      INSERT INTO employment_history
      (contact_url, company, position, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?)
    """, (url, company, position, timestamp, timestamp))
