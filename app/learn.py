import json
import re
from functools import lru_cache
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent / "learn"
IMAGE = re.compile(r"^!\[(.+?)\]\((.+?)\)$")
GROUPS = {"s": "Start: study plan", "": "Topics", "p": "Parts A to Z"}
VIDEO = re.compile(r"^@video (.+?) \| (.+)$")


@lru_cache(maxsize=1)
def credits():
    path = ROOT / "credits.json"
    return json.loads(path.read_text()) if path.exists() else {}


def figure(caption, name):
    credit = credits().get(name)
    line = ""
    if credit:
        line = (f'<span class="learn-credit">Photo: {escape(credit["author"])}, {escape(credit["license"])}, '
                f'<a href="{escape(credit["page"])}" target="_blank" rel="noopener">Wikimedia Commons</a></span>')
    return (f'<figure class="learn-figure"><img src="/static/learn/{escape(name)}" alt="{escape(caption)}" loading="lazy">'
            f'<figcaption>{inline(caption)}{line}</figcaption></figure>')


def video(title, query):
    from urllib.parse import quote_plus
    return (f'<a class="learn-video" href="https://www.youtube.com/results?search_query={quote_plus(query)}" '
            f'target="_blank" rel="noopener"><span class="learn-play"></span><span><strong>{inline(title)}</strong>'
            f'<small>YouTube</small></span></a>')


def inline(text):
    text = escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    return text


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def render(lines):
    html, toc = [], []
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        if not line:
            index += 1
            continue
        if IMAGE.match(line):
            html.append(figure(*IMAGE.match(line).groups()))
            index += 1
            continue
        if VIDEO.match(line):
            links = []
            while index < len(lines) and VIDEO.match(lines[index].rstrip()):
                links.append(video(*VIDEO.match(lines[index].rstrip()).groups()))
                index += 1
            html.append('<div class="learn-videos">' + "".join(links) + "</div>")
            continue
        if line.startswith("## "):
            title = line[3:].strip()
            toc.append((slug(title), title))
            html.append(f'<h2 id="{slug(title)}">{inline(title)}</h2>')
            index += 1
            continue
        if line.startswith("|"):
            block = []
            while index < len(lines) and lines[index].startswith("|"):
                block.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")])
                index += 1
            head, body = block[0], [row for row in block[1:] if not all(set(c) <= set("-: ") for c in row)]
            html.append('<div class="table-wrap"><table><thead><tr>' + "".join(f"<th>{inline(c)}</th>" for c in head)
                        + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>" for row in body)
                        + "</tbody></table></div>")
            continue
        if re.match(r"^(- |\d+\. )", line):
            ordered = bool(re.match(r"^\d+\. ", line))
            items = []
            while index < len(lines) and re.match(r"^(- |\d+\. )", lines[index]):
                items.append(re.sub(r"^(- |\d+\. )", "", lines[index].rstrip()))
                index += 1
            tag = "ol" if ordered else "ul"
            html.append(f"<{tag}>" + "".join(f"<li>{inline(item)}</li>" for item in items) + f"</{tag}>")
            continue
        para = []
        while index < len(lines) and lines[index].strip() and not re.match(r"^(## |\||- |\d+\. |!\[|@video )", lines[index]):
            para.append(lines[index].strip())
            index += 1
        html.append(f"<p>{inline(' '.join(para))}</p>")
    return "\n".join(html), toc


@lru_cache(maxsize=1)
def topics():
    found = []
    for path in sorted(ROOT.glob("*.md")):
        lines = path.read_text().splitlines()
        title = lines[0].lstrip("# ").strip()
        summary = lines[1].strip() if len(lines) > 1 else ""
        body, toc = render(lines[2:])
        text = re.sub(r"<[^>]+>", " ", body)
        code = path.stem.split("-", 1)[0]
        group = code.rstrip("0123456789")
        found.append({"slug": path.stem.split("-", 1)[1], "number": int(code[len(group):]), "group": GROUPS.get(group, group),
                      "order": (list(GROUPS).index(group) if group in GROUPS else 9, int(code[len(group):])), "title": title,
                      "summary": summary, "html": body, "toc": toc, "text": " ".join(text.split()).lower()})
    found.sort(key=lambda item: item["order"])
    return found


def grouped():
    groups = {}
    for item in topics():
        groups.setdefault(item["group"], []).append(item)
    return list(groups.items())


def topic(name):
    return next((item for item in topics() if item["slug"] == name), None)


def search(query):
    words = [w for w in query.lower().split() if w]
    if not words:
        return []
    hits = []
    for item in topics():
        haystack = item["title"].lower() + " " + item["text"]
        if all(word in haystack for word in words):
            position = item["text"].find(words[0])
            start = max(0, position - 80)
            hits.append({**item, "snippet": item["text"][start:start + 220]})
    return hits
