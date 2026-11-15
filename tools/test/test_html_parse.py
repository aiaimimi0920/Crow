"""Lazy HTML parsing keeps parser selection and failure semantics."""

import pytest

from src.html_parse import parse_html


def test_parser_prefers_lxml_and_falls_back_only_when_unavailable(monkeypatch):
    import bs4

    calls = []
    real_parser = bs4.BeautifulSoup

    def without_lxml(content, features):
        calls.append(features)
        if features == "lxml":
            raise bs4.FeatureNotFound("lxml unavailable")
        return real_parser(content, features)

    monkeypatch.setattr(bs4, "BeautifulSoup", without_lxml)
    assert parse_html("<p>ready</p>").get_text() == "ready"
    assert calls == ["lxml", "html.parser"]


def test_explicit_parser_is_not_replaced(monkeypatch):
    import bs4

    calls = []
    sentinel = object()
    monkeypatch.setattr(
        bs4,
        "BeautifulSoup",
        lambda content, features: calls.append(features) or sentinel,
    )
    assert parse_html("<p>ready</p>", "xml") is sentinel
    assert calls == ["xml"]


def test_unexpected_parser_failure_is_not_hidden(monkeypatch):
    import bs4

    def broken(*args):
        raise RuntimeError("parser failure")

    monkeypatch.setattr(bs4, "BeautifulSoup", broken)
    with pytest.raises(RuntimeError, match="parser failure"):
        parse_html("<p>ready</p>")
