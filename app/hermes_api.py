"""Read-only, key-authenticated endpoints for the Hermes agent.

No API key is ever accepted in a URL or returned in a response.
"""
import hmac
import os
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException

from app.context import get as get_context, person_tags
from app.manual import display_name, employment
from app.person_ids import details

router = APIRouter(prefix="/api/v1", tags=["Hermes (read-only)"])


def authorize(authorization: str | None, x_api_key: str | None):
    """Fail closed if the secret file is not mounted or has no valid key."""
    path = Path(os.getenv("FARLEY_API_KEY_FILE", "/run/secrets/farley_api_key"))
    try:
        expected = path.read_text(encoding="utf-8").strip()
    except OSError:
        raise HTTPException(503, "API niet geconfigureerd") from None
    if len(expected) < 32:
        raise HTTPException(503, "API niet geconfigureerd")
    supplied = x_api_key or ""
    if authorization:
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "API-key vereist", headers={"WWW-Authenticate": "Bearer"})
        if supplied:
            raise HTTPException(401, "Gebruik één authenticatiemethode")
        supplied = authorization[7:]
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(401, "Ongeldige API-key", headers={"WWW-Authenticate": "Bearer"})


def _get_db():
    # Late import avoids a circular dependency with app.main.
    from app.main import connect
    return connect()


def _person(db, pid):
    info = details(db, pid)
    if info is None:
        raise HTTPException(404, "Persoon niet gevonden")
    resolved, accounts = info
    return resolved, accounts


@router.get("/people")
def search_people(q: str = "", limit: int = 20,
                  authorization: str | None = Header(default=None),
                  x_api_key: str | None = Header(default=None)):
    authorize(authorization, x_api_key)
    query = q.strip()
    if not 2 <= len(query) <= 100:
        raise HTTPException(422, "Zoekterm moet 2 tot 100 tekens bevatten")
    limit = max(1, min(limit, 30))
    term = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    # Search only known imported identities and manually entered records;
    # never infer two people are the same from a matching name.
    sql = """
    SELECT person_id FROM farley_person_names
      WHERE display_name LIKE ? ESCAPE '\\'
    UNION
    SELECT a.person_id FROM farley_accounts a
      JOIN contacts c ON a.platform='linkedin' AND a.account_key=c.url
      WHERE (c.first_name || ' ' || c.last_name) LIKE ? ESCAPE '\\'
         OR c.company LIKE ? ESCAPE '\\' OR c.position LIKE ? ESCAPE '\\'
    UNION
    SELECT a.person_id FROM farley_accounts a
      JOIN facebook_people f ON a.platform='facebook' AND a.account_key=f.fb_key
      WHERE f.display_name LIKE ? ESCAPE '\\'
    UNION
    SELECT a.person_id FROM farley_accounts a
      WHERE a.platform='instagram' AND a.account_key LIKE ? ESCAPE '\\'
    UNION
    SELECT a.person_id FROM farley_accounts a
      JOIN twitter_handles h ON a.platform='twitter' AND a.account_key=h.user_id
      WHERE h.handle LIKE ? ESCAPE '\\'
    LIMIT 200
    """
    with _get_db() as db:
        ids = [row[0] for row in db.execute(sql, (term,) * 7)]
        seen = set()
        people = []
        for pid in ids:
            resolved, accounts = _person(db, pid)
            if resolved in seen:
                continue
            seen.add(resolved)
            people.append({
                "id": resolved,
                "name": display_name(db, resolved),
                "platforms": sorted({a["platform"] for a in accounts}),
                "profile_url": f"/person/{resolved}",
            })
        people.sort(key=lambda item: (item["name"].casefold(), item["id"]))
        return {"query": query, "results": people[:limit], "count": len(people[:limit])}


@router.get("/people/{person_id}")
def get_person(person_id: int,
               authorization: str | None = Header(default=None),
               x_api_key: str | None = Header(default=None)):
    authorize(authorization, x_api_key)
    with _get_db() as db:
        pid, accounts = _person(db, person_id)
        notes = db.execute(
            "SELECT title,target FROM farley_notes WHERE person_id=? ORDER BY id", (pid,)
        ).fetchall()
        return {
            "id": pid,
            "name": display_name(db, pid),
            "profile_url": f"/person/{pid}",
            "accounts": [{"platform": a["platform"], "account_key": a["account_key"]}
                         for a in accounts],
            "context": get_context(db, pid),
            "tags": person_tags(db, pid),
            "employment": employment(db, pid),
            "obsidian_notes": [{"title": row["title"], "url": row["target"]} for row in notes],
        }
