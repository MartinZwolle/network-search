"""One profile page for LinkedIn and Instagram, with user-controlled account links.

A LinkedIn contact is the canonical profile when available. An unlinked
Instagram account has its own profile until it is linked. Existing
profile_links records are retained; we never merge by name automatically.
"""
from html import escape
from urllib.parse import quote
from fastapi import HTTPException
from app.person_ids import account_person, details as person_details
from app.context import get as get_context, person_tags
from app.manual import display_name as farley_display_name, employment as farley_employment

CSS = """
:root{--ink:#252b30;--muted:#647078;--accent:#087f80;--edge:#dde6e5;--paper:#fff;--bg:#f5f7f6}
*{box-sizing:border-box}body{font:16px/1.65 system-ui,-apple-system,Segoe UI,sans-serif;max-width:1050px;margin:0 auto;padding:38px 24px 90px;background:var(--bg);color:var(--ink)}
h1,h2{line-height:1.25;letter-spacing:-.035em}h1{font-size:clamp(2.3rem,5vw,4rem);margin:.35em 0 .15em}
a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:3px}
header{border-bottom:4px solid var(--accent);padding-bottom:23px;margin-bottom:30px}\n.profile-brand{display:flex;align-items:center;gap:14px}.profile-brand img{width:56px;height:56px;border-radius:12px}
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
    """One search result per confirmed person ID."""
    output, seen = [], set()
    for contact in linkedin_results:
        pid = account_person(db, "linkedin", contact["url"])
        if pid is not None and pid not in seen:
            output.append(("linkedin", contact))
            seen.add(pid)
    for account in instagram_results:
        pid = account_person(db, "instagram", account["username"])
        if pid is None or pid in seen:
            continue
        info = person_details(db, pid)
        linked = next((a["account_key"] for a in info[1] if a["platform"] == "linkedin"), None)
        if linked:
            row = db.execute(
                """SELECT c.*, (SELECT count(*) FROM contact_messages cm
                   WHERE cm.contact_url=c.url) AS message_count
                   FROM contacts c WHERE c.url=?""", (linked,)
            ).fetchone()
            if row:
                output.append(("linkedin", row))
                seen.add(pid)
                continue
        output.append(("instagram", account))
        seen.add(pid)
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
    if not linkedin_url and not instagram_username and person_id is None:
        raise HTTPException(400, "Selecteer een persoon")
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
    if contact is None and instagram_username:
        standalone = db.execute(
            "SELECT * FROM instagram_accounts WHERE username=?", (username,)
        ).fetchone()
        if standalone is None:
            raise HTTPException(404, "Instagram-account niet gevonden")
    accounts = db.execute(
        """SELECT a.* FROM profile_links l JOIN instagram_accounts a
           ON a.username=l.instagram_username
           WHERE l.linkedin_url=? ORDER BY a.username""", (linkedin_url,)
    ).fetchall() if contact is not None else ([standalone] if standalone is not None else [])

    if person_id is None:
        person_id = (account_person(db, "linkedin", linkedin_url) if contact is not None
                     else account_person(db, "instagram", standalone["username"]))
    name = (farley_display_name(db, person_id) if person_id is not None else
            " ".join(filter(None, [contact["first_name"], contact["last_name"]])) if contact is not None else
            "@" + standalone["username"])
    nav = ('<a href="/">⌂ Home</a> · <a href="/activity">Netwerkactiviteit</a>'
           ' · <a href="/matches">Mogelijke koppelingen</a> · <a href="/tags">Netwerktags</a>')
    html = ('<!doctype html><html lang="nl"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Persoon · Farley File</title><link rel="icon" type="image/svg+xml" href="/static/farley-logo.svg"><style>' + CSS + '</style>'
            '<header><div class="profile-brand"><a href="/"><img src="/static/farley-logo.svg" alt="Farley File home" width="56" height="56"></a><span class="brand">Elegant Chaos / Labs</span></div>'
            f'<h1>{escape(name)}</h1><nav>{nav}</nav>'
            '<p class="muted">Eén persoon, meerdere sociale accounts.</p></header>')
    if person_id is not None:
        context = get_context(db, person_id)
        net_tags = person_tags(db, person_id)
        html += '<section><h2>Farley File · persoonlijk</h2>'
        for label, key in (
            ("Hoe ken ik deze persoon?", "how_known"),
            ("Achtergrond", "background"),
            ("Interesses", "interests"),
            ("Wat wil ik onthouden?", "remember"),
        ):
            value = context[key]
            if value:
                html += (f'<article><strong>{escape(label)}</strong><br>'
                         f'<span style="white-space:pre-wrap">{escape(value)}</span></article>')
        if net_tags:
            html += '<article><strong>Netwerken en groepen</strong><br>'
            for tag in net_tags:
                html += (f'<a href="/tags/{quote(tag,safe="")}" '
                         f'style="display:inline-block;margin:5px 8px 5px 0;padding:3px 9px;'
                         f'background:#e4f3f0;border-radius:4px">#{escape(tag)}</a>')
            html += '</article>'
        if not any(context.values()) and not net_tags:
            html += '<p class="muted">Je hebt nog niets over deze persoon vastgelegd.</p>'
        html += ('<details style="margin-top:18px"><summary style="color:#087f80;'
                 'cursor:pointer;font-weight:700">✎ Persoonsgegevens bewerken</summary>'
                 f'<form action="/person/{person_id}/context" method="post">')
        fields = (
            ("how_known", "Hoe ken ik deze persoon?", "Bijvoorbeeld: oud-collega bij Wehkamp", 2, 1000),
            ("background", "Achtergrond", "Bijvoorbeeld: heeft een eigen brouwerij", 4, 4000),
            ("interests", "Interesses (komma's)", "Bierbrouwen, muziek, fietsen", 2, 2000),
            ("remember", "Wat wil ik onthouden?", "Vraag de volgende keer hoe het met ... gaat", 4, 4000),
        )
        for key, label, placeholder, rows, maximum in fields:
            html += (f'<label for="ctx_{key}" style="display:block;margin-top:12px">'
                     f'<strong>{escape(label)}</strong></label>'
                     f'<textarea id="ctx_{key}" name="{key}" rows="{rows}" maxlength="{maximum}" '
                     f'placeholder="{escape(placeholder,quote=True)}" '
                     f'style="width:100%;max-width:720px;padding:10px;font:inherit;'
                     f'border:1px solid #bdcbcb;border-radius:4px">'
                     f'{escape(context[key])}</textarea>')
        html += (f'<label for="ctx_tags" style="display:block;margin-top:12px">'
                 '<strong>Netwerktags</strong></label>'
                 '<p class="muted">Gebruik bijvoorbeeld #wehkamp, #bierproefclub. '
                 'Eén persoon kan bij meerdere groepen horen.</p>'
                 '<input id="ctx_tags" type="text" name="network_tags" '
                 f'value="{escape(", ".join("#"+t for t in net_tags),quote=True)}" '
                 'placeholder="#wehkamp, #bierproefclub" '
                 'style="width:100%;max-width:720px;padding:10px;font:inherit;'
                 'border:1px solid #bdcbcb;border-radius:4px"><br>'
                 '<button type="submit" style="margin-top:16px">Opslaan</button>'
                 '</form></details></section>')
    if person_id is not None:
        html += '<section><h2>Functies en werkhistorie</h2>'
        html += ('<p class="muted">Geïmporteerde LinkedIn-functies blijven als bron bewaard. '
                 'Handmatige correcties en aanvullende functies worden nooit overschreven '
                 'door een nieuwe export.</p>')
        jobs = farley_employment(db, person_id)
        for job in jobs:
            source = "LinkedIn-observatie" if job["kind"] == "import" else "Handmatig toegevoegd"
            label = escape(job["title"] or "Functie onbekend")
            company = escape(job["company"] or "Werkgever onbekend")
            html += (f'<article><strong>{label}</strong> · {company}<br>'
                     f'<small>{source}'
                     f'{" · voor het eerst gezien op " + escape(job["first_seen"][:10]) if job["first_seen"] else ""}'
                     f'{" · vanaf " + escape(job["started"]) if job["started"] else ""}'
                     f'{" t/m " + escape(job["ended"]) if job["ended"] else ""}</small>')
            if job["note"]:
                html += f'<p>{escape(job["note"])}</p>'
            html += (f'<details><summary style="cursor:pointer;color:#087f80">✎ Functie bewerken</summary>'
                     f'<form method="post" action="/person/{person_id}/job">'
                     f'<input type="hidden" name="kind" value="{job["kind"]}">'
                     f'<input type="hidden" name="job_id" value="{job["id"]}">'
                     f'<label>Functie<br><input type="text" name="title" maxlength="200" value="{escape(job["title"],quote=True)}"></label><br>'
                     f'<label>Werkgever<br><input type="text" name="company" maxlength="200" value="{escape(job["company"],quote=True)}"></label><br>'
                     f'<label>Startdatum<br><input type="date" name="started" value="{escape(job["started"],quote=True)}"></label><br>'
                     f'<label>Einddatum<br><input type="date" name="ended" value="{escape(job["ended"],quote=True)}"></label><br>'
                     f'<label>Toelichting<br><textarea name="note" maxlength="2000">{escape(job["note"])}</textarea></label><br>'
                     '<button type="submit">Wijzigingen opslaan</button></form></details>')
            if job["kind"] == "manual":
                html += (f'<form method="post" action="/person/{person_id}/job/delete">'
                         f'<input type="hidden" name="job_id" value="{job["id"]}">'
                         '<button type="submit" style="background:#69767a">Functie verwijderen</button></form>')
            html += '</article>'
        html += (f'<details style="margin-top:12px"><summary style="cursor:pointer;color:#087f80;font-weight:700">'
                 '+ Functie toevoegen</summary>'
                 f'<form method="post" action="/person/{person_id}/job">'
                 '<input type="hidden" name="kind" value="new">'
                 '<label>Functie<br><input name="title" type="text" maxlength="200"></label><br>'
                 '<label>Werkgever<br><input name="company" type="text" maxlength="200"></label><br>'
                 '<label>Startdatum<br><input name="started" type="date"></label><br>'
                 '<label>Einddatum<br><input name="ended" type="date"></label><br>'
                 '<label>Toelichting<br><textarea name="note" maxlength="2000"></textarea></label><br>'
                 '<button type="submit">Functie toevoegen</button></form></details></section>')
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
