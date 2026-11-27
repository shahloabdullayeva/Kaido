import json
import re
from functools import lru_cache
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent / "learn"
IMAGE = re.compile(r"^!\[(.+?)\]\((.+?)\)$")
GROUPS = {"s": "Start: study plan", "v": "See it: what problems look like", "i": "Issues by system", "": "Topics",
          "p": "Parts A to Z"}
VIDEO = re.compile(r"^@video (.+?) \| (.+)$")
ISSUE = re.compile(r"^::: issue (.+?) \| (stop|soon|watch)$")
CALLOUT = re.compile(r"^> (tip|warn|stop|note): (.+)$")
SWATCH = re.compile(r"\{\{(#[0-9a-fA-F]{6})\}\}")
SEVERITY = {"stop": "Stop now", "soon": "Fix today", "watch": "Schedule it"}
FIELDS = {"looks": "What it looks like", "hear": "What you hear", "smell": "What you smell", "feel": "What the driver feels",
          "dash": "Dash and codes", "why": "Usual causes", "check": "How to check", "do": "What to do",
          "cost": "Typical cost", "dot": "DOT / out of service", "ask": "Ask the driver"}
CALLOUTS = {"tip": "Tip", "warn": "Careful", "stop": "Safety", "note": "Note"}


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
    text = re.sub(r"\[([^\]]+)\]\((/learn/[a-z0-9#-]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\{\{lamp:([a-z0-9-]+)\}\}", r'<img class="lamp" src="/static/learn/lamps/\1.svg" alt="" loading="lazy">', text)
    return SWATCH.sub(r'<span class="swatch" style="background:\1"></span>', text)


def issue_card(title, severity, fields, anchor):
    rows_html = "".join(f'<div class="issue-row issue-{key}"><dt>{FIELDS[key]}</dt><dd>{inline(value)}</dd></div>'
                        for key, value in fields)
    return (f'<article class="issue sev-{severity}" id="{anchor}"><header><h3>{inline(title)}</h3>'
            f'<span class="sev">{SEVERITY[severity]}</span></header><dl>{rows_html}</dl></article>')


def read_issue(lines, index):
    head = ISSUE.match(lines[index].rstrip())
    fields = []
    index += 1
    while index < len(lines) and lines[index].strip() != ":::":
        line = lines[index].strip()
        key, _, value = line.partition(":")
        if key in FIELDS and value:
            fields.append((key, value.strip()))
        elif line and fields:
            fields[-1] = (fields[-1][0], fields[-1][1] + " " + line)
        index += 1
    return head.group(1).strip(), head.group(2), fields, index + 1


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def render(lines, issues=None):
    html, toc = [], []
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        if not line:
            index += 1
            continue
        if ISSUE.match(line):
            title, severity, fields, index = read_issue(lines, index)
            anchor = slug(title)
            html.append(issue_card(title, severity, fields, anchor))
            if issues is not None:
                issues.append({"title": title, "severity": severity, "fields": fields, "anchor": anchor,
                               "section": toc[-1][1] if toc else ""})
            continue
        if CALLOUT.match(line):
            kind, text = CALLOUT.match(line).groups()
            html.append(f'<aside class="callout callout-{kind}"><strong>{CALLOUTS[kind]}</strong><span>{inline(text)}</span></aside>')
            index += 1
            continue
        if line.startswith("@svg "):
            name, _, caption = line[5:].partition(" | ")
            html.append(f'<figure class="learn-figure learn-svg"><img src="/static/learn/{escape(name.strip())}" '
                        f'alt="{escape(caption)}" loading="lazy"><figcaption>{inline(caption)}</figcaption></figure>')
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
        while index < len(lines) and lines[index].strip() and not re.match(r"^(## |\||- |\d+\. |!\[|@video |@svg |::: |> )", lines[index]):
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
        issues = []
        body, toc = render(lines[2:], issues)
        text = re.sub(r"<[^>]+>", " ", body)
        code = path.stem.split("-", 1)[0]
        group = code.rstrip("0123456789")
        found.append({"slug": path.stem.split("-", 1)[1], "number": int(code[len(group):]), "group": GROUPS.get(group, group),
                      "order": (list(GROUPS).index(group) if group in GROUPS else 9, int(code[len(group):])), "title": title,
                      "summary": summary, "html": body, "toc": toc, "text": " ".join(text.split()).lower(),
                      "issues": issues, "code": code})
    found.sort(key=lambda item: item["order"])
    return found


