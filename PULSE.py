from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from html import escape
import sqlite3, time, secrets, re, html, threading, webbrowser
import os

DB = "pulse.db"

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8080))

FEEDS = [
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", "World"),
    ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml", "Business"),
    ("BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml", "Technology"),
]

def db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c

def initialize():

def initialize():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS posts(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL, body TEXT NOT NULL,
          author TEXT NOT NULL, category TEXT NOT NULL,
          url TEXT UNIQUE, created REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS comments(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          post_id INTEGER NOT NULL, author TEXT NOT NULL,
          body TEXT NOT NULL, created REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS votes(
          post_id INTEGER NOT NULL, voter TEXT NOT NULL,
          PRIMARY KEY(post_id, voter)
        );

        CREATE TABLE IF NOT EXISTS users(
          username TEXT PRIMARY KEY
        );
        """)

def clean(s, limit=2000):
    s = re.sub(r"<[^>]*>", " ", s or "")
    return " ".join(html.unescape(s).split())[:limit]

def refresh_news():
    added = 0
    for source, url, category in FEEDS:
        try:
            req = Request(url, headers={"User-Agent": "PulseNews/1.0"})
            with urlopen(req, timeout=10) as response:
                data = response.read(1200000)

            root = ET.fromstring(data)
            entries = root.findall(".//item")

            for item in entries[:12]:
                title = clean(item.findtext("title", ""), 200)
                link = (item.findtext("link", "") or "").strip()
                description = clean(item.findtext("description", ""), 700)

                if not title or not link:
                    continue
                if not link.startswith(("https://", "http://")):
                    continue

                with db() as c:
                    cur = c.execute("""
                        INSERT OR IGNORE INTO posts
                        (title,body,author,category,url,created)
                        VALUES(?,?,?,?,?,?)
                    """, (
                        title,
                        description or "Read the original report for details.",
                        source, category, link, time.time()
                    ))
                    added += cur.rowcount

        except Exception as e:
            print("News feed error:", source, str(e)[:120])

    return added

def e(value):
    return escape(str(value or ""), quote=True)

def age(ts):
    seconds = max(0, int(time.time() - ts))
    if seconds < 3600:
        return str(max(1, seconds // 60)) + "m ago"
    if seconds < 86400:
        return str(seconds // 3600) + "h ago"
    return str(seconds // 86400) + "d ago"

def layout(content, username):
    nav = """
    <nav>
      <a href="/">For You</a>
      <a href="/?sort=latest">Latest</a>
      <a href="/?sort=trending">Trending</a>
      <a href="/?category=Business">Business</a>
      <a href="/?category=Technology">Tech</a>
      <a href="/?category=World">World</a>
      <a href="/?category=Community">Community</a>
    </nav>
    """
    return """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#101319">
<title>Pulse — News & Community</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#101319;color:#edf0f7;
font:15px system-ui,-apple-system,sans-serif}
header{background:#171c26;border-bottom:1px solid #303747;
padding:16px;position:sticky;top:0}
.wrap{max-width:700px;margin:auto;padding:14px}
.logo{font-size:27px;font-weight:900;letter-spacing:-1px}
.logo span{color:#899aff}
nav{display:flex;gap:16px;overflow-x:auto;padding-top:12px}
nav a{white-space:nowrap;color:#b5c1ff}
a{color:#aabaff;text-decoration:none}
.card{background:#191f2a;border:1px solid #303747;
border-radius:14px;padding:15px;margin:12px 0}
input,textarea,select{width:100%;padding:12px;margin:6px 0 10px;
background:#101319;color:white;border:1px solid #414b5e;
border-radius:9px;font:inherit}
textarea{min-height:85px}
button{background:#8191ff;color:#101319;font-weight:bold;
border:0;border-radius:9px;padding:10px 14px;font-size:14px}
.secondary{background:#30394a;color:white}
h2{font-size:19px;line-height:1.4}
.small{font-size:12px;color:#9ba7bb}
.pill{background:#2b3345;color:#c3ccff;padding:5px 9px;
border-radius:20px;font-size:12px}
.actions{display:flex;gap:15px;align-items:center;
flex-wrap:wrap;margin-top:14px}
.bodytext{line-height:1.65;overflow-wrap:anywhere}
footer{text-align:center;padding:25px;color:#8993a7}
</style></head><body>
<header><div class="wrap" style="padding:0">
<div class="logo">pulse<span>.</span></div>
<div class="small">News. Ideas. People.</div>
""" + nav + """
</div></header><main class="wrap">
<div class="card">
<form action="/name" method="post">
<label>Your username</label>
<input name="username" maxlength="24" required
placeholder="Choose a username" value=""" + '"' + e(username) + '"' + """>
<button>Save username</button>
</form></div>
""" + content + """
<footer>Pulse · Text-first news and community</footer>
</main></body></html>"""

def get_user(handler):
    cookie = handler.headers.get("Cookie", "")
    match = re.search(r"(?:^|;\s*)pulse_user=([A-Za-z0-9_]{2,24})(?:;|$)", cookie)
    return match.group(1) if match else ""

class Site(BaseHTTPRequestHandler):
    def send_html(self, body, status=200, cookie=None):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def go(self, path="/"):
        self.send_response(303)
        self.send_header("Location", path)
        self.end_headers()

    def form(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 0 or size > 12000:
                return {}
            raw = self.rfile.read(size).decode("utf-8", "replace")
            return parse_qs(raw, keep_blank_values=True)
        except Exception:
            return {}

    def value(self, form, key, limit):
        return clean((form.get(key) or [""])[0], limit)

    def page(self, content, status=200):
        self.send_html(layout(content, get_user(self)), status)

    def do_GET(self):
        u = get_user(self)
        path = urlparse(self.path)
        query = parse_qs(path.query)

        if path.path == "/":
            category = (query.get("category") or [""])[0]
            sort = (query.get("sort") or ["trending"])[0]
            with db() as c:
                sql = "SELECT * FROM posts"
                args = []
                if category in ("Business", "Technology", "World", "Community", "Money"):
                    sql += " WHERE category=?"
                    args.append(category)
                rows = c.execute(sql, args).fetchall()
                posts = []
                for p in rows:
                    d = dict(p)
                    d["score"] = c.execute(
                        "SELECT COUNT(*) FROM votes WHERE post_id=?",
                        (p["id"],)).fetchone()[0]
                    d["comments"] = c.execute(
                        "SELECT COUNT(*) FROM comments WHERE post_id=?",
                        (p["id"],)).fetchone()[0]
                    posts.append(d)

            if sort == "latest":
                posts.sort(key=lambda x: x["created"], reverse=True)
                heading = "Latest"
            else:
                posts.sort(key=lambda x:
                    (x["score"] * 3 + x["comments"] * 2) /
                    (1 + max(0, time.time()-x["created"])/86400),
                    reverse=True)
                heading = "Trending" if sort == "trending" else "For You"

            content = """
            <div class="card"><h3>Start a discussion</h3>
            <form action="/post" method="post">
            <input name="title" maxlength="180" required
            placeholder="Headline or question">
            <textarea name="body" maxlength="2000" required
            placeholder="Share an idea or opinion"></textarea>
            <select name="category">
            <option>Community</option><option>Business</option>
            <option>Money</option><option>Technology</option><option>World</option>
            </select><button>Publish post</button></form>
            <form action="/refresh" method="post">
            <button class="secondary">Refresh news feeds</button></form>
            </div><h3>""" + e(heading) + """</h3>"""

            if not posts:
                content += '<div class="card">No posts yet. Refresh news feeds or publish a discussion.</div>'

            for p in posts[:60]:
                content += """
                <article class="card">
                <span class="pill">""" + e(p["category"]) + """</span>
                <div class="small">""" + e(p["author"]) + " · " + e(age(p["created"])) + """</div>
                <h2><a href="/post/""" + str(p["id"]) + """">""" + e(p["title"]) + """</a></h2>
                <p class="bodytext">""" + e(p["body"]) + """</p>"""
                if p["url"]:
                    content += '<a href="' + e(p["url"]) + '" target="_blank" rel="noopener noreferrer">Original source ↗</a>'
                content += """
                <div class="actions">
                <form action="/vote/""" + str(p["id"]) + """" method="post">
                <button class="secondary">▲ """ + str(p["score"]) + """</button></form>
                <a href="/post/""" + str(p["id"]) + """">💬 """ + str(p["comments"]) + """ comments</a>
                </div></article>"""

            self.page(content)
            return

        match = re.fullmatch(r"/post/([0-9]+)", path.path)
        if match:
            pid = int(match.group(1))
            with db() as c:
                p = c.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
                if not p:
                    self.page("<div class='card'>Post not found.</div>", 404)
                    return
                score = c.execute("SELECT COUNT(*) FROM votes WHERE post_id=?", (pid,)).fetchone()[0]
                comments = c.execute("SELECT * FROM comments WHERE post_id=? ORDER BY created DESC", (pid,)).fetchall()

            content = '<div class="card"><span class="pill">' + e(p["category"]) + '</span><h2>' + e(p["title"]) + '</h2><div class="small">' + e(p["author"]) + ' · ' + e(age(p["created"])) + '</div><p class="bodytext">' + e(p["body"]) + '</p>'
            if p["url"]:
                content += '<p><a href="' + e(p["url"]) + '" target="_blank" rel="noopener noreferrer">Original source ↗</a></p>'
            content += '<form action="/vote/' + str(pid) + '" method="post"><button class="secondary">▲ ' + str(score) + '</button></form></div>'
            content += '<div class="card"><h3>Write a comment</h3><form action="/comment/' + str(pid) + '" method="post"><textarea name="body" maxlength="1000" required></textarea><button>Comment</button></form></div><h3>Comments</h3>'
            for cmt in comments:
                content += '<div class="card"><div class="small">' + e(cmt["author"]) + ' · ' + e(age(cmt["created"])) + '</div><p>' + e(cmt["body"]) + '</p></div>'
            self.page(content)
            return

        self.page("<div class='card'>Page not found. <a href='/'>Home</a></div>", 404)

    def do_POST(self):
        path = urlparse(self.path).path
        f = self.form()
        u = get_user(self)

        if path == "/name":
            name = self.value(f, "username", 24)
            if not re.fullmatch(r"[A-Za-z0-9_]{2,24}", name):
                self.page("<div class='card'>Username must contain 2-24 letters, numbers or underscores.</div>", 400)
                return
            with db() as c:
                c.execute("INSERT OR IGNORE INTO users(username) VALUES(?)", (name,))
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", "pulse_user=" + name + "; Path=/; SameSite=Lax")
            self.end_headers()
            return

        if not u:
            self.go("/")
            return

        if path == "/post":
            title = self.value(f, "title", 180)
            body = self.value(f, "body", 2000)
            category = self.value(f, "category", 20)
            if category not in ("Community", "Business", "Money", "Technology", "World"):
                category = "Community"
            if title and body:
                with db() as c:
                    c.execute("""INSERT INTO posts
                    (title,body,author,category,url,created)
                    VALUES(?,?,?,?,NULL,?)""",
                    (title, body, u, category, time.time()))
            self.go("/")
            return

        match = re.fullmatch(r"/vote/([0-9]+)", path)
        if match:
            with db() as c:
                c.execute("INSERT OR IGNORE INTO votes VALUES(?,?)",
                          (int(match.group(1)), u))
            self.go("/")
            return

        match = re.fullmatch(r"/comment/([0-9]+)", path)
        if match:
            body = self.value(f, "body", 1000)
            pid = int(match.group(1))
            with db() as c:
                exists = c.execute("SELECT id FROM posts WHERE id=?", (pid,)).fetchone()
                if exists and body:
                    c.execute("INSERT INTO comments(post_id,author,body,created) VALUES(?,?,?,?)",
                              (pid, u, body, time.time()))
            self.go("/post/" + str(pid))
            return

        if path == "/refresh":
            threading.Thread(target=refresh_news, daemon=True).start()
            self.go("/")
            return

        self.go("/")

    def log_message(self, format, *args):
        print(args[0] if args else "Request")

if __name__ == "__main__":
    initialize()
    print("=" * 38)
    print("PULSE IS STARTING")
    print(f"Pulse running on port {PORT}")
    print("Keep Pydroid running.")
    print("=" * 38)
    try:
        HTTPServer((HOST, PORT), Site).serve_forever()
    except OSError as err:
        print("Could not start server:", err)
        print("Try closing another running copy of Pulse.")
