"""Builds docs.opentokenmini.org into the given dir: every tracked file as is, an HTML page per .md,
sitemap.xml, robots.txt and llms.txt. Usage: python3 .github/pages/build.py _site"""
import html, pathlib, posixpath, re, shutil, subprocess, sys
import markdown

SITE = "https://docs.opentokenmini.org/"
REPO = "https://github.com/OpenTokenMini/opentokenmini/blob/main/"
DESC_MAX = 160
PAGES = pathlib.Path(__file__).parent
OUT = pathlib.Path(sys.argv[1])

files = [f for f in subprocess.check_output(["git", "ls-files"], text=True).split() if not f.startswith(".github/")]
docs = [f for f in files if f.endswith(".md")]

def page_of(md):
    """README.md at the root is the home page; every other .md sits next to its source as .html."""
    return "index.html" if md == "README.md" else md[:-3] + ".html"

def target(src, href):
    """Where a relative link from src should point on the site."""
    path, _, frag = href.partition("#")
    full = posixpath.normpath(posixpath.join(posixpath.dirname(src), path))
    if path.endswith("/") or full + "/README.md" in docs or full + "/AGENTS.md" in docs:
        full = next((f"{full}/{i}" for i in ("README.md", "AGENTS.md") if f"{full}/{i}" in docs), full)
    if full in docs:
        return "/" + page_of(full).removesuffix("index.html") + ("#" + frag if frag else "")
    return REPO + full

def fix_links(src, body):
    def sub(m):
        attr, href = m.group(1), m.group(2)
        if re.match(r"^[a-z]+:|^#|^/", href):
            return m.group(0)
        return f'{attr}="{target(src, href)}"'
    return re.sub(r'(href|src)="([^"]+)"', sub, body)

def description(text):
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if block and not block.startswith(("#", "[", "<", "-", "|", "`", ">")):
            plain = re.sub(r"[`*_]|\[([^\]]*)\]\([^)]*\)", r"\1", " ".join(block.split()))
            return plain if len(plain) <= DESC_MAX else plain[:DESC_MAX].rsplit(" ", 1)[0] + "…"
    return "OpenTokenMini docs"

template = (PAGES / "template.html").read_text()
OUT.mkdir(parents=True, exist_ok=True)
for f in files:
    (OUT / f).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(f, OUT / f)
shutil.copy(PAGES / "logo.svg", OUT / "logo.svg")

for md in docs:
    text = pathlib.Path(md).read_text()
    h1 = re.search(r"^# (.+)$", text, re.M)
    title = h1.group(1).strip() if h1 else md
    if md == "README.md":
        title = "OpenTokenMini docs: measure what AI agents cost and produce"
    elif not title.startswith("OpenTokenMini"):
        title += " · OpenTokenMini"
    body = fix_links(md, markdown.markdown(text, extensions=["tables", "fenced_code"]))
    url = SITE + ("" if md == "README.md" else page_of(md))
    fields = {"title": title, "description": description(text), "url": url, "raw": "/" + md,
              "github": REPO + md, "path": md, "body": body}
    out = template
    for k, v in fields.items():
        out = out.replace("{" + k + "}", v if k == "body" else html.escape(v))
    (OUT / page_of(md)).write_text(out)

urls = [SITE + ("" if md == "README.md" else page_of(md)) for md in docs]
(OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    + "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>\n")
(OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}sitemap.xml\n")
(OUT / "llms.txt").write_text((PAGES / "llms.txt").read_text()
    + "".join(f"- [{md}]({SITE}{md})\n" for md in docs))
