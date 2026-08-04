"""knowledge/ 정본 **접근**(로드·검증·쓰기) — KB_DATA_MODEL §9.

읽기 — 검증 실패 = 예외 (조용한 통과 금지). 검증 4층:
① envelope(record.schema.json) ② 타입별 data 스키마 ③ 조건 subject의 vocab 대조
④ 참조 무결성(relations.target·satisfiable_by가 실존 id)

쓰기 — **정본에 쓰는 경로는 여기 하나뿐이다** (B-6, 사용자 합의 2026-08-03).
쓰기 계약이 없던 시절엔 ingest 모듈들이 각자 `knowledge/`에 쓰면서 KD-1 배치 규칙
(개별 JSON이냐 NDJSON 샤드냐)을 매번 재추론했고, 한 곳만 빠뜨려도 샤드가 통째로
파괴됐다(실측 2026-08-02 830건·2026-08-03 884건). 배치 판단을 여기 가두고,
모든 쓰기에 안전장치 3종을 강제한다:
  ① 쓰기 후 자동 재검증 — 깨진 상태가 커밋으로 넘어가지 않는다
  ② 레코드 감소 시 예외 — 명시적 삭제 근거(`allow_delete`) 없이는 줄지 않는다
  ③ 원자적 쓰기 — 중단돼도 기존 파일이 반토막 나지 않는다
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Iterator, Mapping
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


class KBWriteError(Exception):
    """정본 쓰기 거부 — 데이터가 줄거나 계약을 어긴 경우 (파일은 그대로)."""


@dataclass(frozen=True)
class WriteReport:
    """쓰기 결과 요약 — 호출자가 로그·검증에 쓴다."""

    path: Path
    added: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        return f"{self.path.name}: +{len(self.added)} ~{len(self.updated)} -{len(self.removed)}"


@dataclass(frozen=True)
class Record:
    """정본 레코드 1건 (원본 dict 보존)."""

    id: str
    type: str
    path: Path
    raw: dict[str, Any] = field(repr=False)

    @property
    def in_shard(self) -> bool:
        """NDJSON 벌크 샤드 소속인가 (KD-1). 개별 큐레이션 JSON 시드면 False.

        `path`는 샤드일 때 **파일 전체**를 가리키므로 이 레코드 하나만 그 경로에
        덮어쓰면 샤드가 통째로 날아간다 — 갱신 경로를 가르는 판별자다.
        """
        return self.path.suffix == ".ndjson"

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


# ── 쓰기 (B-6: 정본 쓰기 단일 경로) ────────────────────────────────


def _atomic_write(path: Path, text: str) -> None:
    """임시 파일에 쓰고 교체 — 중단돼도 기존 파일이 반토막 나지 않는다(안전장치 ③)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _dump_shard(records: Iterable[dict[str, Any]]) -> str:
    """NDJSON 직렬화 — id 정렬로 diff를 안정시킨다 (KD-1 벌크 배치)."""
    ordered = sorted(records, key=lambda r: str(r["id"]))
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ordered)


def _dump_record(record: dict[str, Any]) -> str:
    """개별 JSON 직렬화 — 사람이 리뷰하므로 들여쓰기 유지 (KD-1 큐레이션 배치)."""
    return json.dumps(record, ensure_ascii=False, indent=2) + "\n"


