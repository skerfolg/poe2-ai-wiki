"""Skill-owned source isolation: game data verification, never build recommendations."""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from bs4 import BeautifulSoup

WEB_REFERENCE = "web-reference"
POK_PRIMARY = "pok-primary"
BLOCKED_TYPES = frozenset({"Build", "UsageProfile"})
DROP = object()
PAGE_TYPES = frozenset(
    {"Item", "Skill", "Support", "Passive", "Modifier", "Mechanic", "Resource", "Defence"}
)
_NON_DATA = re.compile(
    r"Recommended|Supported (?:By|Gem)|Microtransactions|Unique Runeforging|"
    r"Economy|Community|Wiki|\bBuilds?\b|\bGuides?\b|Related|^From\s*/",
    re.I,
)

# This is an edit-operation contract, distinct from the record JSON schema (#222).
EDIT_OPERATIONS = {
    "upsert_decision": {"op": "upsert_decision", "value": "decision object from record schema"},
    "upsert_evidence": {"op": "upsert_evidence", "value": "evidence object from record schema"},
    "upsert_question": {"op": "upsert_question", "value": "question object from record schema"},
    "remove_decision": {"op": "remove_decision", "id": "existing decision ID"},
    "remove_evidence": {"op": "remove_evidence", "id": "existing evidence ID"},
    "remove_question": {"op": "remove_question", "id": "existing question ID"},
    "set_mechanism_summary": {"op": "set_mechanism_summary", "value": "summary text"},
    "merge_extensions": {"op": "merge_extensions", "value": {"extension_name": "object"}},
    "set_material": {"op": "set_material", "value": "captured material; stage4+ only"},
}


def data_url(record: dict[str, Any]) -> str:
    """Construct a data-page URL from an existing fact entity, not an agent URL."""
    if record.get("type") not in PAGE_TYPES:
        raise ValueError("No primary data-page route for this record type")
    name = str((record.get("name") or {}).get("en") or "").strip()
    slug = name.replace("'", "").replace("\u2019", "").replace(" ", "_")
    if not slug or not re.fullmatch(r"[\w.\-]+", slug, re.UNICODE) or slug.startswith("."):
        raise ValueError("Entity has no supported canonical data-page name")
    if re.search(r"(?:^|_)(?:builds?|guides?|profiles?|ladder|economy|wiki)(?:_|$)", slug, re.I):
        raise ValueError("Build/guide/profile pages are outside the verification surface")
    return "https://poe2db.tw/us/" + quote(slug, safe="_.-")


def check_url(url: str, expected_url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "poe2db.tw"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or url != expected_url
    ):
        raise ValueError(
            "Only the requested canonical PoE2DB data page is allowed; redirects denied"
        )


def extract_data(html: str) -> str:
    """Extract the entity pane, removing recommendations, related lists and wiki tabs."""
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one(".page-content")
    if content is None:
        raise ValueError("Unrecognised data-page layout; no unrestricted HTML fallback")
    tabs = content.select_one(".tab-content")
    if tabs:
        panes = tabs.find_all(class_="tab-pane", recursive=False)
        if not panes:
            raise ValueError("Unrecognised data tabs; refusing unrestricted content")
        for pane in panes[1:]:
            pane.decompose()
    for element in content.select("script,style,nav,header,footer,.nav,.breadcrumb,iframe,form"):
        element.decompose()
    for heading in list(content.select(".card-header")):
        if _NON_DATA.search(heading.get_text(" ", strip=True)):
            card = heading.find_parent(class_="card")
            if card:
                card.decompose()
            else:
                raise ValueError("Unrecognised recommendation section; refusing page")
    lines = [line.strip() for line in content.get_text("\n", strip=True).splitlines()]
    text = "\n".join(line for line in lines if line)
    if not text or len(text) > 120_000:
        raise ValueError("Data page is empty or exceeds the verification text bound")
    return text


def fetch_data(
    record: dict[str, Any],
    *,
    client: httpx.Client | None = None,
    patch_version: str | None = None,
) -> dict[str, Any]:
    if patch_version is not None:
        if record.get("type") not in PAGE_TYPES:
            raise ValueError("No primary verification route for this record type")
        if not re.fullmatch(r"\d+\.\d+\.\d+[a-z]?\d*", patch_version):
            raise ValueError("Expected a numeric game patch version, not a URL or guide")
        url = "https://poe2db.tw/us/Version_" + patch_version
    else:
        url = data_url(record)
    check_url(url, url)
    owned = client is None
    active = client or httpx.Client(timeout=httpx.Timeout(20, connect=10), follow_redirects=False)
    try:
        with active.stream(
            "GET", url, headers={"User-Agent": "PoK-mechanism-verification/1"}
        ) as response:
            check_url(str(response.url), url)
            response.raise_for_status()
            if "text/html" not in response.headers.get("content-type", ""):
                raise ValueError("Expected a game data HTML page")
            chunks = bytearray()
            for chunk in response.iter_bytes():
                chunks.extend(chunk)
                if len(chunks) > 2_000_000:
                    raise ValueError("Primary source exceeds response bound")
            html = bytes(chunks).decode("utf-8", errors="replace")
        text = extract_data(html)
        return {
            "url": url,
            "http_status": 200,
            "text": text,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "html_sha256": hashlib.sha256(chunks).hexdigest(),
            "purpose": "verify_preselected_mechanism_only",
            "instruction_authority": "none",
            "patch_version": patch_version,
        }
    finally:
        if owned:
            active.close()


def scrub_records(value: Any, blocked_ids: set[str]) -> Any:
    """Remove full build/corpus records from fact-query results before storage."""
    if isinstance(value, dict):
        if value.get("type") in BLOCKED_TYPES or any(
            isinstance(value.get(key), str) and value[key] in blocked_ids
            for key in (
                "id",
                "entity_id",
                "carrier_id",
                "source",
                "target",
                "source_id",
                "target_id",
                "from",
                "to",
            )
        ):
            return DROP
        return {
            k: cleaned
            for k, v in value.items()
            if (cleaned := scrub_records(v, blocked_ids)) is not DROP
        }
    if isinstance(value, list):
        return [
            cleaned for item in value if (cleaned := scrub_records(item, blocked_ids)) is not DROP
        ]
    if isinstance(value, str) and value in blocked_ids:
        return DROP
    return value
