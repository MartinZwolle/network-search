"""One profile page for LinkedIn and Instagram, with user-controlled account links.

A LinkedIn contact is the canonical profile when available. An unlinked
Instagram account has its own profile until it is linked. Existing
profile_links records are retained; we never merge by name automatically.
"""
from html import escape
from urllib.parse import quote
from fastapi import HTTPException
from app.person_ids import account_person, details as person_details

CSS = """
:root{--ink:#252b30;--muted:#647078;--accent:#087f80;--edge:#dde6e5;--paper:#fff;--bg:#f5f7f6}
*{box-sizing:border-box}body{font:16px/1.65 system-ui,-apple-system,Segoe UI,sans-serif;max-width:1050px;margin:0 auto;padding:38px 24px 90px;background:var(--bg);color:var(--ink)}
h1,h2{line-height:1.25;letter-spacing:-.035em}h1{font-size:clamp(2.3rem,5vw,4rem);margin:.35em 0 .15em}
a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:3px}
header{border-bottom:4px solid var(--accent);padding-bottom:23px;margin-bottom:30px}
.brand{font-size:.83rem;text-transform:uppercase;letter-spacing:.17em;font-weight:800;color:var(--accent)}
section{background:var(--paper);padding:clamp(20px,4vw,32px);margin:22px 0;border:1px solid var(--edge);box-shadow:0 8px 28px #192f2d08}
article{padding:14px 0;border-top:1px solid var(--edge)}
small,.muted{color:var(--muted)}input[type=search]{font:inherit;padding:10px;width:min(100%,480px);border:1px solid #bdcbcb;border-radius:4px}
button{font:inherit;background:var(--accent);color:white;padding:9px 14px;border:0;border-radius:4px;cursor:pointer;font-weight:700}
form{margin:12px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}
"""


def profile_url(linkedin_url=None, instagram_username=None):
    if linkedin_url:
        return "/person?linkedin_url=" + quote(linkedin_url, safe="")
    return "/person?instagram_username=" + quote(instagram_username or "", safe="")


def linked_owner(db, username):
    row = db.execute(
        "SELECT linkedin_url FROM profile_links WHERE instagram_username=?", (username,)
    ).fetchone()
    return row["linkedin_url"] if row else None


def merged_contacts(db, linkedin_results, instagram_results):
    """Return one entry per identified person, whatever source matched."""
    output = []
    seen = set()
    for person in linkedin_results:
        url = person["url"]
        if url not in seen:
            seen.add(url)
            output.append(("linkedin", person))
    for account in instagram_results:
        username = account["username"]
        url = linked_owner(db, username)
        if url:
            if url not in seen:
                person = db.execute(
                    """SELECT c.*, (SELECT count(*) FROM contact_messages cm
                        WHERE cm.contact_url=c.url) AS message_count
                        FROM contacts c WHERE c.url=?""", (url,)
                ).fetchone()
                if person:
                    seen.add(url)
                    output.append(("linkedin", person))
                    continue
        else:
            output.append(("instagram", account))
    return output


