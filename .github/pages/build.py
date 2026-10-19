"""Builds opentokenmini.org into the given dir: the landing at / and /<lang>/, under /docs/ every tracked file
as is plus an HTML page per .md, and sitemap.xml, robots.txt, llms.txt. Usage: python3 .github/pages/build.py _site"""
import html, pathlib, posixpath, re, shutil, subprocess, sys
import markdown
import i18n

SITE = "https://opentokenmini.org/"
DOCS = SITE + "docs/"
REPO = "https://github.com/OpenTokenMini/opentokenmini/blob/main/"
DESC_MAX = 160
PAGES = pathlib.Path(__file__).parent
OUT = pathlib.Path(sys.argv[1])
HOME = "00-docs/humans/overview.md"  # served at /docs/
NAV_LABEL = {HOME: "How it works", "README.md": "README", "AGENTS.md": "For agents"}
NAV_HIDE = ("00-docs/humans/es/", "00-docs/humans/zh/")  # generated translations, reached from the language links instead
ASSETS = ["logo.svg", "flow.svg", "og.png", "dashboard.png"]  # from 00-docs/humans/, served at the root for the landing

files = [f for f in subprocess.check_output(["git", "ls-files"], text=True).split() if not f.startswith(".github/")]
docs = [f for f in files if f.endswith(".md")]

def page_of(md):
    """HOME is the docs home page; every other .md sits next to its source as .html."""
    return "index.html" if md == HOME else md[:-3] + ".html"

def target(src, href):
    """Where a relative link from src should point on the site."""
    path, _, frag = href.partition("#")
    full = posixpath.normpath(posixpath.join(posixpath.dirname(src), path))
    if path.endswith("/") or full + "/README.md" in docs or full + "/AGENTS.md" in docs:
        full = next((f"{full}/{i}" for i in ("README.md", "AGENTS.md") if f"{full}/{i}" in docs), full)
    if full in docs:
        return "/docs/" + page_of(full).removesuffix("index.html") + ("#" + frag if frag else "")
    return REPO + full

def fix_links(src, body):
    def sub(m):
        attr, href = m.group(1), m.group(2)
        if re.match(r"^[a-z]+:|^#|^/", href):
            return m.group(0)
        if attr == "src":  # images are copied to the site as is
            return f'src="/docs/{posixpath.normpath(posixpath.join(posixpath.dirname(src), href))}"'
        return f'{attr}="{target(src, href)}"'
    return re.sub(r'(href|src)="([^"]+)"', sub, body)

def ignored(path):
    """Local files the docs name on purpose but git ignores (e.g. 01-deploy/config.json)."""
    return "todelete" not in path and subprocess.run(["git", "check-ignore", "-q", "--no-index", path]).returncode == 0

def broken(src, text):
    """Relative links and backticked repo paths in src that point at nothing tracked."""
    known = set(files) | {"/".join(f.split("/")[:i]) for f in files for i in range(1, f.count("/") + 1)}
    refs = re.findall(r"\]\(([^)#\s]+)", text) + re.findall(r'src="([^"#:]+)"', text)
    refs += [r for r in re.findall(r"`([^`\s]+)`", text) if "/" in r and re.match(r"(\.\./)*[0-9]{2}-", r)]
    out = []
    for r in refs:
        if re.match(r"^[a-z]+:|^/|^~", r) or "<" in r:
            continue
        path = r.split()[0].rstrip("/")
        here = posixpath.normpath(posixpath.join(posixpath.dirname(src), path))
        if here not in known and posixpath.normpath(path) not in known and not ignored(path):
            out.append(r)
    return out

def label(md):
    """Sidebar text for md: its section overview, or its first heading without markup."""
    if md.endswith("AGENTS.md") and md.count("/") == 1:
        return "Overview"
    if md in NAV_LABEL:
        return NAV_LABEL[md]
    h1 = re.search(r"^# (.+)$", pathlib.Path(md).read_text(), re.M)
    return (re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else "") or posixpath.basename(md)[:-3].capitalize()

