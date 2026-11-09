"""Find imported social accounts for an explicit, user-approved profile link."""
from html import escape
from urllib.parse import quote, urlencode

from app.person_ids import account_person

PLATFORMS=("linkedin","facebook","instagram","twitter")


def find(db,platform,query,limit=25):
    platform=platform if platform in PLATFORMS else "all"
    term=(query or "").strip()[:120]
    if len(term)<2:
        return []
    like="%"+term.casefold().replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%"
    results=[]
    if platform in ("all","linkedin"):
        for r in db.execute("""SELECT a.account_key,
                    TRIM(COALESCE(c.first_name,'')||' '||COALESCE(c.last_name,'')) name
                FROM farley_accounts a JOIN contacts c ON a.platform='linkedin'
                    AND a.account_key=c.url
                WHERE (c.first_name||' '||c.last_name) LIKE ? ESCAPE '\\'
                    OR a.account_key LIKE ? ESCAPE '\\'
                ORDER BY name LIMIT ?""",(like,like,limit)):
            results.append(("linkedin",r["account_key"],r["name"]))
    if platform in ("all","facebook"):
        for r in db.execute("""SELECT a.account_key,f.display_name name
                FROM farley_accounts a JOIN facebook_people f
                    ON a.platform='facebook' AND a.account_key=f.fb_key
                WHERE f.display_name LIKE ? ESCAPE '\\'
                    OR a.account_key LIKE ? ESCAPE '\\'
                ORDER BY f.display_name LIMIT ?""",(like,like,limit)):
            results.append(("facebook",r["account_key"],r["name"]))
    if platform in ("all","instagram"):
        for r in db.execute("""SELECT a.account_key
                FROM farley_accounts a WHERE a.platform='instagram'
                    AND a.account_key LIKE ? ESCAPE '\\'
                ORDER BY a.account_key LIMIT ?""",(like,limit)):
            results.append(("instagram",r["account_key"],"@"+r["account_key"]))
    if platform in ("all","twitter"):
        for r in db.execute("""SELECT DISTINCT a.account_key,
                    COALESCE((SELECT '@'||h.handle FROM twitter_handles h
                       WHERE h.user_id=a.account_key
                       ORDER BY h.last_seen DESC LIMIT 1),
                       'Twitter-ID '||a.account_key) name
                FROM farley_accounts a LEFT JOIN twitter_handles h
                   ON h.user_id=a.account_key
                WHERE a.platform='twitter' AND
                    (h.handle LIKE ? ESCAPE '\\' OR a.account_key LIKE ? ESCAPE '\\')
                ORDER BY name LIMIT ?""",(like,like,limit)):
            results.append(("twitter",r["account_key"],r["name"]))
    return results[:limit]


def render(db,person_id,platform="all",query=""):
    platform=platform if platform in (*PLATFORMS,"all") else "all"
    query=(query or "").strip()[:120]
    html=(f'<details id="accounts-koppelen" {"open" if query else ""}>'
          '<summary style="cursor:pointer;color:#087f80;font-weight:700">'
          '+ Sociaal account koppelen</summary>'
          '<p class="muted">Zoek een bestaand geïmporteerd account. Controleer '
          'het profiel voordat je het bewust aan deze persoon koppelt.</p>'
          f'<form method="get" action="/person/{person_id}#accounts-koppelen">'
          '<label>Platform <select name="account_platform">')
    for p,label in (("all","Alle platforms"),("linkedin","LinkedIn"),
                    ("facebook","Facebook"),("instagram","Instagram"),("twitter","Twitter")):
        html+=f'<option value="{p}"'+(' selected' if p==platform else '')+f'>{label}</option>'
    html+=('</select></label> '
           '<input type="search" name="account_query" minlength="2" maxlength="120" '
           f'value="{escape(query,quote=True)}" placeholder="Naam of gebruikersnaam" required> '
           '<button type="submit">Zoeken</button></form>')
    if query:
        results=find(db,platform,query)
        if not results:
            html+='<p>Geen geïmporteerde accounts gevonden. Probeer een andere zoekterm.</p>'
        for p,key,label in results:
            owner=account_person(db,p,key)
            if owner==person_id:
                continue
            html+=(f'<article><strong>{escape(label)}</strong> · {escape(p.title())} '
                   + (f'· <a href="/person/{owner}">Huidig profiel bekijken</a>' if owner else '')
                   + f'<form method="post" action="/person/{person_id}/attach" '
                   'onsubmit="return confirm(\'Dit account bewust aan deze persoon koppelen?\')">'
                   f'<input type="hidden" name="platform" value="{escape(p,quote=True)}">'
                   f'<input type="hidden" name="account" value="{escape(key,quote=True)}">'
                   '<button type="submit">Koppelen</button></form></article>')
    html+=('<details style="margin-top:14px"><summary>Account-ID direct invoeren</summary>'
           '<p class="muted">Voor een account uit de import waarvan je de exacte '
           'profiel-URL, gebruikersnaam of het historische ID al kent.</p>'
           f'<form method="post" action="/person/{person_id}/attach">'
           '<label>Platform <select name="platform">'
           '<option value="linkedin">LinkedIn</option>'
           '<option value="instagram">Instagram</option>'
           '<option value="facebook">Facebook</option>'
           '<option value="twitter">Twitter</option></select></label><br>'
           '<input type="text" name="account" required maxlength="600" '
           'placeholder="Exacte accountnaam, URL of ID">'
           '<button type="submit">Account koppelen</button></form></details></details>')
    return html
