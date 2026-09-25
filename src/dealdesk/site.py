"""Serve the web app as a complete HTML document.

`web/index.html` is written as a page fragment (title, styles, markup, scripts) so the same file can be
published as a claude.ai artifact, which adds its own document skeleton. The API and the GitHub Pages
build wrap it here with the doctype, charset, viewport and base reset a standalone page needs.
"""

from __future__ import annotations

from pathlib import Path

WEB_DIR = Path(__file__).with_name("web")
BODY_START = '<div class="wrap">'

_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>
"""


def index_html() -> str:
    fragment = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    i = fragment.index(BODY_START)
    return f"{_HEAD}{fragment[:i]}</head>\n<body>\n{fragment[i:]}</body>\n</html>\n"