def nav(current):
    """Docs tree for the right sidebar: home pages, then one collapsible group per top folder, current page marked."""
    def item(md):
        mark = ' aria-current="page"' if md == current else ""
        return f'<li><a href="/docs/{page_of(md).removesuffix("index.html")}"{mark}>{html.escape(label(md))}</a></li>'
    shown = [d for d in docs if not d.startswith(NAV_HIDE) and d not in NAV_LABEL]
    top = [HOME, "README.md", "AGENTS.md"]
    out = '<nav class="tree"><ul>' + "".join(item(d) for d in top) + "</ul>"
    for group in sorted({d.split("/")[0] for d in shown if "/" in d}):
        pages = sorted((d for d in shown if d.startswith(group + "/")),
                       key=lambda d: (not d.endswith("/AGENTS.md") or d.count("/") > 1, "METHOD" not in d, d))
        name = re.sub(r"^\d+-", "", group)
        opened = " open" if current in pages else ""
        out += f'<details{opened}><summary>{name}</summary><ul>' + "".join(item(d) for d in pages) + "</ul></details>"
    return out + "</nav>"

def description(text):
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if block and not block.startswith(("#", "[", "<", "-", "|", "`", ">")):
            plain = re.sub(r"[`*_]|\[([^\]]*)\]\([^)]*\)", r"\1", " ".join(block.split()))
            return plain if len(plain) <= DESC_MAX else plain[:DESC_MAX].rsplit(" ", 1)[0] + "…"
    return "OpenTokenMini docs"

stale = [d.format(lang=l) for s, d in i18n.MD.items() for l in i18n.LANGS
         if pathlib.Path(d.format(lang=l)).read_text() != i18n.md(s, d.format(lang=l), l)]
if stale:
    sys.exit("translations out of date, run python3 .github/pages/i18n.py: " + ", ".join(stale))

template = (PAGES / "template.html").read_text()
for f in files:
    (OUT / "docs" / f).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(f, OUT / "docs" / f)
for a in ASSETS:
    shutil.copy("00-docs/humans/" + a, OUT / a)
shutil.copy(i18n.LANDING, OUT / "index.html")
for lang in i18n.LANGS:
    (OUT / lang).mkdir(exist_ok=True)
    (OUT / lang / "index.html").write_text(i18n.landing(lang))

bad = {md: broken(md, pathlib.Path(md).read_text()) for md in docs}
bad = {k: v for k, v in bad.items() if v}
if bad:
    sys.exit("broken links:\n" + "\n".join(f"  {k}: {', '.join(v)}" for k, v in bad.items()))

for md in docs:
    text = pathlib.Path(md).read_text()
    h1 = re.search(r"^# (.+)$", text, re.M)
    title = h1.group(1).strip() if h1 else md
    if md == HOME:
        title = "OpenTokenMini docs: measure what AI agents cost and produce"
    elif not title.startswith("OpenTokenMini"):
        title += " · OpenTokenMini"
    body = fix_links(md, markdown.markdown(text, extensions=["tables", "fenced_code"]))
    url = DOCS + page_of(md).removesuffix("index.html")
    fields = {"title": title, "description": description(text), "url": url, "raw": "/docs/" + md,
              "github": REPO + md, "path": md, "nav": nav(md), "body": body}
    out = template
    for k, v in fields.items():
        out = out.replace("{" + k + "}", v if k in ("body", "nav") else html.escape(v))
    (OUT / "docs" / page_of(md)).write_text(out)

urls = [SITE] + [SITE + l + "/" for l in i18n.LANGS] + [DOCS + page_of(md).removesuffix("index.html") for md in docs]
(OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    + "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>\n")
(OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}sitemap.xml\n")
(OUT / "llms.txt").write_text((PAGES / "llms.txt").read_text()
    + "".join(f"- [{md}]({DOCS}{md})\n" for md in docs))
