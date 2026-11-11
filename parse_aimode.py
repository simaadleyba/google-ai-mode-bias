"""
parse_aimode.py - extract answer text and claim -> source pairs from a saved Google AI Mode page.

  python parse_aimode.py page.html [more.html ...] > answers.jsonl

Markup this relies on (Nov 2026, will change):
  - answer block: parent of <h3> "AI Mode reply for <query>"
  - inline citation chip: <span data-suuid="nCd0md|<uuid>-|"> placed right after the sentence it supports
  - every source behind a chip (incl. the "+N" ones): hidden <div data-suuid="X1OVdc|<uuid>-<n>|">
    whose embedded JSON comment holds title and URL
"""
import json, re, sys, html as htmllib
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

SKIP_HOSTS = ("gstatic.com", "google.com", "googleusercontent.com")
BLOCKS = {"h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "table", "ul", "ol"}


REC = re.compile(r'\["([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",\["((?:[^"\\]|\\.)*)"')


def source_map(raw):
    """uuid -> list of {title, url, domain}, from the JSON records Google embeds in HTML comments."""
    txt = htmllib.unescape(raw)
    hits = list(REC.finditer(txt))
    out = {}
    for k, m in enumerate(hits):
        stop = hits[k + 1].start() if k + 1 < len(hits) else m.end() + 3000
        window = txt[m.end():min(stop, m.end() + 3000)]
        urls = [u.replace("\\u003d", "=").replace("\\u0026", "&") for u in re.findall(r'https?://[^"\\\s]+', window)]
        urls = [u for u in urls if not any(h in urlparse(u).netloc for h in SKIP_HOSTS)
                and urlparse(u).path not in ("", "/")]
        if not urls:
            continue
        rec = {"title": m.group(2).replace('\\"', '"'), "url": urls[0],
               "domain": urlparse(urls[0]).netloc.removeprefix("www.")}
        lst = out.setdefault(m.group(1), [])
        if rec["url"] not in {r["url"] for r in lst}:
            lst.append(rec)
    # some records carry an index instead of a title: borrow the title from another record of the same url
    titles = {r["url"]: r["title"] for rs in out.values() for r in rs if not r["title"].isdigit()}
    for rs in out.values():
        for r in rs:
            if r["title"].isdigit():
                r["title"] = titles.get(r["url"])
    return out


def parse(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    soup = BeautifulSoup(raw, "lxml")
    h3 = soup.find(lambda t: t.name == "h3" and t.get_text().startswith("AI Mode reply for"))
    if not h3:
        return {"file": path, "error": "no AI Mode reply found"}
    query = h3.get_text().removeprefix("AI Mode reply for").strip()
    root = h3.parent
    srcs = source_map(raw)
    claims, buf, heading = [], [], None

    def flush(sources=None):
        text = re.sub(r"\s+", " ", " ".join(buf)).strip()
        buf.clear()
        if text:
            claims.append({"text": text, "heading": heading, "sources": sources or []})

    def walk(node):
        nonlocal heading
        for ch in node.children:
            if isinstance(ch, Comment):
                continue
            if isinstance(ch, NavigableString):
                buf.append(str(ch))
                continue
            if not isinstance(ch, Tag) or ch is h3:
                continue
            if ch.name in ("script", "style", "svg", "button") or "display:none" in ch.get("style", "").replace(" ", ""):
                continue
            suuid = ch.get("data-suuid", "")
            if suuid.startswith("nCd0md|"):  # citation chip ends a claim
                uid = suuid.split("|")[1][:36]
                cited = srcs.get(uid) or [{"title": a.get("aria-label"), "url": a["href"],
                                           "domain": urlparse(a["href"]).netloc.removeprefix("www.")}
                                          for a in ch.find_all("a", href=True)]
                flush(cited)
                continue
            if ch.name in BLOCKS:
                flush()
                if ch.name.startswith("h"):
                    heading = ch.get_text(" ", strip=True)
                    continue
            walk(ch)
            if ch.name in BLOCKS:
                flush()

    walk(root)
    flush()
    cut = next((i for i, c in enumerate(claims) if "Copied to clipboard" in c["text"]), None)
    claims = claims[:cut]
    claims = [c for c in claims if c["text"] != c["heading"]]
    # files saved by google_ai_audit.py are named <qid>_<account>_<ts>.html
    stem = Path(path).stem
    parts = stem.split("_")
    meta = {"id": stem, "qid": parts[0], "account": "_".join(parts[1:-1]), "ts": parts[-1]} if len(parts) >= 3 else {"id": stem}
    return {**meta, "file": path, "query": query, "premise": None,
            "answer": " ".join(c["text"] for c in claims),
            "claims": claims}


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(json.dumps(parse(p), ensure_ascii=False))
