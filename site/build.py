"""Render README.md and API.md into a two-page local site."""
import os
import re
import shutil
import sys


PAGES = (
    ("README.md", "index.html", "guide", "Guide"),
    ("docs/tutorial.md", "tutorial.html", "tutorial", "Tutorial"),
    ("docs/concepts.md", "concepts.html", "concepts", "Concepts"),
    ("docs/mesh.md", "mesh.html", "mesh", "Mesh"),
    ("docs/troubleshooting.md", "troubleshooting.html", "troubleshooting", "Troubleshoot"),
    ("docs/pipeline.md", "pipeline.html", "pipeline", "Pipeline"),
    ("API.md", "api.html", "api", "API"),
)

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@TITLE@@</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<header>
<a class="brand" href="index.html">External-flow CFD</a>
<nav>
@@NAV@@
</nav>
</header>
<div class="layout">
<nav class="toc">
<p class="toc-label">Contents</p>
@@TOC@@
</nav>
<main>
@@BODY@@
</main>
</div>
</body>
</html>
"""


def die(msg):
    print("ERROR: %s" % msg, file=sys.stderr)
    raise SystemExit(1)


def esc(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def plain_text(text):
    """Visible heading text, with Markdown markers removed."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "`":
            j = text.find("`", i + 1)
            if j < 0:
                out.append(text[i:])
                break
            out.append(text[i + 1:j])
            i = j + 1
            continue
        if text.startswith("**", i):
            j = text.find("**", i + 2)
            if j < 0:
                out.append(text[i:])
                break
            out.append(plain_text(text[i + 2:j]))
            i = j + 2
            continue
        if text[i] == "[":
            match = re.match(r"\[([^\]]*)\]\([^)]*\)", text[i:])
            if match:
                out.append(plain_text(match.group(1)))
                i += match.end()
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def slugify(text):
    """GitHub-style heading id: lowercase, punctuation dropped, spaces to hyphens."""
    out = []
    for ch in plain_text(text).lower():
        if ch.isalnum() or ch in "-_":
            out.append(ch)
        elif ch.isspace():
            out.append("-")
    return "".join(out).strip("-")


def unique_slug(text, seen):
    base = slugify(text) or "section"
    slug = base
    n = 1
    while slug in seen:
        slug = "%s-%d" % (base, n)
        n += 1
    seen.add(slug)
    return slug


def page_targets():
    return {src: dest for src, dest, _key, _label in PAGES}


def classify_href(url, source="README.md"):
    """Return ('link', href) or ('code', path).

    Markdown page names become site pages. config/ and cfd/ stay visible as
    paths because the server only exposes the site folder.
    """
    if url.startswith("#"):
        return "link", url
    base, sep, frag = url.partition("#")
    if not base:
        return "link", url
    source_dir = os.path.dirname(source)
    norm = os.path.normpath(os.path.join(source_dir, base)).replace(os.sep, "/")
    while norm.startswith("./"):
        norm = norm[2:]
    pages = page_targets()
    if norm in pages:
        href = pages[norm]
        if sep:
            href += "#" + frag
        return "link", href
    if norm.startswith("config/") or norm.startswith("cfd/"):
        return "code", norm
    return "link", url


def render_link(text, url, source="README.md"):
    kind, href = classify_href(url, source)
    if kind == "code":
        return "<code>%s</code>" % esc(href)
    return '<a href="%s">%s</a>' % (esc(href), render_inline(text, source))


def render_inline(text, source="README.md"):
    parts = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "`":
            j = text.find("`", i + 1)
            if j < 0:
                parts.append(esc(text[i:]))
                break
            parts.append("<code>%s</code>" % esc(text[i + 1:j]))
            i = j + 1
            continue
        if text.startswith("**", i):
            j = text.find("**", i + 2)
            if j < 0:
                parts.append(esc(text[i:]))
                break
            parts.append("<strong>%s</strong>" % render_inline(text[i + 2:j], source))
            i = j + 2
            continue
        if text[i] == "[":
            match = re.match(r"\[([^\]]*)\]\(([^)]*)\)", text[i:])
            if match:
                parts.append(render_link(match.group(1), match.group(2), source))
                i += match.end()
                continue
        j = i + 1
        while j < n and text[j] not in "`[" and not text.startswith("**", j):
            j += 1
        parts.append(esc(text[i:j]))
        i = j
    return "".join(parts)


