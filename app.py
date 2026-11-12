import os
import re
import json
import ipaddress
import socket
from html import escape
from urllib.parse import urljoin, urlparse, quote, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, redirect, request, stream_with_context

app = Flask(__name__)
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
MAX_BYTES = 5 * 1024 * 1024
BRAVE_KEY = os.environ.get("BRAVE_API_KEY", "")  # optional, most reliable search


@app.after_request
def headers(r):
    r.headers["Referrer-Policy"] = "no-referrer"
    return r


# ---------- helpers ----------
def prox(u):
    return "/p?u=" + quote(u, safe="")


def asset(u):
    return "/r?u=" + quote(u, safe="")


def media(u):
    return "/v?u=" + quote(u, safe="")


def safe_url(raw):
    """Block private/internal addresses (SSRF protection)."""
    u = urlparse(raw)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("Only http and https links work here.")
    for info in socket.getaddrinfo(u.hostname, None):
        if not ipaddress.ip_address(info[4][0].split("%")[0]).is_global:
            raise ValueError("That address is not allowed.")
    return raw


def fetch(url, method="GET", data=None, headers=None):
    for _ in range(6):
        safe_url(url)
        r = requests.request(
            method, url, data=data, stream=True, timeout=15, allow_redirects=False,
            headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9", "DNT": "1", **(headers or {})},
        )
        if r.is_redirect and r.headers.get("location"):
            url, method, data = urljoin(url, r.headers["location"]), "GET", None
            continue
        body = r.raw.read(MAX_BYTES + 1, decode_content=True)
        if len(body) > MAX_BYTES:
            raise ValueError("Page is too large.")
        return r, body, url
    raise ValueError("Too many redirects.")


STYLE = """
*{box-sizing:border-box}body{margin:0;font:16px/1.5 system-ui,sans-serif;color:#1c2733;background:#fff}
.wrap{max-width:720px;margin:0 auto;padding:20px 16px}
.res{margin:0 0 22px}.res a{font-size:18px;color:#1a5fb4;text-decoration:none}.res a:hover{text-decoration:underline}
.res small{display:block;color:#4d7a4d;word-break:break-all}.res p{margin:4px 0 0;color:#444}
.err{padding:14px;background:#fdecec;border-radius:6px;color:#8a1f1f}
.hint{color:#667;margin-top:40px}
"""


def page(title, body):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="referrer" content="no-referrer"><meta name="robots" content="noindex,nofollow">'
            "<title>%s</title><style>%s</style></head><body><div class=\"wrap\">%s</div></body></html>"
            % (escape(title), STYLE, body))