def _read_shard(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out[str(rec["id"])] = rec
    return out


def write_shard(
    path: Path,
    records: Iterable[dict[str, Any]],
    *,
    allow_delete: Iterable[str] = (),
    root: Path | None = None,
    validate: bool = True,
) -> WriteReport:
    """NDJSON 샤드를 통째로 다시 쓴다 (KD-1 벌크 배치).

    `records`는 **그 샤드의 최종 전량**이다. 기존에 있었으나 빠진 레코드는
    `allow_delete`에 id가 명시된 것만 삭제하고, 나머지는 **거부**한다(안전장치 ②)
    — 부분 갱신이 정본을 조용히 깎는 사고를 구조적으로 막는다. 삭제 근거는
    호출자가 원장(`knowledge/ingest/exclusions.json` 등)에서 가져온다.
    """
    before = _read_shard(path)
    incoming = {str(r["id"]): r for r in records}
    allowed = set(allow_delete)
    missing = set(before) - set(incoming)
    unexpected = sorted(missing - allowed)
    if unexpected:
        raise KBWriteError(
            f"{path.name}: 근거 없는 레코드 감소 {len(unexpected)}건 — 쓰기 거부. "
            f"삭제하려면 allow_delete에 id를 명시하라 (예: {unexpected[:3]})"
        )
    _atomic_write(path, _dump_shard(incoming.values()))
    if validate:
        load(root)  # 안전장치 ①: 깨진 상태로 남지 않는다 (실패 시 예외)
    return WriteReport(
        path=path,
        added=tuple(sorted(set(incoming) - set(before))),
        updated=tuple(sorted(k for k in set(incoming) & set(before) if incoming[k] != before[k])),
        removed=tuple(sorted(missing & allowed)),
    )


def write_record(
    path: Path, record: dict[str, Any], *, root: Path | None = None, validate: bool = True
) -> WriteReport:
    """큐레이션 개별 JSON 1건을 쓴다 (KD-1 큐레이션 배치).

    ⚠️ `path`는 **그 레코드만 담은 파일**이어야 한다 — 샤드 경로를 넘기면
    파일 전체가 한 레코드로 덮여 파괴된다. 그 사고를 여기서 차단한다.
    """
    if path.suffix == ".ndjson":
        raise KBWriteError(
            f"{path.name}: 샤드에 개별 레코드를 쓸 수 없다 — write_shard를 쓰라 "
            "(파일 전체가 한 줄로 덮이는 파괴 경로)"
        )
    _atomic_write(path, _dump_record(record))
    if validate:
        load(root)
    return WriteReport(path=path, updated=(str(record["id"]),))


def patch_records(
    updates: Mapping[str, Mapping[str, Any]],
    *,
    root: Path | None = None,
    validate: bool = True,
) -> list[WriteReport]:
    """기존 레코드의 `data`에 필드를 덧씌운다 — 후처리 보강 전용.

    id → data 패치를 받아 **레코드가 실제로 있는 파일**(샤드든 개별이든)을 찾아
    갱신한다. 호출자는 배치 형태를 알 필요가 없다 — 그 판단이 흩어져 있던 것이
    B-6이 없애려는 결함이다. 없는 id는 조용히 넘기지 않고 예외.

    패치 값이 `None`이면 **그 키를 지운다** — 소스에서 사라진 값이 눌러붙지 않게
    하는 재적용 멱등성의 수단이다(예: 젬 코스트 재파싱).
    """
    store = load(root)
    unknown = sorted(set(updates) - set(store.records))
    if unknown:
        raise KBWriteError(f"KB에 없는 id {len(unknown)}건 — 패치 거부 (예: {unknown[:3]})")

    by_path: dict[Path, list[str]] = {}
    for rid in updates:
        by_path.setdefault(store.records[rid].path, []).append(rid)

    def _apply(data: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
        merged = {**data, **{k: v for k, v in patch.items() if v is not None}}
        for key, value in patch.items():  # None = 키 삭제 (재적용 멱등)
            if value is None:
                merged.pop(key, None)
        return merged

    reports: list[WriteReport] = []
    for path, ids in by_path.items():
        if path.suffix == ".ndjson":
            shard = _read_shard(path)
            for rid in ids:
                prev_data = shard[rid].get("data", {})
                shard[rid] = {**shard[rid], "data": _apply(prev_data, updates[rid])}
            _atomic_write(path, _dump_shard(shard.values()))
        else:
            rec = json.loads(path.read_text(encoding="utf-8"))
            rec["data"] = _apply(rec.get("data", {}), updates[rec["id"]])
            _atomic_write(path, _dump_record(rec))
        reports.append(WriteReport(path=path, updated=tuple(sorted(ids))))
    if validate and reports:
        load(root)
    return reports


def patch_record_field(
    entity_id: str,
    field: str,
    value: Any,
    *,
    root: Path | None = None,
    validate: bool = True,
) -> WriteReport:
    """레코드의 **최상위 필드**를 갈아끼운다 (`relations`·`tags`·`notes` 등).

    `patch_records`는 `data` 안쪽 전용이라 관계 엣지처럼 최상위에 사는 필드를
    못 쓴다. 그렇다고 호출자가 파일을 직접 열면 B-6이 없앤 결함(배치 규칙이
    흩어짐·샤드 통째 유실)이 되돌아온다 — 그래서 같은 안전장치(파일 자동 탐색·
    원자적 쓰기·재검증) 위에 얹은 별도 입구를 둔다.

    `id`·`type`은 레코드의 정체성이라 바꿀 수 없다.
    """
    if field in ("id", "type"):
        raise KBWriteError(f"{field}는 레코드의 정체성 — 이 경로로 바꿀 수 없다")
    store = load(root)
    if entity_id not in store.records:
        raise KBWriteError(f"KB에 없는 id: {entity_id}")
    path = store.records[entity_id].path

    if path.suffix == ".ndjson":
        shard = _read_shard(path)
        shard[entity_id] = {**shard[entity_id], field: value}
        _atomic_write(path, _dump_shard(shard.values()))
    else:
        rec = json.loads(path.read_text(encoding="utf-8"))
        rec[field] = value
        _atomic_write(path, _dump_record(rec))
    if validate:
        load(root)
    return WriteReport(path=path, updated=(entity_id,))
