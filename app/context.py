"""User-authored Farley File context, separate from imported social data."""
import re
from datetime import datetime, timezone
from app.person_ids import details

FIELDS = ("how_known", "background", "interests", "remember")


def migrate(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS farley_tags (
        person_id INTEGER NOT NULL REFERENCES farley_people(id),
        tag TEXT NOT NULL COLLATE NOCASE,
        PRIMARY KEY(person_id,tag)
    );
    CREATE INDEX IF NOT EXISTS idx_farley_tags_tag ON farley_tags(tag);
    CREATE TABLE IF NOT EXISTS farley_context (
        person_id INTEGER PRIMARY KEY REFERENCES farley_people(id),
        how_known TEXT NOT NULL DEFAULT '',
        background TEXT NOT NULL DEFAULT '',
        interests TEXT NOT NULL DEFAULT '',
        remember TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    );
    """)


def get(db, person_id):
    info = details(db, person_id)
    if info is None:
        raise ValueError("Persoon niet gevonden")
    row = db.execute(
        "SELECT how_known,background,interests,remember,updated_at "
        "FROM farley_context WHERE person_id=?", (info[0],)
    ).fetchone()
    return {key: row[key] if row else "" for key in FIELDS}


def tags(value):
    """Deduplicate tags, preserve user's spelling and order."""
    parts = re.split(r"[,;\n]+", value or "")
    result = []
    seen = set()
    for raw in parts:
        tag = " ".join(raw.strip().split())
        if tag and tag.casefold() not in seen:
            if len(tag) > 60:
                raise ValueError("Een interesse mag maximaal 60 tekens zijn")
            result.append(tag)
            seen.add(tag.casefold())
    if len(result) > 30:
        raise ValueError("Gebruik maximaal 30 interesses")
    return ", ".join(result)


def save(db, person_id, how_known="", background="", interests="", remember="", network_tags=""):
    info = details(db, person_id)
    if info is None:
        raise ValueError("Persoon niet gevonden")
    values = {}
    limits = {"how_known": 1000, "background": 4000, "remember": 4000}
    for key, value in (("how_known", how_known), ("background", background), ("remember", remember)):
        text = (value or "").strip()
        if len(text) > limits[key]:
            raise ValueError(f"Het veld {key} is te lang (maximaal {limits[key]} tekens)")
        values[key] = text
    values["interests"] = tags(interests)
    parsed_tags = parse_network_tags(network_tags)
    timestamp = datetime.now(timezone.utc).isoformat()
    db.execute(
        """INSERT INTO farley_context(person_id,how_known,background,interests,remember,updated_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(person_id) DO UPDATE SET
             how_known=excluded.how_known, background=excluded.background,
             interests=excluded.interests, remember=excluded.remember,
             updated_at=excluded.updated_at""",
        (info[0], values["how_known"], values["background"],
         values["interests"], values["remember"], timestamp),
    )
    db.execute("DELETE FROM farley_tags WHERE person_id=?", (info[0],))
    db.executemany("INSERT INTO farley_tags(person_id,tag) VALUES (?,?)",
                   [(info[0], tag) for tag in parsed_tags])


def parse_network_tags(value):
    """Tags group persons, unlike free-form interests."""
    result = []
    seen = set()
    for raw in re.split(r"[,;\\n]+", value or ""):
        tag = " ".join(raw.strip().lstrip("#").split()).casefold()
        if not tag:
            continue
        if len(tag) > 50 or not re.fullmatch(r"[\\w][\\w -]*", tag, flags=re.UNICODE):
            raise ValueError("Gebruik tags zoals #wehkamp of #bierproefclub (maximaal 50 tekens)")
        if tag not in seen:
            result.append(tag)
            seen.add(tag)
    if len(result) > 50:
        raise ValueError("Maximaal 50 netwerktags per persoon")
    return result


def person_tags(db, person_id):
    return [row["tag"] for row in db.execute(
        "SELECT tag FROM farley_tags WHERE person_id=? ORDER BY tag",
        (person_id,),
    )]


def merge_context(db, source, dest):
    """Keep existing destination text and preserve source text when people merge."""
    if source == dest:
        return
    db.execute(
        "INSERT OR IGNORE INTO farley_tags(person_id,tag) "
        "SELECT ?,tag FROM farley_tags WHERE person_id=?", (dest, source)
    )
    db.execute("DELETE FROM farley_tags WHERE person_id=?", (source,))
    src = db.execute("SELECT * FROM farley_context WHERE person_id=?", (source,)).fetchone()
    if src is None:
        return
    target = db.execute("SELECT * FROM farley_context WHERE person_id=?", (dest,)).fetchone()
    if target is None:
        db.execute("UPDATE farley_context SET person_id=? WHERE person_id=?", (dest, source))
        return
    merged = {}
    for key in ("how_known", "background", "remember"):
        a = (target[key] or "").strip()
        b = (src[key] or "").strip()
        merged[key] = a if not b or b == a else (a + "\n\n" + b).strip()
    merged["interests"] = tags((target["interests"] or "") + "," + (src["interests"] or ""))
    db.execute(
        """UPDATE farley_context SET how_known=?,background=?,interests=?,remember=?,updated_at=?
           WHERE person_id=?""",
        (merged["how_known"], merged["background"], merged["interests"], merged["remember"],
         datetime.now(timezone.utc).isoformat(), dest),
    )
    db.execute("DELETE FROM farley_context WHERE person_id=?", (source,))
