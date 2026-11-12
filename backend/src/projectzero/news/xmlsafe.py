"""Untrusted feed XML, parsed behind a guard (review 028c decision (g), Codex H-256 / plan revision 2).

The old ``_fetch_feed`` parsed every feed with the stdlib ``ET.fromstring``, which accepts a DOCTYPE and its entity
declarations (the "billion laughs" expansion). Here every parse, the old repair of undeclared HTML entities included,
goes through ONE guarded parser built on expat:

* ``StartDoctypeDeclHandler``, ``EntityDeclHandler`` (general AND parameter entities) and ``ExternalEntityRefHandler``
  raise ``UnsafeXMLError``, so a document is refused at its declaration, before anything is expanded;
* parameter-entity parsing is off (``XML_PARAM_ENTITY_PARSING_NEVER``);
* expat decodes the bytes itself (a BOM, a declared encoding), so the guard holds for every encoding it accepts
  (UTF-8, UTF-16 with a BOM, declared encodings).

The tree is the one ``ET.fromstring`` built: ``ET.TreeBuilder`` elements, names as ``{namespace}local`` (expat's
namespace processing with ``}`` as separator, as the stdlib ``XMLParser`` does), comments and processing
instructions dropped, character data buffered. A well-formedness error is the stdlib ``ET.ParseError`` with the same
message (``<expat error>: line L, column C``), ``code`` and ``position``. ``UnsafeXMLError`` is a ``ParseError`` on
purpose: the old repair path (``feed_root``: ``except ET.ParseError`` -> repair -> parse again) re-parses a refused
document through the same guard, which refuses it again, so the feed fails with the guard's reason.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from typing import Any
from xml.parsers import expat


class UnsafeXMLError(ET.ParseError):
    """The document declares a DOCTYPE or an entity (refused before anything is expanded)."""


def _refuse(what: str) -> Any:
    def handler(*_args: Any) -> Any:
        raise UnsafeXMLError(f"refused feed XML: {what} declarations are not accepted")

    return handler


def _fixname(name: str) -> str:
    # expat's namespace processing gives "uri}local"; the stdlib XMLParser names it "{uri}local"
    return "{" + name if "}" in name else name


def guarded_parser(builder: ET.TreeBuilder) -> Any:
    """An expat parser feeding ``builder`` with the guard installed (module docstring)."""
    parser = expat.ParserCreate(None, "}")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = _refuse("DOCTYPE")
    parser.EntityDeclHandler = _refuse("ENTITY")
    parser.UnparsedEntityDeclHandler = _refuse("ENTITY")
    parser.ExternalEntityRefHandler = _refuse("external entity")
    parser.buffer_text = True

    def start(name: str, attrs: dict[str, str]) -> None:
        builder.start(_fixname(name), {_fixname(k): v for k, v in attrs.items()})

    def end(name: str) -> None:
        builder.end(_fixname(name))

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = builder.data
    return parser


def fromstring(data: bytes) -> ET.Element:
    """``ET.fromstring(data)`` behind the guard (module docstring). Raises ``ET.ParseError`` (``UnsafeXMLError`` for a
    DOCTYPE / entity declaration)."""
    builder = ET.TreeBuilder()
    parser = guarded_parser(builder)
    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        err = ET.ParseError(str(exc))
        err.code = exc.code
        err.position = (exc.lineno, exc.offset)
        raise err from None
    root = builder.close()
    return root


# the old repair: HTML entities (&nbsp; &eacute; ...) are undeclared in XML and would kill the whole feed
_HTML_ENTITY = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)([A-Za-z][A-Za-z0-9]{1,10});")


def repair_entities(xml: str) -> str:
    """The old undeclared-entity repair, verbatim: a known HTML entity becomes its (XML-escaped) character, an unknown
    one is dropped."""
    return _HTML_ENTITY.sub(
        lambda m: (
            html.escape(html.unescape(m.group(0)), quote=False) if html.unescape(m.group(0)) != m.group(0) else ""
        ),
        xml,
    )


def feed_root(xml: str) -> ET.Element:
    """The old ``_fetch_feed`` parse of the (junk-trimmed) feed text: parse; on a ``ParseError``, repair the undeclared
    HTML entities and parse again. BOTH parses are guarded."""
    try:
        return fromstring(xml.encode("utf-8", errors="replace"))
    except ET.ParseError:
        fixed = repair_entities(xml)
        return fromstring(fixed.encode("utf-8", errors="replace"))