def grouped():
    groups = {}
    for item in topics():
        groups.setdefault(item["group"], []).append(item)
    return list(groups.items())


def all_issues():
    found = []
    for item in topics():
        for issue in item["issues"]:
            text = " ".join([issue["title"]] + [value for _, value in issue["fields"]])
            found.append({**issue, "topic": item["title"], "slug": item["slug"], "html": issue_card(
                issue["title"], issue["severity"], issue["fields"], issue["anchor"]),
                "text": re.sub(r"<[^>]+>|\{\{#\w+\}\}", " ", text).lower()})
    return found


def systems():
    seen = {}
    for issue in all_issues():
        seen.setdefault(issue["slug"], issue["topic"])
    return list(seen.items())


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


ICON = '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{}</svg>'
SYSTEMS = [
    {"key": "engine", "title": "Engine and oil", "blurb": "How the diesel makes power, oil, knocks, smoke and no-starts",
     "topics": ["engine", "oils-and-fluids"], "issues": ["engine-issues", "oil-lubrication-issues"],
     "parts": ["parts-engine-core", "parts-lubrication"],
     "icon": '<path d="M4 9h3V7h7v2h2l2 2h2v6h-2l-2 2H8l-2-2H4z"/><path d="M2 11v4"/>'},
    {"key": "air-exhaust", "title": "Turbo and aftertreatment", "blurb": "Air intake, turbo, DPF, DEF, regens and derates",
     "topics": ["aftertreatment"], "issues": ["air-intake-turbo-issues", "aftertreatment-issues"],
     "parts": ["parts-air-intake-and-turbo", "parts-exhaust-and-emissions"],
     "icon": '<path d="M3 8h10a3 3 0 1 0-3-3"/><path d="M3 12h15a3 3 0 1 1-3 3"/><path d="M3 16h7"/>'},
    {"key": "fuel", "title": "Fuel system", "blurb": "Tanks, filters, gelling, water, injectors",
     "topics": ["fuel"], "issues": ["fuel-system-issues"], "parts": ["parts-fuel-system"],
     "icon": '<rect x="4" y="4" width="10" height="16" rx="1.5"/><path d="M4 10h10M14 7h2l3 3v7a1.5 1.5 0 0 0 3 0V9"/>'},
    {"key": "cooling", "title": "Cooling, AC and APU", "blurb": "Overheating, coolant loss, fans, belts, cab comfort",
     "topics": ["cooling-ac"], "issues": ["cooling-issues", "hvac-apu-issues"],
     "parts": ["parts-cooling-system", "parts-hvac-and-apu"],
     "icon": '<path d="M12 3v11"/><circle cx="12" cy="17" r="3.5"/><path d="M12 6h3M12 9h3"/>'},
    {"key": "electrical", "title": "Electrical and codes", "blurb": "Batteries, charging, lights, fault codes, ELD",
     "topics": ["electrical", "fault-codes"], "issues": ["electrical-issues", "lights-issues", "telematics-camera-issues"],
     "parts": ["parts-electrical-electronics-and-sensors", "parts-lights"],
     "icon": '<path d="M13 2 5 13h6l-1 9 8-12h-6z"/>'},
    {"key": "brakes", "title": "Air brakes", "blurb": "Air supply, chambers, slack adjusters, linings, ABS",
     "topics": ["air-brakes"], "issues": ["air-brake-issues", "wheel-end-issues"], "parts": ["parts-air-brakes"],
     "icon": '<circle cx="12" cy="12" r="6"/><path d="M4.5 7a9 9 0 0 0 0 10M19.5 7a9 9 0 0 1 0 10"/><path d="M12 10v3"/>'},
    {"key": "tires", "title": "Tires and wheels", "blurb": "Tread, pressure, wear patterns, hubs, lug nuts",
     "topics": ["tires"], "issues": ["tire-wear-patterns", "wheel-end-issues"], "parts": ["parts-wheel-ends-and-tires"],
     "icon": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><path d="M12 3v5M12 16v5M3 12h5M16 12h5"/>'},
    {"key": "drivetrain", "title": "Clutch, transmission, axles", "blurb": "Shifting, driveshafts, U-joints, differentials",
     "topics": ["drivetrain"], "issues": ["clutch-transmission-issues", "driveline-axle-issues"],
     "parts": ["parts-clutch-and-transmission", "parts-driveline-and-axles"],
     "icon": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/>'},
    {"key": "steering", "title": "Steering and suspension", "blurb": "Play, pull, kingpins, air bags, springs, shocks",
     "topics": ["steering-suspension"], "issues": ["steering-issues", "suspension-issues"],
     "parts": ["parts-steering", "parts-suspension"],
     "icon": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2"/><path d="M3.5 10h6.5M14 10h6.5M12 14v7"/>'},
    {"key": "trailer", "title": "Trailers, coupling, reefers", "blurb": "Fifth wheel, gladhands, sliders, doors, reefer units",
     "topics": ["trailers-coupling"], "issues": ["coupling-frame-issues", "trailer-issues", "reefer-issues"],
     "parts": ["parts-frame-fifth-wheel-and-coupling", "parts-trailer", "parts-reefer-unit"],
     "icon": '<rect x="2" y="6" width="15" height="10" rx="1"/><path d="M17 12h3l2 2"/><circle cx="6" cy="18" r="2"/><circle cx="12" cy="18" r="2"/>'},
    {"key": "cab", "title": "Cab and body", "blurb": "Glass, mirrors, wipers, doors, seats, body damage",
     "topics": ["cab-and-body"], "issues": ["cab-body-issues"],
     "parts": ["parts-cab-interior-and-controls", "parts-body-aero-and-mirrors"],
     "icon": '<path d="M3 17V9l4-4h7v12"/><path d="M14 9h4l3 4v4h-7"/><path d="M7 5v4H3"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>'},
]
SHELVES = [
    ("Start here", "Read these first", ["start-here", "study-schedule", "truck", "how-fleets-work"]),
    ("The office side", "Running maintenance for a fleet", ["maintenance", "pre-trip", "breakdowns", "dot",
                                                            "shops-invoices", "parts-prices", "loves-speedco", "costs"]),
    ("Quick reference", "Look things up", ["symptoms", "fault-codes", "vin", "glossary", "sources"]),
]


def by_slug():
    return {item["slug"]: item for item in topics()}


def minutes(item):
    return max(1, round(len(item["text"].split()) / 200))


def system_groups():
    index = by_slug()
    out = []
    for system in SYSTEMS:
        pick = lambda keys: [index[k] for k in keys if k in index]
        issues = pick(system["issues"])
        out.append({**system, "icon_svg": ICON.format(system["icon"]), "topic_items": pick(system["topics"]),
                    "issue_items": issues, "part_items": pick(system["parts"]), "see_items": pick(system.get("see", [])),
                    "issue_count": sum(len(i["issues"]) for i in issues),
                    "stop_count": sum(1 for i in issues for x in i["issues"] if x["severity"] == "stop")})
    return out


def system(key):
    return next((s for s in system_groups() if s["key"] == key), None)


def system_of(slug):
    for item in system_groups():
        if slug in item["topics"] + item["issues"] + item["parts"] + item.get("see", []):
            return item
    return None


def shelves():
    index = by_slug()
    return [(title, note, [index[k] for k in keys if k in index]) for title, note, keys in SHELVES]
