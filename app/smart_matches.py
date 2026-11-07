"""Explainable, user-approved person matching across imported and manual profiles.

Evidence suggests review, never establishes identity. No message bodies are read.
Avoid fuzzy first-name-only matches and never propose two conflicting LinkedIn
or Facebook accounts as a safe merge.
"""
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
import re
import unicodedata

from app.person_ids import resolve


def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS farley_match_rejections (
        person_low INTEGER NOT NULL,
        person_high INTEGER NOT NULL,
        rejected_at TEXT NOT NULL,
        PRIMARY KEY(person_low,person_high)
    )""")


def normalized(text):
    value = unicodedata.normalize("NFKD", (text or "").casefold())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def squeezed(text):
    return normalized(text).replace(" ", "")


def _rows(db):
    """Collect lightweight evidence without touching private conversation content."""
    data = {}
    for row in db.execute("SELECT id FROM farley_people ORDER BY id"):
        pid = row["id"]
        if resolve(db, pid) != pid:
            continue
        data[pid] = {"id": pid, "names": set(), "handles": set(),
                     "employers": set(), "tags": set(), "platforms": set(),
                     "facebook_keys": set(), "linkedin_keys": set()}
    for row in db.execute("SELECT person_id,display_name FROM farley_person_names"):
        record = data.get(resolve(db,row["person_id"]))
        if record:
            record["names"].add(row["display_name"])
    for a in db.execute("SELECT person_id,platform,account_key FROM farley_accounts"):
        pid = resolve(db,a["person_id"])
        rec = data.get(pid)
        if not rec:
            continue
        platform,key = a["platform"],a["account_key"]
        rec["platforms"].add(platform)
        if platform == "linkedin":
            rec["linkedin_keys"].add(key)
        elif platform == "facebook":
            rec["facebook_keys"].add(key)
        elif platform == "instagram":
            rec["handles"].add(squeezed(key))
    for row in db.execute("""SELECT a.person_id,c.first_name,c.last_name,c.company
        FROM farley_accounts a JOIN contacts c
          ON a.platform='linkedin' AND a.account_key=c.url"""):
        rec = data.get(resolve(db,row["person_id"]))
        if rec:
            name = " ".join(x for x in (row["first_name"],row["last_name"]) if x)
            if name.strip():
                rec["names"].add(name.strip())
            if normalized(row["company"]):
                rec["employers"].add(normalized(row["company"]))
    for row in db.execute("""SELECT a.person_id,f.display_name
        FROM farley_accounts a JOIN facebook_people f
          ON a.platform='facebook' AND a.account_key=f.fb_key"""):
        rec = data.get(resolve(db,row["person_id"]))
        if rec:
            rec["names"].add(row["display_name"])
    for row in db.execute("SELECT person_id,tag FROM farley_tags"):
        rec = data.get(resolve(db,row["person_id"]))
        if rec and normalized(row["tag"]):
            rec["tags"].add(normalized(row["tag"]))
    for row in db.execute("SELECT person_id,company FROM farley_manual_jobs"):
        rec = data.get(resolve(db,row["person_id"]))
        if rec and normalized(row["company"]):
            rec["employers"].add(normalized(row["company"]))
    for row in db.execute("""SELECT a.person_id,h.company
        FROM farley_accounts a JOIN employment_history h
          ON a.platform='linkedin' AND a.account_key=h.contact_url"""):
        rec = data.get(resolve(db,row["person_id"]))
        if rec and normalized(row["company"]):
            rec["employers"].add(normalized(row["company"]))
    # A LinkedIn handle is another legitimate alias, but usually a weak signal.
    for rec in data.values():
        for url in rec["linkedin_keys"]:
            slug = url.split("/in/")[-1].split("/")[0].split("?")[0]
            if slug and slug != url:
                rec["handles"].add(squeezed(slug))
    return data


def _best_label(rec):
    named = sorted((n for n in rec["names"] if n and normalized(n)),
                   key=lambda n:(-len(n.split()), -len(n), n))
    if named:
        return named[0]
    return "@" + next(iter(sorted(rec["handles"]))) if rec["handles"] else "Persoon " + str(rec["id"])


def _evidence(a,b):
    names_a={normalized(x) for x in a["names"] if normalized(x)}
    names_b={normalized(x) for x in b["names"] if normalized(x)}
    compact_a={x.replace(" ","") for x in names_a}
    compact_b={x.replace(" ","") for x in names_b}
    reasons=[]
    score=0
    if names_a & names_b:
        reasons.append("Dezelfde volledige naam")
        score=80
    elif compact_a & compact_b:
        reasons.append("Naam komt overeen zonder spaties of leestekens")
        score=75
    else:
        # Minor spelling variations only where there is independent evidence.
        pairs=[(x,y) for x in names_a for y in names_b
               if len(x)>=7 and len(y)>=7 and x.split()[-1]==y.split()[-1]]
        if pairs and max(SequenceMatcher(None,x,y).ratio() for x,y in pairs)>=0.88:
            score=35
            reasons.append("Sterk gelijkende naam")
    name_and_handle=(compact_a & b["handles"]) or (compact_b & a["handles"])
    if name_and_handle:
        reasons.append("Gebruikersnaam lijkt op de volledige naam")
        score=max(score,65)
    employers=a["employers"] & b["employers"]
    if employers and (score>=35 or name_and_handle):
        reasons.append("Werkgever komt overeen: " + sorted(employers)[0][:80])
        score+=20
    tags=a["tags"] & b["tags"]
    if tags and score>=35:
        reasons.append("Gedeeld netwerk: #" + sorted(tags)[0][:50])
        score+=5
    # A common employer or tag alone is never sufficient evidence.
    if score<55:
        return None
    return {"score":min(score,100), "reasons":reasons}


def candidates(db, limit=500):
    """Return explainable pairs, sorted by evidence then name; never merge."""
    profiles=_rows(db)
    by_name=defaultdict(set)
    by_handle=defaultdict(set)
    by_surname=defaultdict(set)
    for pid,rec in profiles.items():
        for raw in rec["names"]:
            n=normalized(raw)
            if not n:
                continue
            by_name[n.replace(" ","")].add(pid)
            if len(n)>=7 and len(n.split())>=2:
                by_surname[n.split()[-1]].add(pid)
        for h in rec["handles"]:
            if len(h)>=6:
                by_handle[h].add(pid)
    pairs=set()
    # Blocking avoids O(n²) across thousands of imported accounts.
    for ids in list(by_name.values())+list(by_handle.values()):
        if len(ids)>40: # suspiciously shared names; do not flood suggestions
            continue
        ordered=sorted(ids)
        for i,one in enumerate(ordered):
            for two in ordered[i+1:]:
                pairs.add((one,two))
    for handle,ids in by_handle.items():
        for pid in by_name.get(handle,()):
            for other in ids:
                if pid!=other:
                    pairs.add(tuple(sorted((pid,other))))
    for ids in by_surname.values():
        if len(ids)>25:
            continue
        ordered=sorted(ids)
        for i,one in enumerate(ordered):
            for two in ordered[i+1:]:
                if profiles[one]["employers"] & profiles[two]["employers"]:
                    pairs.add((one,two))
    rejected={(row["person_low"],row["person_high"]) for row in db.execute(
        "SELECT person_low,person_high FROM farley_match_rejections")}
    rejected_ig={(r["linkedin_url"],r["instagram_username"]) for r in db.execute(
        "SELECT linkedin_url,instagram_username FROM profile_rejections")}
    rejected_fb={(r["facebook_key"],r["target_person_id"]) for r in db.execute(
        "SELECT facebook_key,target_person_id FROM facebook_match_rejections")}
    results=[]
    for low,high in sorted(pairs):
        if (low,high) in rejected:
            continue
        a,b=profiles[low],profiles[high]
        if a["linkedin_keys"] and b["linkedin_keys"]:
            continue  # existing merge code rejects two LinkedIn identities
        if a["facebook_keys"] and b["facebook_keys"]:
            continue  # avoid conflating distinct ambiguous Facebook name-keys
        if (a["linkedin_keys"] and b["handles"] and any((li,ig) in rejected_ig
                for li in a["linkedin_keys"] for ig in _instagram_accounts(db,high))) or (
            b["linkedin_keys"] and a["handles"] and any((li,ig) in rejected_ig
                for li in b["linkedin_keys"] for ig in _instagram_accounts(db,low))
        ):
            continue
        if any((fb,high) in rejected_fb for fb in a["facebook_keys"]) or any(
                (fb,low) in rejected_fb for fb in b["facebook_keys"]):
            continue
        evidence=_evidence(a,b)
        if not evidence:
            continue
        # Prefer the more complete profile, especially LinkedIn, as the survivor.
        priority=lambda rec:(int(bool(rec["linkedin_keys"])),len(rec["platforms"]),-rec["id"])
        dest,source=(a,b) if priority(a)>=priority(b) else (b,a)
        results.append({"source_id":source["id"],"target_id":dest["id"],
                        "source_name":_best_label(source),"target_name":_best_label(dest),
                        "source_platforms":", ".join(sorted(source["platforms"])) or "handmatig",
                        "target_platforms":", ".join(sorted(dest["platforms"])) or "handmatig",
                        **evidence})
    results.sort(key=lambda r:(-r["score"],r["target_name"].casefold(),
                              r["source_name"].casefold()))
    return results[:limit]


def _instagram_accounts(db,pid):
    return [r["account_key"] for r in db.execute(
        "SELECT account_key FROM farley_accounts WHERE platform='instagram' AND person_id=?",
        (pid,))]


def reject(db,person_a,person_b):
    one,two=resolve(db,person_a),resolve(db,person_b)
    if one==two:
        raise ValueError("Profielen zijn al gekoppeld")
    if not db.execute("SELECT 1 FROM farley_people WHERE id=?",(one,)).fetchone() or not db.execute(
            "SELECT 1 FROM farley_people WHERE id=?",(two,)).fetchone():
        raise ValueError("Persoon niet gevonden")
    low,high=sorted((one,two))
    db.execute("INSERT OR IGNORE INTO farley_match_rejections VALUES (?,?,?)",
               (low,high,datetime.now(timezone.utc).isoformat()))
