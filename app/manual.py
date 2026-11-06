"""Hand-entered people and employment facts, kept apart from imported snapshots.

Imported LinkedIn rows remain observations. Any correction to an imported
employment record lives in a separate override, and cannot be overwritten by
re-importing. Manual jobs have optional actual dates.
"""
import re
from datetime import date, datetime, timezone
from app.person_ids import details

def migrate(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS farley_person_names (
        person_id INTEGER PRIMARY KEY REFERENCES farley_people(id),
        display_name TEXT NOT NULL,
        created_manually INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS farley_manual_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER NOT NULL REFERENCES farley_people(id),
        company TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL DEFAULT '',
        started TEXT NOT NULL DEFAULT '',
        ended TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_farley_manual_jobs_person
      ON farley_manual_jobs(person_id);
    CREATE TABLE IF NOT EXISTS farley_job_overrides (
        history_id INTEGER PRIMARY KEY REFERENCES employment_history(id),
        person_id INTEGER NOT NULL REFERENCES farley_people(id),
        company TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL DEFAULT '',
        started TEXT NOT NULL DEFAULT '',
        ended TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_farley_job_overrides_person
      ON farley_job_overrides(person_id);
    """)


def _name(name):
    value = " ".join((name or "").split())
    if len(value) < 2 or len(value) > 160:
        raise ValueError("Naam moet tussen 2 en 160 tekens lang zijn")
    return value


def create_person(db, name):
    value = _name(name)
    pid = db.execute("INSERT INTO farley_people DEFAULT VALUES").lastrowid
    db.execute(
        "INSERT INTO farley_person_names(person_id,display_name,created_manually) VALUES (?,?,1)",
        (pid, value),
    )
    return pid


def rename_person(db, person_id, name):
    info = details(db, person_id)
    if info is None:
        raise ValueError("Persoon niet gevonden")
    value = _name(name)
    db.execute(
        """INSERT INTO farley_person_names(person_id,display_name,created_manually)
           VALUES (?,?,1)
           ON CONFLICT(person_id) DO UPDATE SET display_name=excluded.display_name""",
        (info[0], value),
    )


def display_name(db, person_id):
    info = details(db, person_id)
    if info is None:
        return ""
    row = db.execute(
        "SELECT display_name FROM farley_person_names WHERE person_id=?", (info[0],)
    ).fetchone()
    if row:
        return row["display_name"]
    for account in info[1]:
        if account["platform"] == "linkedin":
            contact = db.execute(
                "SELECT first_name,last_name FROM contacts WHERE url=?", (account["account_key"],)
            ).fetchone()
            if contact:
                return " ".join(filter(None, (contact["first_name"], contact["last_name"])))
    for account in info[1]:
        if account["platform"] == "instagram":
            return "@" + account["account_key"]
    return "Persoon " + str(info[0])


def search_manual(db, query, limit=60):
    term = (query or "").strip().casefold()
    if not term:
        return []
    return db.execute(
        """SELECT person_id, display_name FROM farley_person_names
           WHERE display_name LIKE ? ESCAPE '\\'
           ORDER BY display_name LIMIT ?""",
        ("%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%", limit),
    ).fetchall()


def _date_value(raw):
    value = (raw or "").strip()
    if not value:
        return ""
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Gebruik een geldige datum in formaat JJJJ-MM-DD") from error
    if len(value) != 10:
        raise ValueError("Gebruik JJJJ-MM-DD")
    return value


def _job_fields(company, title, started="", ended="", note=""):
    company = " ".join((company or "").split())
    title = " ".join((title or "").split())
    note = (note or "").strip()
    if not company and not title:
        raise ValueError("Vul een werkgever of functie in")
    if max(len(company), len(title)) > 200 or len(note) > 2000:
        raise ValueError("Functiegegevens zijn te lang")
    started = _date_value(started)
    ended = _date_value(ended)
    if started and ended and ended < started:
        raise ValueError("Einddatum ligt vóór startdatum")
    return company, title, started, ended, note


def save_job(db, person_id, company, title, started="", ended="", note="",
             job_id=None, history_id=None):
    info = details(db, person_id)
    if info is None:
        raise ValueError("Persoon niet gevonden")
    pid = info[0]
    data = _job_fields(company, title, started, ended, note)
    now = datetime.now(timezone.utc).isoformat()
    if job_id is not None and history_id is not None:
        raise ValueError("Kies één functie")
    if job_id is not None:
        row = db.execute(
            "SELECT 1 FROM farley_manual_jobs WHERE id=? AND person_id=?", (job_id, pid)
        ).fetchone()
        if row is None:
            raise ValueError("Handmatige functie niet gevonden")
        db.execute(
            """UPDATE farley_manual_jobs SET company=?, title=?, started=?, ended=?, note=?
               WHERE id=? AND person_id=?""", (*data, job_id, pid),
        )
    elif history_id is not None:
        row = db.execute(
            """SELECT 1 FROM employment_history h
               JOIN farley_accounts a ON a.platform='linkedin' AND a.account_key=h.contact_url
               WHERE h.id=? AND a.person_id=?""", (history_id, pid)
        ).fetchone()
        if row is None:
            raise ValueError("Geïmporteerde functie niet gevonden bij deze persoon")
        db.execute(
            """INSERT INTO farley_job_overrides
               (history_id,person_id,company,title,started,ended,note,updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(history_id) DO UPDATE SET
                  company=excluded.company,title=excluded.title,
                  started=excluded.started,ended=excluded.ended,
                  note=excluded.note,updated_at=excluded.updated_at""",
            (history_id, pid, *data, now),
        )
    else:
        db.execute(
            """INSERT INTO farley_manual_jobs
               (person_id,company,title,started,ended,note,created_at)
               VALUES (?,?,?,?,?,?,?)""", (pid, *data, now),
        )


def delete_manual_job(db, person_id, job_id):
    info = details(db, person_id)
    if info is None:
        raise ValueError("Persoon niet gevonden")
    db.execute(
        "DELETE FROM farley_manual_jobs WHERE id=? AND person_id=?", (job_id, info[0]),
    )


def employment(db, person_id):
    info = details(db, person_id)
    if info is None:
        raise ValueError("Persoon niet gevonden")
    pid, accounts = info
    records = []
    for account in accounts:
        if account["platform"] != "linkedin":
            continue
        for observed in db.execute(
            """SELECT h.*, o.company AS custom_company,o.title AS custom_title,
               o.started AS custom_started,o.ended AS custom_ended,
               o.note AS custom_note
               FROM employment_history h LEFT JOIN farley_job_overrides o
                 ON o.history_id=h.id
               WHERE h.contact_url=? ORDER BY h.id DESC""",
            (account["account_key"],),
        ):
            edited = observed["custom_company"] is not None
            records.append({
                "kind": "import", "id": observed["id"],
                "company": observed["custom_company"] if edited else observed["company"],
                "title": observed["custom_title"] if edited else observed["position"],
                "started": observed["custom_started"] if edited else "",
                "ended": observed["custom_ended"] if edited else "",
                "note": observed["custom_note"] if edited else "",
                "first_seen": observed["first_seen_at"],
                "edited": edited,
            })
    for row in db.execute(
        "SELECT * FROM farley_manual_jobs WHERE person_id=? ORDER BY id DESC", (pid,)
    ):
        records.append({
            "kind": "manual", "id": row["id"],
            "company": row["company"], "title": row["title"],
            "started": row["started"], "ended": row["ended"],
            "note": row["note"], "first_seen": "", "edited": True,
        })
    return records


def transfer_person_data(db, source, dest):
    """Move user-entered fields when a formerly standalone person gets linked."""
    if source == dest:
        return
    existing = db.execute("SELECT 1 FROM farley_person_names WHERE person_id=?", (dest,)).fetchone()
    if existing:
        db.execute("DELETE FROM farley_person_names WHERE person_id=?", (source,))
    else:
        db.execute("UPDATE farley_person_names SET person_id=? WHERE person_id=?", (dest, source))
    db.execute("UPDATE farley_manual_jobs SET person_id=? WHERE person_id=?", (dest, source))
    db.execute("UPDATE farley_job_overrides SET person_id=? WHERE person_id=?", (dest, source))