def fragments_in(line):
    """Same-page #anchors on one line, ignoring inline code."""
    found = []
    i = 0
    while i < len(line):
        if line[i] == "`":
            j = line.find("`", i + 1)
            if j < 0:
                break
            i = j + 1
            continue
        if line[i] == "[":
            match = re.match(r"\[[^\]]*\]\(([^)]+)\)", line[i:])
            if match:
                url = match.group(1)
                if url.startswith("#") and len(url) > 1:
                    found.append(url[1:])
                i += match.end()
                continue
        i += 1
    return found


def clean_heading(text):
    return text.strip().rstrip("#").strip()


def heading_plan(lines):
    """Slugs in document order, plus alias ids for prefixes the docs already use."""
    raws = []
    frags = []
    fence = False
    for line in lines:
        if line.startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match:
            raws.append(clean_heading(match.group(2)))
            continue
        frags.extend(fragments_in(line))
    seen = set()
    slugs = [unique_slug(raw, seen) for raw in raws]
    aliases = {}
    for frag in frags:
        if frag in seen:
            continue
        matches = [slug for slug in slugs if slug.startswith(frag + "-")]
        if len(matches) == 1:
            aliases[matches[0]] = frag
            seen.add(frag)
    return slugs, aliases


def list_marker(line):
    match = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
    if not match:
        return None
    return len(match.group(1)), match.group(2), match.group(3)


def split_row(line):
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    cells = []
    buf = []
    code = False
    for ch in text:
        if ch == "`":
            code = not code
        if ch == "|" and not code:
            cells.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    cells.append("".join(buf).strip())
    return cells


def is_separator(line):
    if not line.lstrip().startswith("|"):
        return False
    cells = split_row(line)
    if not cells:
        return False
    return all(re.match(r"^:?-+:?$", cell) for cell in cells)


def is_table_start(lines, index):
    if index + 1 >= len(lines):
        return False
    if not lines[index].lstrip().startswith("|"):
        return False
    return is_separator(lines[index + 1])


def read_fence(lines, index):
    index += 1
    buf = []
    while index < len(lines) and not lines[index].startswith("```"):
        buf.append(lines[index])
        index += 1
    if index >= len(lines):
        die("unclosed code fence")
    index += 1
    return "<pre><code>%s</code></pre>" % esc("\n".join(buf)), index


def read_table(lines, index, source="README.md"):
    header = split_row(lines[index])
    index += 2
    rows = []
    while index < len(lines) and lines[index].strip() and lines[index].lstrip().startswith("|"):
        if is_separator(lines[index]):
            break
        rows.append(split_row(lines[index]))
        index += 1
    parts = ['<div class="table-wrap"><table><thead><tr>']
    for cell in header:
        parts.append("<th>%s</th>" % render_inline(cell, source))
    parts.append("</tr></thead><tbody>")
    for row in rows:
        parts.append("<tr>")
        for cell in row:
            parts.append("<td>%s</td>" % render_inline(cell, source))
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts), index


def read_list(lines, index, indent, source="README.md"):
    items = []
    kind = None
    while index < len(lines):
        if lines[index].strip() == "":
            break
        marker = list_marker(lines[index])
        if not marker:
            break
        spaces, bullet, text = marker
        if spaces != indent:
            break
        this = "ol" if bullet[0].isdigit() else "ul"
        if kind is None:
            kind = this
        elif this != kind:
            break
        index += 1
        child = ""
        if index < len(lines):
            nxt = list_marker(lines[index])
            if nxt and nxt[0] > spaces:
                child, index = read_list(lines, index, nxt[0], source)
        number = int(bullet[:-1]) if this == "ol" else None
        items.append((text, child, number))
    if not items:
        die("list parser made no items")
    attrs = ""
    if kind == "ol" and items[0][2] not in (None, 1):
        attrs = ' start="%d"' % items[0][2]
    parts = ["<%s%s>" % (kind, attrs)]
    for text, child, _number in items:
        inner = render_inline(text, source)
        if child:
            inner += "\n" + child
        parts.append("<li>%s</li>" % inner)
    parts.append("</%s>" % kind)
    return "\n".join(parts), index


