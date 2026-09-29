#!/usr/bin/env python3
"""Emit redirect stubs for links that chat apps truncate.

Messaging apps stop auto-linking at characters such as ' ( ) , and at
non-ASCII letters, so a shared link to
  .../george's-cheesecake-(sour-cream-topped-cheesecake)
arrives as .../george and 404s. For every page whose slug contains such a
character, write a small HTML page at each truncated prefix that forwards to
the full page (or lists the candidates when several pages share the prefix).

Usage: link_stubs.py <public_dir> <base_path>
"""
import html
import json
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

BREAKERS = set("'(),!")


def prefixes(slug):
    start = slug.rfind("/") + 1
    for i, ch in enumerate(slug):
        if ch in BREAKERS or ord(ch) > 127:
            if i > start:  # something left of the cut in the last segment
                yield slug[:i]
            elif i < start:  # cut inside a parent folder name
                seg_start = slug.rfind("/", 0, i) + 1
                if i > seg_start:
                    yield slug[:i]
    if slug.endswith(")"):
        yield slug[:-1]


def page(targets, titles, base):
    links = [(f"{base}/{quote(t)}", titles.get(t, t)) for t in targets]
    if len(links) == 1:
        url, title = links[0]
        head = (f'<meta http-equiv="refresh" content="0; url={html.escape(url)}">'
                f'<link rel="canonical" href="{html.escape(url)}">'
                f"<script>location.replace({json.dumps(url)})</script>")
        body = f'<p>Redirecting to <a href="{html.escape(url)}">{html.escape(title)}</a>.</p>'
    else:
        head = ""
        items = "".join(f'<li><a href="{html.escape(u)}">{html.escape(t)}</a></li>' for u, t in links)
        body = f"<p>That link was cut short. Did you mean:</p><ul>{items}</ul>"
    return ("<!doctype html><html><head><meta charset=\"utf-8\">"
            "<meta name=\"robots\" content=\"noindex\">"
            f"<title>Blanks' Restaurant</title>{head}</head><body>{body}</body></html>\n")


def main():
    public, base = Path(sys.argv[1]), sys.argv[2].rstrip("/")
    index = json.loads((public / "static" / "contentIndex.json").read_text(encoding="utf-8"))
    titles = {k: v.get("title", k) for k, v in index.items()}
    wanted = defaultdict(list)
    for slug in index:
        if slug.endswith("/index") or slug == "index":
            continue
        for p in set(prefixes(slug)):
            wanted[p].append(slug)
    written = 0
    for prefix, targets in sorted(wanted.items()):
        dest = public / (prefix + ".html")
        if prefix in index or dest.exists() or (public / prefix).is_dir():
            continue  # a real page or folder already lives there
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(page(sorted(targets), titles, base), encoding="utf-8")
        written += 1
    print(f"link_stubs: wrote {written} truncated-link stubs")


if __name__ == "__main__":
    main()
