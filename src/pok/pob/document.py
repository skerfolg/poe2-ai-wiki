"""Explicit XML attribute edits preserving every byte outside the edited span.

Paths count element children from the document root, excluding comments/text.
This is structural editing, not skill interpretation or game validation.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from xml.parsers import expat

_NAME = re.compile(r"[A-Za-z_:][A-Za-z0-9_.:-]*\Z")
_ATTRIBUTE = re.compile(rb"""([^\s=<>/]+)\s*=\s*(["'])(.*?)\2""", re.S)


def xml_revision(xml: str) -> str:
    return "sha256:" + hashlib.sha256(xml.encode("utf-8")).hexdigest()


def xml_node_pointer(path: tuple[int, ...]) -> str:
    """Address element-only paths, independent of filtered inspection pages."""
    return "/nodes/" + (".".join(str(index) for index in path) if path else "root")


def select_xml_node(xml: str, pointer: str) -> str:
    """Select exact subtree bytes, never a native skill or active-set identity."""
    if not re.fullmatch(r"/nodes/(?:root|(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))*)", pointer):
        raise ValueError("Expected an XML node pointer /nodes/root or /nodes/0.1")
    nodes = inspect_xml(xml)
    for node in nodes:
        if xml_node_pointer(node.path) == pointer:
            return xml.encode("utf-8")[node.start : node.end].decode("utf-8")
    raise ValueError("XML node pointer does not exist")


@dataclass(frozen=True)
class XmlElement:
    path: tuple[int, ...]
    tag: str
    attributes: dict[str, str]
    raw_attributes: dict[str, str]
    start: int
    start_end: int
    end_start: int = 0
    end: int = 0


@dataclass(frozen=True)
class XmlEdit:
    xml: str
    parent_revision: str
    revision: str
    changed: bool


def inspect_xml(xml: str) -> tuple[XmlElement, ...]:
    raw = xml.encode("utf-8")
    parser = expat.ParserCreate("utf-8")
    stack: list[tuple[tuple[int, ...], int, int]] = []
    elements: list[XmlElement] = []

    def start(tag: str, attributes: dict[str, str]) -> None:
        if stack:
            parent, count, parent_index = stack[-1]
            path = (*parent, count)
            stack[-1] = (parent, count + 1, parent_index)
        else:
            path = ()
        position = parser.CurrentByteIndex
        end = position
        quote = 0
        while end < len(raw):
            byte = raw[end]
            if quote:
                if byte == quote:
                    quote = 0
            elif byte in (34, 39):
                quote = byte
            elif byte == 62:
                break
            end += 1
        if end == len(raw):
            raise ValueError("Unterminated XML start tag")
        raw_attributes = {
            match[1].decode("utf-8"): match[3].decode("utf-8")
            for match in _ATTRIBUTE.finditer(raw[position : end + 1])
        }
        elements.append(XmlElement(path, tag, dict(attributes), raw_attributes, position, end + 1))
        stack.append((path, 0, len(elements) - 1))

    def end(tag: str) -> None:
        _, _, index = stack.pop()
        node = elements[index]
        if raw[node.start : node.start_end].endswith(b"/>"):
            close_start, close_end = node.start_end - 2, node.start_end
        else:
            close_start = parser.CurrentByteIndex
            close_end = raw.find(b">", close_start) + 1
            if close_end == 0:
                raise ValueError("Unterminated XML closing tag")
        elements[index] = replace(node, end_start=close_start, end=close_end)

    def unsupported_doctype(*args: object) -> None:
        raise ValueError("DTD documents are outside the PoB XML edit format")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.StartDoctypeDeclHandler = unsupported_doctype
    try:
        parser.Parse(raw, True)
    except expat.ExpatError as exc:
        raise ValueError(f"Malformed XML: {exc}") from exc
    return tuple(elements)


def set_xml_attribute(
    xml: str,
    expected_revision: str,
    element_path: tuple[int, ...],
    attribute: str,
    expected_value: str | None,
    value: str,
) -> XmlEdit:
    """Compare a raw attribute token and encode value with named entities only.

    Do not conflate numeric entities with literal characters, or normalized XML
    attribute whitespace with the raw values consumed by the pinned PoB reader.
    """
    parent = xml_revision(xml)
    if parent != expected_revision:
        raise ValueError("XML revision conflict")
    if not _NAME.fullmatch(attribute):
        raise ValueError("Invalid XML attribute name")
    if any(type(index) is not int or index < 0 for index in element_path):
        raise ValueError("XML element path must contain nonnegative ordinals")
    selected = next((node for node in inspect_xml(xml) if node.path == element_path), None)
    if selected is None:
        raise ValueError("XML element path does not exist")
    if selected.raw_attributes.get(attribute) != expected_value:
        raise ValueError("XML attribute value conflict")
    raw = xml.encode("utf-8")
    tag = raw[selected.start : selected.start_end]
    matches = [match for match in _ATTRIBUTE.finditer(tag) if match[1].decode() == attribute]
    if len(matches) > 1:
        raise ValueError("Ambiguous XML attribute")
    quote = matches[0][2].decode() if matches else '"'
    encoded = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    encoded = encoded.replace(quote, "&quot;" if quote == '"' else "&apos;")
    if expected_value == encoded:
        return XmlEdit(xml, parent, parent, False)
    if matches:
        match = matches[0]
        begin, end = selected.start + match.start(3), selected.start + match.end(3)
        replacement = encoded.encode("utf-8")
    else:
        begin = selected.start_end - (2 if tag.endswith(b"/>") else 1)
        end = begin
        replacement = f' {attribute}="{encoded}"'.encode()
    changed = (raw[:begin] + replacement + raw[end:]).decode("utf-8")
    inspect_xml(changed)
    revision = xml_revision(changed)
    return XmlEdit(changed, parent, revision, revision != parent)


def set_xml_text(
    xml: str,
    expected_revision: str,
    element_path: tuple[int, ...],
    expected_value: str,
    value: str,
) -> XmlEdit:
    """Replace explicit leaf text while preserving every byte outside its body.

    Mixed elements/comments/processing instructions are not silently removed.
    A single exact CDATA body retains its representation; other text is escaped.
    """
    parent = xml_revision(xml)
    if parent != expected_revision:
        raise ValueError("XML revision conflict")
    if any(type(index) is not int or index < 0 for index in element_path):
        raise ValueError("XML element path must contain nonnegative ordinals")
    nodes = inspect_xml(xml)
    selected = next((node for node in nodes if node.path == element_path), None)
    if selected is None:
        raise ValueError("XML element path does not exist")
    if any(
        node.path[:-1] == element_path and len(node.path) == len(element_path) + 1 for node in nodes
    ):
        raise ValueError("Text edit requires a leaf XML element")
    raw = xml.encode("utf-8")
    start_tag = raw[selected.start : selected.start_end]
    self_closing = start_tag.endswith(b"/>")
    body = "" if self_closing else raw[selected.start_end : selected.end_start].decode("utf-8")
    if body != expected_value:
        raise ValueError("XML text value conflict")
    if "<" in re.sub(r"<!\[CDATA\[.*?\]\]>", "", body, flags=re.S):
        raise ValueError("Text edit cannot remove mixed XML markup")
    if body.startswith("<![CDATA[") and body.endswith("]]>") and body.count("]]>") == 1:
        replacement = "<![CDATA[" + value.replace("]]>", "]]]]><![CDATA[>") + "]]>"
    else:
        replacement = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if replacement == body:
        return XmlEdit(xml, parent, parent, False)
    if self_closing:
        changed = (
            raw[: selected.start_end - 2]
            + b">"
            + replacement.encode("utf-8")
            + f"</{selected.tag}>".encode()
            + raw[selected.start_end :]
        )
    else:
        changed = (
            raw[: selected.start_end] + replacement.encode("utf-8") + raw[selected.end_start :]
        )
    text = changed.decode("utf-8")
    inspect_xml(text)
    return XmlEdit(text, parent, xml_revision(text), True)


def upsert_xml_child_attribute(
    xml: str,
    expected_revision: str,
    parent_path: tuple[int, ...],
    child_tag: str,
    identity_attribute: str,
    identity_value: str,
    attribute: str,
    expected_value: str | None,
    value: str,
) -> XmlEdit:
    """Update one uniquely identified child or append it without rewriting siblings.

    Identity matching follows decoded XML attributes. Attribute comparison is
    against raw tokens, as in set_xml_attribute. This is not a native-mode check.
    """
    revision = xml_revision(xml)
    if revision != expected_revision:
        raise ValueError("XML revision conflict")
    if any(not _NAME.fullmatch(name) for name in (child_tag, identity_attribute, attribute)):
        raise ValueError("Invalid XML child/attribute name")
    if identity_attribute == attribute:
        raise ValueError("Child identity and edited attribute must differ")
    if any(type(index) is not int or index < 0 for index in parent_path):
        raise ValueError("XML element path must contain nonnegative ordinals")
    nodes = inspect_xml(xml)
    parent = next((node for node in nodes if node.path == parent_path), None)
    if parent is None:
        raise ValueError("XML parent path does not exist")
    matches = [
        node
        for node in nodes
        if node.path[:-1] == parent_path
        and len(node.path) == len(parent_path) + 1
        and node.tag == child_tag
        and node.attributes.get(identity_attribute) == identity_value
    ]
    if len(matches) > 1:
        raise ValueError("Ambiguous duplicate XML child identity")
    if matches:
        return set_xml_attribute(xml, revision, matches[0].path, attribute, expected_value, value)
    if expected_value is not None:
        raise ValueError("Expected XML child does not exist")

    def encode(value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    child = (
        f'<{child_tag} {identity_attribute}="{encode(identity_value)}" '
        f'{attribute}="{encode(value)}"/>'
    )
    raw = xml.encode("utf-8")
    if raw[parent.start : parent.start_end].endswith(b"/>"):
        changed = (
            raw[: parent.start_end - 2]
            + b">"
            + child.encode()
            + f"</{parent.tag}>".encode()
            + raw[parent.start_end :]
        )
    else:
        changed = raw[: parent.end_start] + child.encode() + raw[parent.end_start :]
    text = changed.decode("utf-8")
    inspect_xml(text)
    return XmlEdit(text, revision, xml_revision(text), True)