def block_start(lines, index):
    line = lines[index]
    if line.startswith("```"):
        return True
    if line.startswith("#"):
        return True
    if is_table_start(lines, index):
        return True
    marker = list_marker(line)
    return marker is not None and marker[0] == 0


def render_document(markdown, source="README.md"):
    """Return (body_html, toc, title). toc entries are (level, id, inner_html)."""
    lines = markdown.splitlines()
    slugs, aliases = heading_plan(lines)
    slug_at = 0
    title = "External-flow CFD"
    toc = []
    blocks = []
    index = 0
    n = len(lines)
    while index < n:
        line = lines[index]
        if line.strip() == "":
            index += 1
            continue
        if line.startswith("```"):
            block, index = read_fence(lines, index)
            blocks.append(block)
            continue
        if is_table_start(lines, index):
            block, index = read_table(lines, index, source)
            blocks.append(block)
            continue
        marker = list_marker(line)
        if marker and marker[0] == 0:
            block, index = read_list(lines, index, 0, source)
            blocks.append(block)
            continue
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match:
            level = len(match.group(1))
            raw = clean_heading(match.group(2))
            if slug_at >= len(slugs):
                die("heading slug mismatch")
            sid = slugs[slug_at]
            slug_at += 1
            inner = render_inline(raw, source)
            extra = ""
            if sid in aliases:
                extra = '<span id="%s"></span>' % esc(aliases[sid])
            blocks.append('<h%d id="%s">%s%s</h%d>' % (level, esc(sid), extra, inner, level))
            if level == 1 and title == "External-flow CFD":
                title = plain_text(raw) or title
            if level in (2, 3):
                toc.append((level, sid, inner))
            index += 1
            continue
        para = [line.strip()]
        index += 1
        while index < n and lines[index].strip() and not block_start(lines, index):
            para.append(lines[index].strip())
            index += 1
        blocks.append("<p>%s</p>" % render_inline(" ".join(para), source))
    if slug_at != len(slugs):
        die("heading slug mismatch")
    return "\n".join(blocks), toc, title


def toc_html(toc):
    lines = []
    for level, sid, inner in toc:
        cls = ' class="sub"' if level == 3 else ""
        lines.append('<a%s href="#%s">%s</a>' % (cls, esc(sid), inner))
    return "\n".join(lines)


def nav_html(active):
    parts = []
    for _src, dest, key, label in PAGES:
        cls = ' class="active"' if key == active else ""
        parts.append('<a href="%s"%s>%s</a>' % (esc(dest), cls, esc(label)))
    return "\n".join(parts)


def page_html(markdown, active, source="README.md"):
    body, toc, title = render_document(markdown, source)
    html = TEMPLATE
    html = html.replace("@@TITLE@@", esc(title))
    html = html.replace("@@NAV@@", nav_html(active))
    html = html.replace("@@TOC@@", toc_html(toc))
    html = html.replace("@@BODY@@", body)
    return html


def build(root):
    out = os.path.join(root, "site", "out")
    os.makedirs(out)
    css = os.path.join(root, "site", "style.css")
    if not os.path.isfile(css):
        die("missing %s" % css)
    shutil.copyfile(css, os.path.join(out, "style.css"))
    for src, dest, active in ((item[0], item[1], item[2]) for item in PAGES):
        path = os.path.join(root, src)
        if not os.path.isfile(path):
            die("missing %s" % path)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        with open(os.path.join(out, dest), "w", encoding="utf-8") as handle:
            handle.write(page_html(text, active, src))
    return out


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "site", "out")
    if os.path.isdir(out):
        shutil.rmtree(out)
    build(root)
    print("wrote site/out")


if __name__ == "__main__":
    main()
