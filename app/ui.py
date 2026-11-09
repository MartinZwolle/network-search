"""One consistent application shell for legacy and new Farley File views.

Decorates only rendered HTML; never modifies imported records or form contents.
"""
import re
from html import escape

NAV = (
    ('/', '⌂ Home'),
    ('/activity', 'Netwerkactiviteit'),
    ('/twitter', 'Twitter-archief'),
    ('/matches', 'Mogelijke koppelingen'),
    ('/tags', 'Netwerktags'),
)

STYLE = """
<style id="farley-common-ui">
:root{--ink:#252b30;--muted:#647078;--accent:#087f80;--edge:#dde6e5;--bg:#f5f7f6}
*{box-sizing:border-box}
body{font:16px/1.65 system-ui,-apple-system,Segoe UI,sans-serif!important;
max-width:1050px!important;margin:0 auto!important;padding:38px 24px 90px!important;
background:#f5f7f6!important;color:#252b30!important}
a{color:#087f80}
.farley-shell{border-bottom:4px solid #087f80;padding-bottom:23px;margin-bottom:30px}
.farley-shell .brand{font-size:.83rem;letter-spacing:.17em;text-transform:uppercase;
font-weight:800;color:#087f80}
.farley-shell .masthead{display:flex;gap:14px;align-items:center;margin:14px 0 6px}
.farley-shell .masthead img{width:66px;height:66px;border-radius:12px}
.farley-shell .masthead strong{font-size:clamp(2rem,4vw,3rem);letter-spacing:-.04em;
line-height:1.2}
.farley-shell h1{font-size:clamp(2rem,5vw,3.5rem);margin:14px 0 10px;
letter-spacing:-.035em}
.farley-shell nav{display:flex;gap:4px 11px;flex-wrap:wrap;margin-top:12px}
.farley-shell nav a[aria-current=page]{font-weight:800;text-decoration-thickness:2px}
section{border-radius:5px;box-shadow:0 8px 28px #192f2d08}
button{border-radius:4px}
@media(max-width:550px){.farley-shell nav{gap:6px 12px}
.farley-shell .masthead img{width:54px;height:54px}}
</style>
"""


def _active(path):
    if path.startswith("/activity"):
        return "/activity"
    if path.startswith("/twitter"):
        return "/twitter"
    if path.startswith("/matches"):
        return "/matches"
    if path.startswith("/tags"):
        return "/tags"
    if path.startswith("/person"):
        return None
    return "/"


def _nav(path):
    active = _active(path)
    return '<nav aria-label="Hoofdnavigatie">' + ' · '.join(
        f'<a href="{href}"'+(' aria-current="page"' if href==active else '')+
        f'>{escape(label)}</a>' for href,label in NAV
    ) + '</nav>'


def _title(path, html):
    if path.startswith("/person"):
        match = re.search(r'<header\b[^>]*>.*?<h1[^>]*>(.*?)</h1>', html,
                          re.I | re.S)
        if match:
            return match.group(1)
        return "Persoonsprofiel"
    return {
        "/activity":"Netwerkactiviteit",
        "/matches":"Mogelijke koppelingen",
        "/tags":"Netwerktags",
    }.get(path, "")


def polish(html, path):
    """Reuse home hero and apply identical shell on all other HTML routes."""
    if 'id="farley-common-ui"' in html:
        return html
    nav = _nav(path)
    if path == "/":
        # Home is already the design reference.
        html = re.sub(r'<nav\b[^>]*>.*?</nav>',nav,html,count=1,flags=re.I|re.S)
        return html.replace('</style>','</style>'+STYLE,1)

    title = _title(path,html)
    has_header = bool(re.search(r'<header\\b',html,re.I))
    if not has_header:
        # Move the page heading into the shared masthead instead of
        # showing a second, differently spaced title below it.
        heading = re.search(r'<h1\\b[^>]*>(.*?)</h1>',html,re.I|re.S)
        if heading:
            if not title:
                title=heading.group(1)
            html=html[:heading.start()]+html[heading.end():]
    intro = (
        '<header class="farley-shell">'
        '<span class="brand">Elegant Chaos / Labs</span>'
        '<div class="masthead"><a href="/" aria-label="Farley File home">'
        '<img src="/static/farley-logo.svg" alt="Farley File-logo"></a>'
        '<strong>Farley File</strong></div>'
        + (f'<h1>{title}</h1>' if title else '')
        + nav + '</header>'
    )
    if re.search(r'<header\b',html,re.I):
        html = re.sub(r'<header\b[^>]*>.*?</header>',intro,html,count=1,flags=re.I|re.S)
    else:
        # Most legacy views have no <body> and start after a closing style tag.
        # Insert outside the head in valid browsers.
        if '</style>' in html:
            html = html.replace('</style>','</style>'+STYLE+intro,1)
            return html
        if '</head>' in html:
            html = html.replace('</head>','</head>'+STYLE+intro,1)
            return html
        html = intro+html
    return html.replace('</style>','</style>'+STYLE,1)
