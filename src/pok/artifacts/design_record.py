"""Versioned design data/rendering, without game decisions or runtime persistence.

Sealed records travel as JSON text or immutable references. Re-serializing a
parsed JavaScript object can change numbers and is not an identity operation.
This module checks data integrity, never whether evidence or a build is true.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from collections import OrderedDict
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
from threading import RLock
from typing import Any

from jsonschema import Draft202012Validator

FORMAT = "pok.design-record.v1"
RENDER_VERSION = 1
_VALIDATION_MEMO: OrderedDict[tuple[str, str], None] = OrderedDict()
_VALIDATION_MEMO_LOCK = RLock()
_MEMO_VALIDATOR: Draft202012Validator | None = None
_VALIDATION_MEMO_LIMIT = 128


class DesignRecordError(ValueError):
    """A machine-readable integrity/shape failure; the caller retains the raw input."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(
        files("pok.artifacts").joinpath("design_record.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(value)
    return value


def record_schema() -> dict[str, Any]:
    """Return a detached schema: a caller cannot modify the process validator."""
    return deepcopy(_schema())


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(_schema())


def _json_values(value: Any) -> None:
    if value is None or type(value) in (str, int, bool):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise DesignRecordError("INVALID_RECORD_JSON", "Non-finite numbers are not JSON")
        return
    if isinstance(value, list):
        for item in value:
            _json_values(item)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _json_values(item)
        return
    raise DesignRecordError("INVALID_RECORD_JSON", "Expected JSON values and string object keys")


def canonical_bytes(value: Any) -> bytes:
    """The v1 backend encoding; not the encoding/hash contract of tool_results."""
    try:
        _json_values(value)
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (UnicodeError, RecursionError) as exc:
        raise DesignRecordError("INVALID_RECORD_JSON", "Unsupported JSON text/depth") from exc


def record_revision(record: dict[str, Any]) -> str:
    payload = {key: value for key, value in record.items() if key != "revision"}
    return "sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _validate(record: dict[str, Any]) -> None:
    global _MEMO_VALIDATOR
    raw = canonical_bytes(record)
    if record.get("format") != FORMAT:
        raise DesignRecordError("UNSUPPORTED_RECORD_FORMAT", "Unsupported design record format")
    validator = _validator()
    # Only successful, exact content/schema pairs are memoized. No mutable
    # record references or caller-supplied revisions act as cache identities.
    key = None
    if type(validator) is Draft202012Validator:
        key = (
            hashlib.sha256(canonical_bytes(validator.schema)).hexdigest(),
            hashlib.sha256(raw).hexdigest(),
        )
        with _VALIDATION_MEMO_LOCK:
            if _MEMO_VALIDATOR is not validator:
                _VALIDATION_MEMO.clear()
                _MEMO_VALIDATOR = validator
            if key in _VALIDATION_MEMO:
                _VALIDATION_MEMO.move_to_end(key)
                return
    error = next(validator.iter_errors(record), None)
    if error is not None:
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        raise DesignRecordError("INVALID_RECORD_SHAPE", f"{path}: {error.message[:400]}")
    for section in ("decisions", "evidence", "questions"):
        seen: set[str] = set()
        for entry in record[section]:
            if entry["id"] in seen:
                raise DesignRecordError("DUPLICATE_ID", f"Duplicate ID in {section}: {entry['id']}")
            seen.add(entry["id"])
    for decision in record["decisions"]:
        ids = [provider["id"] for provider in decision["providers"]]
        if len(ids) != len(set(ids)):
            raise DesignRecordError("DUPLICATE_ID", f"Duplicate provider in {decision['id']}")
    if key is not None:
        with _VALIDATION_MEMO_LOCK:
            if _MEMO_VALIDATOR is validator:
                _VALIDATION_MEMO[key] = None
                while len(_VALIDATION_MEMO) > _VALIDATION_MEMO_LIMIT:
                    _VALIDATION_MEMO.popitem(last=False)


def seal_record(payload: dict[str, Any]) -> dict[str, Any]:
    """Seal trusted constructor/mutation output; not a public proof/authorization API."""
    value = deepcopy(payload)
    value["revision"] = record_revision(value)
    _validate(value)
    return value


def create_record(design_id: str, goal: str) -> dict[str, Any]:
    return seal_record(
        {
            "format": FORMAT,
            "design_id": design_id,
            "parents": [],
            "goal": {"summary": goal},
            "mechanism_summary": "",
            "decisions": [],
            "evidence": [],
            "questions": [],
            "material": None,
            "legacy_sources": [],
            "extensions": {},
        }
    )


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DesignRecordError("DUPLICATE_JSON_KEY", "Duplicate JSON object key")
        result[key] = value
    return result


def _constant(value: str) -> Any:
    raise DesignRecordError("INVALID_RECORD_JSON", f"Non-JSON constant: {value}")


def parse_json_data(text: str) -> Any:
    """Strict finite JSON for stored projections, without silent member replacement."""
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise DesignRecordError("INVALID_RECORD_JSON", "Malformed JSON data") from exc
    canonical_bytes(value)
    return value


def parse_record(record_json: str) -> dict[str, Any]:
    value = parse_json_data(record_json)
    if not isinstance(value, dict):
        raise DesignRecordError("INVALID_RECORD_SHAPE", "Design record must be an object")
    _validate(value)
    if value["revision"] != record_revision(value):
        raise DesignRecordError("REVISION_MISMATCH", "Record content does not match its revision")
    return value


def record_json(record: dict[str, Any]) -> str:
    _validate(record)
    if record["revision"] != record_revision(record):
        raise DesignRecordError("REVISION_MISMATCH", "Refusing to serialize unsealed changes")
    return canonical_bytes(record).decode("utf-8") + "\n"


_ROLES = {
    "user_fixed": "사용자 고정",
    "mechanism_required": "메커니즘 필수 조건",
    "provisional": "잠정 구현",
    "power_candidate": "성능 후보",
}


def _text(value: Any) -> str:
    text = html.escape(str(value), quote=False)
    text = re.sub(r"([\\`*_{}\[\]()#+!|])", r"\\\1", text)
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def render_record(record_text: str) -> str:
    """Stable record view. Beliefs/refs are not rendered as verified game facts."""
    record = parse_record(record_text)
    lines = [
        "# 빌드 설계 기록",
        "",
        f"- 설계 ID: `{record['design_id']}`",
        f"- 리비전: `{record['revision']}`",
        f"- 형식: `{FORMAT}` / 렌더 {RENDER_VERSION}",
        "",
        "## 목표",
        "",
        _text(record["goal"]["summary"]),
        "",
        "## 메커니즘",
        "",
        _text(record.get("mechanism_summary") or "미정"),
        "",
        "## 결정과 현재 공급자",
        "",
        "채택·신뢰도는 기록한 판단이다. 실제 근거 검증 결과와 구분한다.",
        "",
        "| ID | 역할 / 영역 | 상태 / 판단 | 조건과 범위 | 현재 공급자 | 재검토 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for decision in record["decisions"]:
        scope = decision["condition"]["scope"]["description"]
        providers = "; ".join(provider["label"] for provider in decision["providers"]) or "미정"
        review = decision.get("review", {}).get("state", "unknown")
        cells = [
            decision["id"],
            _ROLES[decision["role"]] + " / " + ", ".join(decision["domains"]),
            f"{decision['adoption']} / {decision['belief']} / {decision['confidence']}",
            decision["condition"]["statement"] + " / " + scope,
            providers,
            review,
        ]
        lines.append("| " + " | ".join(_text(cell) for cell in cells) + " |")
    lines += ["", "## 선택 이유·대가·의존", ""]
    for decision in record["decisions"]:
        lines += [f"### {_text(decision['id'])}: {_text(decision['title'])}", ""]
        lines.append(_text(decision.get("rationale") or "이유 미기록"))
        for cost in decision["costs"]:
            amount = "미측정" if cost["amount"] is None else str(cost["amount"])
            lines.append(
                f"- 비용: {_text(cost['resource'])} {amount} {_text(cost['unit'])}"
                f" / {_text(cost['note'])}"
            )
        lines.append("- 의존: " + _text(", ".join(decision["depends_on"]) or "없음"))
        lines.append("- 대안: " + _text(", ".join(decision["alternatives"]) or "미기록"))
        lines.append("- 근거 ID: " + _text(", ".join(decision["evidence_ids"]) or "미기록"))
        lines.extend("- 한계: " + _text(value) for value in decision.get("limitations", []))
        lines.append("")
    lines += ["## 근거와 범위", "", "참조가 있다는 사실은 근거 검증 성공을 뜻하지 않는다.", ""]
    for evidence in record["evidence"]:
        lines.append(
            f"- {_text(evidence['id'])}: {_text(evidence['label'])}"
            f" / {evidence['kind']} / {evidence['scope']['usage']}"
        )
        lines.append("  - 범위: " + _text(evidence["scope"]["description"]))
        lines.append(
            "  - 출처: " + _text(json.dumps(evidence["source"], ensure_ascii=False, sort_keys=True))
        )
    lines += ["", "## 열린 질문과 판정 방법", ""]
    for question in record["questions"]:
        lines.append(
            f"- {_text(question['id'])} [{question['state']} / {question['owner']}]:"
            f" {_text(question['claim'])}"
        )
        lines.append("  - 판정: " + _text(question["criterion"]))
    lines += ["", "## 실물·원문·확장", ""]
    lines.append(
        "실물 미연결"
        if record["material"] is None
        else "실물 리비전: " + record["material"]["revision"]
    )
    for source in record["legacy_sources"]:
        lines.append(
            f"- 원문: {_text(source['artifact_id'])}/{_text(source['name'])} / {source['sha256']}"
        )
    if record.get("extensions"):
        lines += [
            "",
            "```json",
            json.dumps(record["extensions"], ensure_ascii=False, sort_keys=True, indent=2),
            "```",
        ]
    return "\n".join(lines) + "\n"