# ---------- decoy home page ----------
INDEX = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Learn Lab | Study guides for curious people</title>
<meta name="description" content="Short, clear study guides on science, history and writing.">
<style>
:root{--ink:#1c2733;--muted:#5a6978;--bg:#f3f6f9;--card:#fff;--line:#d9e1e8;--accent:#2a6f6a}
@media (prefers-color-scheme:dark){:root{--ink:#e6edf3;--muted:#9aa9b8;--bg:#121a22;--card:#1a242e;--line:#2a3743;--accent:#6cc4bb}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.65 Georgia,serif}
header{border-bottom:1px solid var(--line);background:var(--card)}
.in{max-width:760px;margin:0 auto;padding:0 20px}
header .in{display:flex;justify-content:space-between;align-items:center;height:60px}
.logo{font-weight:700;font-size:20px;color:var(--accent);text-decoration:none}
nav a{margin-left:20px;color:var(--muted);text-decoration:none;font:15px system-ui,sans-serif}
h1{font-size:2.1rem;line-height:1.2;margin:48px 0 10px}
.lead{color:var(--muted);margin:0 0 36px;font-size:1.1rem}
article{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:24px 26px;margin-bottom:20px}
article h2{margin:0 0 8px;font-size:1.3rem}article p{margin:0}
article .tag{font:13px system-ui,sans-serif;color:var(--accent);margin-bottom:6px;display:block}
.facts{padding-left:20px}
footer{padding:50px 0 70px;color:var(--muted)}
a.dot{color:inherit;text-decoration:none;cursor:text}
</style></head><body>
<header><div class="in"><a class="logo" href="/">Learn Lab</a>
<nav><a href="#science">Science</a><a href="#history">History</a><a href="#writing">Writing</a></nav></div></header>
<main class="in">
<h1>Short guides for long-term learning</h1>
<p class="lead">Pick a topic, read for five minutes, and remember more of it next week.</p>
<article id="science"><span class="tag">Science</span><h2>How photosynthesis works</h2>
<p>Plants capture light in their chloroplasts and use it to turn water and carbon dioxide into glucose and oxygen. The light-dependent reactions make energy carriers, and the Calvin cycle uses them to build sugar.</p></article>
<article id="history"><span class="tag">History</span><h2>Why the printing press mattered</h2>
<p>Before movable type, books were copied by hand and cost a fortune. Gutenberg's press in the 1450s made texts cheaper, spread literacy, and helped ideas travel across Europe within a few decades.</p></article>
<article id="writing"><span class="tag">Study skills</span><h2>Four habits that make notes useful</h2>
<ul class="facts"><li>Write in your own words instead of copying.</li><li>Test yourself before rereading.</li>
<li>Space reviews over days, not hours.</li><li>Explain the idea to someone else.</li></ul></article>
</main>
<footer><div class="in"><p>New guides are added every week, and each one is written to be finished in a single sitting. Keep reading, keep asking questions, and keep learning<a class="dot" href="/browse" aria-label="Open browser">.</a></p></div></footer>
</body></html>"""


# ---------- browser shell: search bar + iframe ----------
SHELL = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><meta name="robots" content="noindex,nofollow">
<title>Learn Lab | Study guides</title>
<style>
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{display:flex;flex-direction:column;font:16px system-ui,sans-serif}
.bar{display:flex;gap:8px;align-items:center;padding:10px 14px;background:#16222f}
.bar a{color:#9fb3c8;text-decoration:none;font-size:14px}
.bar form{flex:1;display:flex;gap:8px}
.bar input{flex:1;min-width:0;padding:9px 12px;border:0;border-radius:6px;font-size:16px}
.bar button{padding:9px 16px;border:0;border-radius:6px;background:#3d8bd9;color:#fff;font-size:15px;cursor:pointer}
iframe{flex:1;width:100%;border:0;background:#fff}
</style></head><body>
<div class="bar"><a href="/" onclick="location.replace('/');return false">Exit</a>
<form action="/s" method="post" target="view" autocomplete="off"
      onsubmit="var f=this;setTimeout(function(){f.q.value='';f.q.focus()},50)">
<input name="q" placeholder="Search privately or paste a link" autofocus>
<button>Go</button></form></div>
<iframe name="view" src="/blank"></iframe>
</body></html>"""


@app.route("/")
def index():
    return INDEX


@app.route("/browse")
def browse():
    return Response(SHELL, headers={"Cache-Control": "no-store"})


@app.route("/blank")
def blank():
    html = page("Browser", '<p class="hint">Type a search or paste a web address above. Scripts, trackers and cookies are blocked.</p>')
    return Response(html, headers={"Cache-Control": "no-store"})


# ---------- /s : search ----------
def results_brave(q):
    _, body, _ = fetch(
        "https://api.search.brave.com/res/v1/web/search?q=" + quote(q) + "&count=15",
        headers={"X-Subscription-Token": BRAVE_KEY, "Accept": "application/json"},
    )
    items = json.loads(body).get("web", {}).get("results", [])
    out = []
    for it in items:
        desc = BeautifulSoup(it.get("description", ""), "html.parser").get_text()
        out.append((it.get("title", it["url"]), it["url"], desc))
    return out


def results_ddg(q):
    _, body, _ = fetch("https://html.duckduckgo.com/html/", "POST", {"q": q})
    soup = BeautifulSoup(body, "html.parser")
    out = []
    for el in soup.select(".result"):
        a = el.select_one("a.result__a")
        if not a or not a.get("href"):
            continue
        link = urlparse(urljoin("https://duckduckgo.com", a["href"]))
        href = parse_qs(link.query).get("uddg", [link.geturl()])[0]
        if (urlparse(href).hostname or "").endswith("duckduckgo.com"):
            continue
        sn = el.select_one(".result__snippet")
        out.append((a.get_text().strip(), href, sn.get_text().strip() if sn else ""))
    return out


@app.route("/s", methods=["GET", "POST"])
def search():
    q = (request.form.get("q") or request.args.get("q") or "").strip()[:300]
    if not q:
        return redirect("/blank")
    if re.match(r"^https?://", q, re.I) or re.match(r"^[\w-]+(\.[\w-]+)+(/\S*)?$", q):
        return redirect(prox(q if q.lower().startswith("http") else "https://" + q))
    try:
        results = results_brave(q) if BRAVE_KEY else results_ddg(q)
        out = ""
        for title, href, snippet in results:
            out += ('<div class="res"><a href="%s">%s</a><small>%s</small><p>%s</p></div>'
                    % (escape(prox(href)), escape(title), escape(href), escape(snippet)))
        if not out:
            out = ('<p class="hint">No results found. If this keeps happening, the search engine may be '
                   'blocking this server. Set a BRAVE_API_KEY environment variable to fix it.</p>')
        return Response(page(q, out), headers={"Cache-Control": "no-store"})
    except Exception as e:
        return Response(page("Error", '<div class="err">Search failed: %s</div>' % escape(str(e))), 502)


# ---------- /p : proxied page ----------
@app.route("/p")
def proxy():
    target = request.args.get("u", "")
    try:
        if "__action" in request.args:
            t = urlparse(request.args["__action"])
            params = {k: v for k, v in request.args.items() if k not in ("__action", "u")}
            target = t._replace(query=urlencode(params)).geturl()
        r, body, final = fetch(target)
        ctype = r.headers.get("content-type", "")
        if not any(x in ctype.lower() for x in ("text/html", "application/xhtml")):
            return Response(body, content_type=ctype or "application/octet-stream",
                            headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
                                     "Cache-Control": "no-store"})

        soup = BeautifulSoup(body, "html.parser")
        for t in soup.select("script, noscript, iframe, frame, object, embed, base, "
                             'link[rel~="preload"], link[rel~="prefetch"], link[rel~="preconnect"], '
                             'link[rel~="dns-prefetch"], meta[http-equiv="refresh"], meta[name="referrer"]'):
            t.decompose()
        for el in soup.find_all(True):
            for k in list(el.attrs):
                if k.lower().startswith("on"):
                    del el.attrs[k]

        def absu(v):
            try:
                return urljoin(final, v)
            except Exception:
                return None

        for a in soup.find_all("a", href=True):
            h = a["href"]
            if h.startswith("#"):
                continue
            if h.lower().startswith(("javascript:", "data:", "mailto:", "tel:")):
                del a["href"]
                continue
            a["href"] = prox(absu(h))
            a.attrs.pop("target", None)
            a.attrs.pop("ping", None)
        for l in soup.select('link[rel~="stylesheet"][href]'):
            l["href"] = asset(absu(l["href"]))

        # images
        for el in soup.select("img, picture source"):
            raw = el.get("data-src") or el.get("src")
            for k in ("srcset", "data-srcset", "loading"):
                el.attrs.pop(k, None)
            if raw:
                el["src"] = asset(absu(raw))

        # video / audio (plain files only, no JS players)
        for el in soup.select("video, audio"):
            for k in ("autoplay", "preload"):
                el.attrs.pop(k, None)
            el["controls"] = ""
            if el.get("src"):
                el["src"] = media(absu(el["src"]))
            if el.get("poster"):
                el["poster"] = asset(absu(el["poster"]))
        for el in soup.select("video source, audio source"):
            if el.get("src"):
                el["src"] = media(absu(el["src"]))
            el.attrs.pop("srcset", None)

        for f in soup.find_all("form"):
            action = absu(f.get("action") or final)
            f["method"], f["action"] = "get", "/p"
            f.insert(0, soup.new_tag("input", attrs={"type": "hidden", "name": "__action", "value": action}))

        (soup.head or soup).append(BeautifulSoup("<style>%s</style>" % STYLE, "html.parser"))
        return Response(str(soup), content_type="text/html; charset=utf-8", headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'self' 'unsafe-inline'; font-src data:; form-action 'self'",
        })
    except Exception as e:
        return Response(page("Error", '<div class="err">Could not open that page: %s</div>' % escape(str(e))), 502)


# ---------- /r : proxied images & CSS only ----------
@app.route("/r")
def res_proxy():
    try:
        r, body, _ = fetch(request.args.get("u", ""))
        ctype = r.headers.get("content-type", "")
        if not ctype.lower().startswith(("image/", "text/css")):
            return Response(status=415)
        return Response(body, content_type=ctype, headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})
    except Exception:
        return Response(status=502)


# ---------- /v : streamed video & audio (supports Range/seeking) ----------
@app.route("/v")
def media_proxy():
    url = request.args.get("u", "")
    try:
        h = {"User-Agent": UA, "DNT": "1"}
        if request.headers.get("Range"):
            h["Range"] = request.headers["Range"]
        r = None
        for _ in range(6):
            safe_url(url)
            r = requests.get(url, headers=h, stream=True, timeout=15, allow_redirects=False)
            if r.is_redirect and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                r.close()
                continue
            break
        else:
            return Response(status=502)
        ctype = r.headers.get("content-type", "")
        if not ctype.lower().startswith(("video/", "audio/")):
            r.close()
            return Response(status=415)
        out = {k: r.headers[k] for k in ("Content-Length", "Content-Range", "Accept-Ranges") if k in r.headers}
        out["Cache-Control"] = "no-store"

        def gen():
            try:
                for chunk in r.iter_content(65536):
                    yield chunk
            finally:
                r.close()

        return Response(stream_with_context(gen()), status=r.status_code, content_type=ctype, headers=out)
    except Exception:
        return Response(status=502)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
