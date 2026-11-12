"""Review 028c decision (g), offline: every feed parse goes through the guarded expat parser. A DOCTYPE, an internal,
an external and a parameter entity are refused in UTF-8 and in UTF-16 (with a BOM), directly and through the old
undeclared-entity repair path, while a benign feed parses to the same tree, and fails with the same messages, as the
stdlib ``ET.fromstring``."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import pytest

from projectzero.news import refresh, xmlsafe
from projectzero.news.xmlsafe import UnsafeXMLError

HOSTILE = {
    "doctype": "<!DOCTYPE rss><rss><channel><item><title>x</title></item></channel></rss>",
    "internal": '<!DOCTYPE rss [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;">]><rss><title>&b;</title></rss>',
    "external": '<!DOCTYPE rss [<!ENTITY e SYSTEM "file:///etc/hostname">]><rss><title>&e;</title></rss>',
    "external-dtd": '<!DOCTYPE rss SYSTEM "https://dtd.invented.example/rss.dtd"><rss></rss>',
    "parameter": "<!DOCTYPE rss [<!ENTITY % p \"<!ENTITY q 'x'>\"> %p;]><rss>&q;</rss>",
}
ENCODINGS = {
    "utf-8": lambda s: ('<?xml version="1.0" encoding="UTF-8"?>' + s).encode("utf-8"),
    "utf-16": lambda s: ('<?xml version="1.0" encoding="UTF-16"?>' + s).encode("utf-16"),  # BOM first
}


@pytest.mark.parametrize("enc", list(ENCODINGS))
@pytest.mark.parametrize("name", list(HOSTILE))
def test_declarations_are_refused_in_every_encoding(name: str, enc: str) -> None:
    data = ENCODINGS[enc](HOSTILE[name])
    if enc == "utf-16":
        assert data[:2] in (b"\xff\xfe", b"\xfe\xff")
    with pytest.raises(UnsafeXMLError, match="declarations are not accepted"):
        xmlsafe.fromstring(data)


@pytest.mark.parametrize("name", list(HOSTILE))
def test_the_repair_path_reparses_through_the_guard(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """``UnsafeXMLError`` is a ``ParseError``: the old repair branch runs and its second parse is guarded too."""
    calls: list[bytes] = []
    real = xmlsafe.fromstring

    def spy(data: bytes) -> ET.Element:
        calls.append(data)
        return real(data)

    monkeypatch.setattr(xmlsafe, "fromstring", spy)
    text = HOSTILE[name].replace("</rss>", "<x>&nbsp;&eacute;</x></rss>")  # an undeclared HTML entity as well
    with pytest.raises(UnsafeXMLError):
        xmlsafe.feed_root(text)
    assert len(calls) == 2  # the first parse, then the repaired text
    assert b"&nbsp;" in calls[0] and b"&nbsp;" not in calls[1]


def test_every_guard_handler_raises() -> None:
    parser = xmlsafe.guarded_parser(ET.TreeBuilder())
    for handler, args in (
        (parser.StartDoctypeDeclHandler, ("rss", None, None, 0)),
        (parser.EntityDeclHandler, ("a", 0, "x", None, None, None, None)),
        (parser.EntityDeclHandler, ("p", 1, "x", None, None, None, None)),  # a parameter entity
        (parser.UnparsedEntityDeclHandler, ("u", None, "x", None, "gif")),
        (parser.ExternalEntityRefHandler, ("e", None, "file:///etc/hostname", None)),
    ):
        with pytest.raises(UnsafeXMLError):
            handler(*args)


BENIGN = [
    b"<rss><channel><item><title>a &amp; b</title><link>https://x.invented.example/</link></item></channel></rss>",
    b"<feed xmlns='http://www.w3.org/2005/Atom'><entry><title>t</title><link href='h' rel='alternate'/></entry></feed>",
    "<?xml version='1.0' encoding='utf-16'?><rss><a>é &#233;</a></rss>".encode("utf-16"),
    b"<rss><![CDATA[<b>x</b>]]><!-- c --><?pi x?></rss>",
    b"<rss xmlns:dc='http://purl.org/dc/elements/1.1/'><dc:creator x:y='1' xmlns:x='u'>A</dc:creator></rss>",
    b"<rss><a>&nbsp;</a></rss>",
    b"<rss><a></rss>",
    b"garbage",
    b"",
    b"<rss/>junk",
]


def _parse(fn: Any, data: bytes) -> Any:
    try:
        return ET.tostring(fn(data))
    except ET.ParseError as exc:
        return ("ParseError", str(exc), exc.code, exc.position)


@pytest.mark.parametrize("data", BENIGN)
def test_a_benign_document_parses_as_the_stdlib_parsed_it(data: bytes) -> None:
    assert _parse(xmlsafe.fromstring, data) == _parse(ET.fromstring, data)


def test_the_old_repair_and_junk_cut_are_kept() -> None:
    feed = {"url": "https://tech.eu/feed/", "name": "Tech.eu"}
    xml = (
        "<rss><channel><item><title>Invented Dune&nbsp;Robotics caf&eacute; &bogus;</title>"
        "<link>https://tech.eu/x</link></item></channel></rss><script>junk</script>"
    )
    items = refresh.parse_feed(xml, feed)
    assert [i["headline"] for i in items] == ["Invented Dune Robotics café"]  # the old _strip folds the no-break space
    with pytest.raises(UnsafeXMLError):
        refresh.parse_feed(HOSTILE["internal"], feed)
