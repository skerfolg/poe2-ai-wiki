"""knowledge/ 정본 로드·검증 (KB_DATA_MODEL §9).

검증 실패 = 예외 (조용한 통과 금지). 검증 4층:
① envelope(record.schema.json) ② 타입별 data 스키마 ③ 조건 subject의 vocab 대조
④ 참조 무결성(relations.target·satisfiable_by가 실존 id)
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from pok.common.paths import knowledge_dir

_TYPE_SCHEMA = {
    "Skill": "skill.schema.json",
    "Support": "support.schema.json",
    "Passive": "passive.schema.json",
    "Resource": "resource.schema.json",
    "Mechanic": "mechanic.schema.json",  # v6 일반화 — 작동 규칙·공식·한도 (사용자 승인 2026-08-02)
    "Defence": "defence.schema.json",
    "Item": "item.schema.json",  # P1b ③ 유니크 + ④ 베이스
    "Modifier": "modifier.schema.json",  # P1b ④ 모드 풀 (RC4 근거)
    # 나머지 타입은 P1b에서 스키마 추가 시 등록
}


class KBValidationError(Exception):
    """KB 검증 실패 — 위반 전체 목록을 담는다 (첫 실패에서 멈추지 않음)."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        detail = "\n".join(f"- {e}" for e in errors)
        super().__init__(f"KB 검증 실패 ({len(errors)}건):\n{detail}")


@dataclass(frozen=True)
class Record:
    """정본 레코드 1건 (원본 dict 보존)."""

    id: str
    type: str
    path: Path
    raw: dict[str, Any] = field(repr=False)

    @property
    def name_ko(self) -> str:
        return str(self.raw["name"]["ko"])

    @property
    def name_en(self) -> str:
        return str(self.raw["name"]["en"])

    @property
    def tags(self) -> list[str]:
        return list(self.raw.get("tags", []))

    @property
    def relations(self) -> list[dict[str, Any]]:
        return list(self.raw.get("relations", []))

    @property
    def conditions(self) -> list[dict[str, Any]]:
        return list(self.raw.get("conditions", []))


@dataclass(frozen=True)
class Store:
    """로드·검증 완료된 KB 스냅샷."""

    records: dict[str, Record]
    subjects: dict[str, Any]

    def get(self, entity_id: str) -> Record:
        return self.records[entity_id]


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:  # 파일과 위치를 명시해 재수정 가능하게
        raise KBValidationError([f"{path}: JSON 파싱 실패 — {e}"]) from e


def _build_registry(schemas: dict[str, Any]) -> Registry:
    resources = [
        # vocab 데이터 파일엔 $schema가 없으므로 기본 스펙을 명시
        (name, Resource.from_contents(content, default_specification=DRAFT202012))
        for name, content in schemas.items()
    ]
    return Registry().with_resources(resources)


def _iter_exprs(expr: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """expr 트리를 순회하며 predicate만 낸다."""
    if "all" in expr or "any" in expr:
        for sub in expr.get("all", expr.get("any", [])):
            yield from _iter_exprs(sub)
    elif "not" in expr:
        yield from _iter_exprs(expr["not"])
    else:
        yield expr


def _condition_objects(record: Record) -> list[dict[str, Any]]:
    conds = record.conditions
    for edge in record.relations:
        if "condition" in edge:
            conds.append(edge["condition"])
    return conds


def load(root: Path | None = None) -> Store:
    """knowledge/ 전체를 로드하고 4층 검증을 수행한다. 위반 시 KBValidationError."""
    kdir = root if root is not None and root.name == "knowledge" else knowledge_dir(root)
    sdir = kdir / "schema"
    if not sdir.is_dir():
        raise FileNotFoundError(f"스키마 디렉터리 없음: {sdir}")

    schemas: dict[str, Any] = {}
    for p in sorted(sdir.rglob("*.json")):
        schemas[str(p.relative_to(sdir)).replace("\\", "/")] = _load_json(p)
    registry = _build_registry(schemas)
    envelope = Draft202012Validator(schemas["record.schema.json"], registry=registry)
    type_validators = {
        t: Draft202012Validator(schemas[f], registry=registry)
        for t, f in _TYPE_SCHEMA.items()
        if f in schemas
    }
    subjects: dict[str, Any] = schemas["vocab/condition-subjects.json"]["subjects"]

    # 개별 JSON(큐레이션) + NDJSON 샤드(벌크, KD-1) 모두 수집
    sources: list[tuple[Path, Any]] = []
    for p in sorted((kdir / "game-data").rglob("*.json")):
        sources.append((p, _load_json(p)))
    for p in sorted((kdir / "game-data").rglob("*.ndjson")):
        for line_no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                sources.append((p, json.loads(line)))
            except json.JSONDecodeError as e:
                raise KBValidationError([f"{p}:{line_no}: NDJSON 파싱 실패 — {e}"]) from e

    errors: list[str] = []
    records: dict[str, Record] = {}
    for p, raw in sources:
        rel = p.relative_to(kdir)

        env_errors = list(envelope.iter_errors(raw))
        if env_errors:
            errors.extend(
                f"{rel}: envelope — {e.message} (at {'/'.join(map(str, e.path))})"
                for e in env_errors
            )
            continue  # envelope 불합격 레코드는 이후 단계 제외
        rid, rtype = str(raw["id"]), str(raw["type"])

        tv = type_validators.get(rtype)
        if tv is not None:
            for err in tv.iter_errors(raw.get("data", {})):
                errors.append(f"{rel}: data[{rtype}] — {err.message}")

        if rid in records:
            errors.append(f"{rel}: 중복 id {rid} (기존: {records[rid].path.name})")
            continue
        records[rid] = Record(id=rid, type=rtype, path=p, raw=raw)

    # ③ 조건 subject vocab 대조 + op 허용 확인
    for r in records.values():
        for cond in _condition_objects(r):
            for pred in _iter_exprs(cond.get("expr", {})):
                subj, op = pred.get("subject"), pred.get("op")
                if subj not in subjects:
                    errors.append(f"{r.id}: 조건 subject '{subj}' — vocab에 없음")
                elif op not in subjects[subj]["ops"]:
                    allowed = subjects[subj]["ops"]
                    errors.append(f"{r.id}: subject '{subj}'에 op '{op}' 불허 (허용: {allowed})")

    # ④ 참조 무결성
    for r in records.values():
        for edge in r.relations:
            if edge["target"] not in records:
                errors.append(f"{r.id}: relations.target '{edge['target']}' — 실존하지 않는 id")
        for cond in _condition_objects(r):
            for sat in cond.get("satisfiable_by", []):
                if sat not in records:
                    errors.append(f"{r.id}: satisfiable_by '{sat}' — 실존하지 않는 id")

    if errors:
        raise KBValidationError(errors)
    return Store(records=records, subjects=subjects)
