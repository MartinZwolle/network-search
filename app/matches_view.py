"""One explainable proposal list across LinkedIn, Facebook, Instagram and Twitter."""
from html import escape

from app.smart_matches import candidates

PAGE_SIZE=30


def render(db,page=1,linked=False):
    all_candidates=candidates(db,limit=1000)
    total=len(all_candidates)
    pages=max(1,(total+PAGE_SIZE-1)//PAGE_SIZE)
    page=min(max(1,page),pages)
    visible=all_candidates[(page-1)*PAGE_SIZE:page*PAGE_SIZE]
    rejected=db.execute("""SELECT person_low,person_high,rejected_at
        FROM farley_match_rejections ORDER BY rejected_at DESC LIMIT 40""").fetchall()
    html=('<!doctype html><html lang="nl"><meta charset="utf-8">'
          '<meta name="viewport" content="width=device-width,initial-scale=1">'
          '<title>Mogelijke koppelingen · Farley File</title><style>'
          'body{font:16px/1.65 system-ui,sans-serif;max-width:1050px;margin:0 auto;'
          'padding:38px 24px;background:#f5f7f6;color:#252b30}'
          'a{color:#087f80}section{background:white;border:1px solid #dde6e5;'
          'padding:28px;margin:20px 0}article{border-top:1px solid #dde6e5;'
          'padding:16px 0}small{color:#647078}button{background:#087f80;color:white;'
          'border:0;border-radius:4px;padding:9px 12px;font:inherit;cursor:pointer}'
          '.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}'
          '.actions form{margin:0}</style>'
          '<h1>Mogelijke koppelingen</h1>')
    if linked:
        html+='<p><strong>Profielen gekoppeld.</strong></p>'
    html+=(f'<section><h2>{total} mogelijke koppelingen</h2>'
           '<p>Suggesties uit LinkedIn, Facebook, Instagram, Twitter en handmatige profielen. '
           'Het systeem laat zien waarom accounts mogelijk bij dezelfde persoon horen. '
           '<strong>Er wordt nooit automatisch gekoppeld.</strong> '
           'Kijk beide profielen na voordat je ze samenvoegt.</p>'
           '<p>Een bestaand account handmatig koppelen kan op de betreffende '
           '<a href="/">persoonspagina</a>.</p>')
    for item in visible:
        a,b=item["source_id"],item["target_id"]
        reasons="; ".join(item["reasons"])
        html+=(f'<article><strong><a href="/person/{b}">{escape(item["target_name"])}</a></strong>'
               f' <small>({escape(item["target_platforms"])})</small> ↔ '
               f'<strong><a href="/person/{a}">{escape(item["source_name"])}</a></strong>'
               f' <small>({escape(item["source_platforms"])})</small><br>'
               f'<small>Waarom voorgesteld: {escape(reasons)} · aanwijzing {item["score"]}/100</small>'
               '<div class="actions">'
               '<form method="post" action="/smart-match" '
               'onsubmit="return confirm(\'Deze personen bewust samenvoegen? Ongedaan maken is nog niet beschikbaar.\')">'
               f'<input type="hidden" name="person_a" value="{a}">'
               f'<input type="hidden" name="person_b" value="{b}">'
               '<input type="hidden" name="action" value="link">'
               '<input type="hidden" name="confirmed" value="yes">'
               '<button type="submit">Zelfde persoon — koppelen</button></form>'
               '<form method="post" action="/smart-match">'
               f'<input type="hidden" name="person_a" value="{a}">'
               f'<input type="hidden" name="person_b" value="{b}">'
               '<input type="hidden" name="action" value="reject">'
               '<button type="submit" style="background:#69767a">Niet dezelfde persoon</button>'
               '</form></div></article>')
    if not visible:
        html+='<p>Geen nieuwe voorstellen gevonden.</p>'
    html+='</section><p>'
    if page>1:
        html+=f'<a href="/matches?page={page-1}">← Vorige</a> · '
    html+=f'Pagina {page} van {pages}'
    if page<pages:
        html+=f' · <a href="/matches?page={page+1}">Volgende →</a>'
    html+='</p>'
    if rejected:
        html+=(f'<details><summary>Afgewezen voorstellen ({len(rejected)} recentste) — herstellen</summary>'
               '<section><h2>Afwijzingen herstellen</h2>')
        for row in rejected:
            low,high=row["person_low"],row["person_high"]
            html+=(f'<article><a href="/person/{low}">Persoon {low}</a> ↔ '
                   f'<a href="/person/{high}">Persoon {high}</a>'
                   '<form method="post" action="/smart-match/restore">'
                   f'<input type="hidden" name="person_a" value="{low}">'
                   f'<input type="hidden" name="person_b" value="{high}">'
                   '<button type="submit">Afwijzing herstellen</button></form></article>')
        html+='</section></details>'
    return html+'</html>'
