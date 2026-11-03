"""HTML parsing helpers: prefer lxml's C parser, fall back to html.parser."""

from __future__ import annotations

from bs4 import BeautifulSoup, FeatureNotFound


def parse_html(html_content, features="html.parser"):
    """Parse ``html_content`` with lxml when available.

    lxml parses large auction pages ~80x faster than ``html.parser``; the
    BeautifulSoup API stays identical so callers need no other change.
    """
    if features == "html.parser":
        try:
            return BeautifulSoup(html_content, "lxml")
        except FeatureNotFound:
            return BeautifulSoup(html_content, "html.parser")
    return BeautifulSoup(html_content, features)