def profile(db, linkedin_url="", instagram_username="", find="", footer=None,
            contact_timeline=None, profile_key=None, person_id=None):
    if person_id is not None:
        info = person_details(db, person_id)
        if info is None:
            raise HTTPException(404, "Persoon niet gevonden")
        person_id, stored_accounts = info
        linkedin_url = next((r["account_key"] for r in stored_accounts if r["platform"] == "linkedin"), "")
        instagram_username = next((r["account_key"] for r in stored_accounts if r["platform"] == "instagram"), "")
    if not linkedin_url and not instagram_username:
        raise HTTPException(400, "Selecteer een LinkedIn- of Instagram-account")
    if instagram_username:
        username = instagram_username.strip().lstrip("@").casefold()
        owner = linked_owner(db, username)
        if owner:
            linkedin_url = owner
    contact = db.execute(
        "SELECT * FROM contacts WHERE url=?", (linkedin_url,)
    ).fetchone() if linkedin_url else None
    if linkedin_url and contact is None:
        raise HTTPException(404, "LinkedIn-contact niet gevonden")
    standalone = None
    if contact is None:
        standalone = db.execute(
            "SELECT * FROM instagram_accounts WHERE username=?", (username,)
        ).fetchone()
        if standalone is None:
            raise HTTPException(404, "Instagram-account niet gevonden")
    accounts = db.execute(
        """SELECT a.* FROM profile_links l JOIN instagram_accounts a
           ON a.username=l.instagram_username
           WHERE l.linkedin_url=? ORDER BY a.username""", (linkedin_url,)
    ).fetchall() if contact is not None else [standalone]

    if person_id is None:
        person_id = (account_person(db, "linkedin", linkedin_url) if contact is not None
                     else account_person(db, "instagram", standalone["username"]))
    name = (" ".join(filter(None, [contact["first_name"], contact["last_name"]]))
            if contact is not None else "@" + standalone["username"])
    nav = ('<a href="/">⌂ Home</a> · <a href="/activity">Netwerkactiviteit</a>'
           ' · <a href="/matches">Mogelijke koppelingen</a>')
    html = ('<!doctype html><html lang="nl"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Persoon · Network Search</title><style>' + CSS + '</style>'
            '<header><span class="brand">Elegant Chaos / Labs</span>'
            f'<h1>{escape(name)}</h1><nav>{nav}</nav>'
            '<p class="muted">Eén persoon, meerdere sociale accounts.</p></header>')
    html += '<section><h2>Sociale accounts</h2>'
    if contact is not None:
        html += (f'<article><strong>LinkedIn</strong> · '
                 f'<a href="{escape(linkedin_url, quote=True)}" target="_blank" rel="noopener noreferrer">'
                 f'{escape(name)} ↗</a><br><small>{escape(contact["position"] or "")} '
                 f'· {escape(contact["company"] or "")}</small></article>')
    for account in accounts:
        handle = account["username"]
        ig_url = "https://www.instagram.com/" + quote(handle, safe="") + "/"
        html += (f'<article><strong>Instagram</strong> · '
                 f'<a href="{ig_url}" target="_blank" rel="noopener noreferrer">@{escape(handle)} ↗</a>'
                 f'<br><small>{"Jij volgt dit account" if account["follows"] else ""}'
                 f'{" · " if account["follows"] and account["follower"] else ""}'
                 f'{"Volgt jou" if account["follower"] else ""}</small>')
        if contact is not None:
            html += (f'<form method="post" action="/profile-link">'
                     f'<input type="hidden" name="linkedin_url" value="{escape(linkedin_url, quote=True)}">'
                     f'<input type="hidden" name="instagram_username" value="{escape(handle, quote=True)}">'
                     '<input type="hidden" name="action" value="unlink">'
                     '<input type="hidden" name="source" value="person">'
                     '<button type="submit" style="background:#69767a">Ontkoppelen</button></form>')
        html += '</article>'
    html += '</section>'
    if person_id is not None:
        html += (f'<section><h2>Obsidian · gespreksverslagen</h2>'
                 '<p class="muted">Schrijf je gespreksverslagen in Obsidian en verwijs '
                 'vanuit deze persoonspagina naar de notities. De inhoud wordt hier niet gekopieerd.</p>'
                 f'<button type="button" id="copy-person-link" data-id="{person_id}" '
                 f'data-name="{escape(name, quote=True)}">📋 Kopieer Markdown-link voor Obsidian</button>'
                 '<span id="copy-status" role="status" style="margin-left:12px"></span>'
                 '<script>document.getElementById("copy-person-link").addEventListener("click",async function(){'
                 'const link=window.location.origin+"/person/"+this.dataset.id;'
                 'const label="[👤 "+this.dataset.name+"]("+link+")";'
                 'try{await navigator.clipboard.writeText(label);'
                 'document.getElementById("copy-status").textContent="Gekopieerd!";}'
                 'catch(e){window.prompt("Kopieer deze Markdown-link:",label);}'
                 '});</script>')
        notes = db.execute(
            "SELECT id,title,target FROM farley_notes WHERE person_id=? ORDER BY id DESC",
            (person_id,)
        ).fetchall()
        for note in notes:
            html += (f'<article><a href="{escape(note["target"], quote=True)}">'
                     f'{escape(note["title"])}</a>'
                     '<form method="post" action="/obsidian-note/delete">'
                     f'<input type="hidden" name="person_id" value="{person_id}">'
                     f'<input type="hidden" name="note_id" value="{note["id"]}">'
                     '<button type="submit" style="background:#69767a">Verwijder verwijzing</button>'
                     '</form></article>')
        html += (f'<form method="post" action="/obsidian-note/add">'
                 f'<input type="hidden" name="person_id" value="{person_id}">'
                 '<label for="note_title">Titel van de notitie</label><br>'
                 '<input id="note_title" type="text" name="title" maxlength="160" required '
                 'style="width:min(100%,480px);padding:10px"><br>'
                 '<label for="note_target">Obsidian-link (obsidian://...)</label><br>'
                 '<input id="note_target" type="text" name="target" maxlength="2048" required '
                 'placeholder="obsidian://open?vault=..." '
                 'style="width:min(100%,480px);padding:10px"><br>'
                 '<button type="submit">Notitielink toevoegen</button></form></section>')

    # The search is on the person's profile and can be started from EITHER source.
    html += ('<section><h2>Een account aan deze persoon koppelen</h2>'
             '<p class="muted">Zoek een account op het andere platform, controleer het profiel, '
             'en bevestig zelf. We koppelen nooit automatisch op basis van een naam.</p>'
             '<form method="get" action="/person">')
    if contact is not None:
        html += f'<input type="hidden" name="linkedin_url" value="{escape(linkedin_url, quote=True)}">'
        label = "Zoek een Instagram-gebruikersnaam"
    else:
        html += f'<input type="hidden" name="instagram_username" value="{escape(standalone["username"], quote=True)}">'
        label = "Zoek een LinkedIn-contact op naam"
    html += (f'<label for="find">{label}</label><br>'
             f'<input id="find" name="find" type="search" value="{escape(find, quote=True)}" '
             'placeholder="Typ minstens 2 tekens" required minlength="2"> '
             '<button type="submit">Zoeken</button></form>')
    term = find.strip().casefold()
    if len(term) >= 2:
        like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        if contact is not None:
            options = db.execute(
                """SELECT a.* FROM instagram_accounts a WHERE a.username LIKE ? ESCAPE '\\'
                   AND NOT EXISTS (SELECT 1 FROM profile_links l WHERE l.instagram_username=a.username)
                   ORDER BY a.username LIMIT 30""", (like,)
            ).fetchall()
            for option in options:
                handle = option["username"]
                ig_url = "https://www.instagram.com/" + quote(handle, safe="") + "/"
                html += (f'<article><a href="{ig_url}" target="_blank" rel="noopener noreferrer">'
                         f'@{escape(handle)} ↗</a>'
                         '<form action="/profile-link" method="post">'
                         f'<input type="hidden" name="linkedin_url" value="{escape(linkedin_url, quote=True)}">'
                         f'<input type="hidden" name="instagram_username" value="{escape(handle, quote=True)}">'
                         '<input type="hidden" name="source" value="person">'
                         '<button type="submit">Aan deze persoon koppelen</button></form></article>')
        else:
            options = db.execute(
                """SELECT * FROM contacts
                   WHERE (first_name || ' ' || last_name) LIKE ? ESCAPE '\\'
                   ORDER BY last_name, first_name LIMIT 30""", (like,)
            ).fetchall()
            for option in options:
                url = option["url"]
                person_name = " ".join(filter(None, [option["first_name"], option["last_name"]]))
                html += (f'<article><a href="{escape(url, quote=True)}" '
                         f'target="_blank" rel="noopener noreferrer">{escape(person_name)} ↗</a>'
                         f' <small>{escape(option["company"] or "")}</small>'
                         '<form action="/profile-link" method="post">'
                         f'<input type="hidden" name="linkedin_url" value="{escape(url, quote=True)}">'
                         f'<input type="hidden" name="instagram_username" value="{escape(standalone["username"], quote=True)}">'
                         '<input type="hidden" name="source" value="person">'
                         '<button type="submit">Aan deze persoon koppelen</button></form></article>')
        if not options:
            html += '<p>Geen beschikbare accounts gevonden. Probeer een andere zoekterm.</p>'
    html += '</section>'

    if contact is not None:
        history = db.execute(
            """SELECT m.* FROM contact_messages cm JOIN messages m
               ON m.message_key=cm.message_key WHERE cm.contact_url=?
               ORDER BY m.date DESC""", (linkedin_url,)
        ).fetchall()
        jobs = db.execute(
            """SELECT company, position, first_seen_at, superseded_at
               FROM employment_history WHERE contact_url=? ORDER BY id DESC""",
            (linkedin_url,)
        ).fetchall()
        received = sum(profile_key(m["sender_url"]) == profile_key(linkedin_url) for m in history)
        last = history[0]["date"] if history else "Geen berichten gevonden"
        html += (f'<section><h2>LinkedIn-geschiedenis</h2><p>{len(history)} berichten '
                 f'· {received} ontvangen · {len(history)-received} overige</p>'
                 f'<p>Laatste LinkedIn-bericht: {escape(last)}</p></section>')
        if contact_timeline:
            html += contact_timeline(history, jobs)
        html += '<section><h2>Werkhistorie (waargenomen)</h2>'
        for job in jobs:
            html += (f'<article><strong>{escape(job["position"] or "Functie onbekend")}</strong>'
                     f' · {escape(job["company"] or "Werkgever onbekend")} '
                     f'<small>· gezien vanaf {escape((job["first_seen_at"] or "")[:10])}</small></article>')
        if not jobs:
            html += '<p>Geen werkhistorie gevonden.</p>'
        html += '</section><section><h2>LinkedIn-berichten</h2>'
        for msg in history:
            html += (f'<article><small>{escape(msg["date"] or "")} · '
                     f'{escape(msg["sender"] or "")}</small>'
                     f'<h3>{escape(msg["subject"] or "(geen onderwerp)")}</h3>'
                     f'<pre>{escape(msg["content"] or "")}</pre></article>')
        html += '</section>'
    html += ('<section><h2>Instagram-berichten</h2>'
             '<p class="muted">Instagram-inboxberichten zijn nog niet betrouwbaar aan '
             'gebruikersnamen gekoppeld. Ze blijven doorzoekbaar op de startpagina; '
             'we tonen ze hier pas wanneer de afzender correct te herleiden is.</p></section>')
    return html + (footer() if footer else "") + "</html>"
