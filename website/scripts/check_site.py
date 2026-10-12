#!/usr/bin/env python3
"""Check built pages, local links, images, search and editorial punctuation."""

import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]  # website/
SITE = ROOT / "site"
FORBIDDEN = set("\u2013\u2014\u2018\u2019\u201c\u201d\u2026\u2011")


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.path = path
        self.ids = set()
        self.links = []
        self.h1_count = 0
        self.errors = []
        self.feed(path.read_text())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "h1":
            self.h1_count += 1
        if tag == "img" and "alt" not in attrs:
            self.errors.append("Image has no alt attribute")
        for name in ("href", "src"):
            if attrs.get(name):
                self.links.append(attrs[name])


def main():
    errors = []
    files = sorted(SITE.rglob("*.html"))
    if not files:
        raise SystemExit("No built pages. Run mkdocs build --strict first.")
    pages = {p.resolve(): Page(p) for p in files}
    for path, page in pages.items():
        label = str(path.relative_to(SITE))
        errors.extend(f"{label}: {error}" for error in page.errors)
        if page.h1_count != 1:
            errors.append(f"{label}: expected one H1, found {page.h1_count}")
        for link in page.links:
            url = urlsplit(link)
            if url.scheme or url.netloc:
                continue
            if not url.path:
                target = path
            elif url.path.startswith("/"):
                target = SITE / unquote(url.path).lstrip("/")
            else:
                target = path.parent / unquote(url.path)
            target = target.resolve()
            if target.is_dir():
                target /= "index.html"
            if not target.is_relative_to(SITE):
                errors.append(f"{label}: link escapes site: {link}")
            elif not target.exists():
                errors.append(f"{label}: missing local target: {link}")
            elif url.fragment and target in pages and unquote(url.fragment) not in pages[target].ids:
                errors.append(f"{label}: missing anchor: {link}")

    search_path = SITE / "search/search_index.json"
    if not search_path.exists():
        errors.append("Missing search index")
    else:
        search = json.loads(search_path.read_text())
        indexed = {entry["location"].split("#")[0] for entry in search.get("docs", [])}
        for path in files:
            rel = path.relative_to(SITE).as_posix()
            if rel in {"index.html", "404.html"}:
                continue
            location = rel.removesuffix("index.html")
            if location not in indexed:
                errors.append(f"Page missing from search: {location}")

    authored = [ROOT / "mkdocs.yml", ROOT / "README.md"]
    authored += list((ROOT / "docs").rglob("*.md"))
    authored += list((ROOT / "overrides").rglob("*.html"))
    authored += list((ROOT / "docs/assets").rglob("*.js"))
    # Ignore punctuation inside vendored minified theme libraries. Check every
    # generated content page and the complete search index instead.
    for path in authored + files + [search_path]:
        if not path.exists():
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            found = FORBIDDEN.intersection(line)
            if found:
                codes = ", ".join(f"U+{ord(c):04X}" for c in sorted(found))
                errors.append(f"{path.relative_to(ROOT)}:{number}: prohibited punctuation {codes}")

    if errors:
        for error in errors[:80]:
            print(error)
        raise SystemExit(f"Site check failed: {len(errors)} issues")
    print(f"Passed: {len(files)} HTML pages; local links and anchors; image alt text; search coverage; editorial punctuation.")


if __name__ == "__main__":
    main()
