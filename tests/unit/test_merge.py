"""④ merge 재실행 안전성 — 채워진 KB에 다시 돌려도 정본이 그대로다 (멱등).

회귀 근거(2026-08-03 실측): 샤드(NDJSON) 소속 레코드를 개별 JSON 시드로 오인해
`Record.path`(=샤드 파일 전체)에 단일 JSON을 덮어써 skills/supports 샤드가 0줄이 됐다.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from pok.common.paths import project_root
from pok.kb.ingest.merge import merge_patch

SHARDS = ("skills.ndjson", "supports.ndjson")


def _item(slug: str, name_en: str, name_ko: str, category: str, **over: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "slug": slug,
        "categories": [category],
        "name_en": name_en,
        "name_ko": name_ko,
        "tags": ["Fire"],
        "tier": 2,
        "description": f"{name_en} does something.",
        "acquisition": ["Uncut Skill Gem"],
        "has_level_effect": True,
        "in_pob": True,
        "pob_meta_id": f"Metadata/Items/Gems/{name_en.replace(' ', '')}",
        "verdict": "implemented",
    }
    item.update(over)
    return item


ITEMS = [
    _item("Fireball", "Fireball", "화염구", "skill-gems"),  # 개별 JSON 시드와 id 일치
    _item("Spark", "Spark", "전기불꽃", "skill-gems"),
    _item("Ice_Nova", "Ice Nova", "얼음 회오리", "skill-gems"),
    _item("Fork", "Fork", "분기", "support-gems"),
    _item("Freeze", "Freeze", "빙결", "support-gems"),
]

# 수작업 큐레이션 시드 (KD-1 혼합 배치) — relations·facets·notes는 ingest가 건드리면 안 된다
SEED: dict[str, Any] = {
    "id": "skill.fireball",
    "type": "Skill",
    "name": {"ko": "파이어볼", "en": "Fireball"},  # 추정 ko — ingest가 공식명으로 교정
    "tags": ["guessed"],
    "data": {"category": "spell", "cost_resource": "mana"},
    "verification": "SUPPORTED_INFERENCE",
    "sources": [{"src": "community", "ref": "seed"}],
    "relations": [{"rel": "scales_with", "target": "skill.fireball"}],
    "facets": {"role": "main"},
    "notes": "사람이 적은 메모",
}


def _minimal_kb(tmp_path: Path) -> tuple[Path, Path]:
    """스키마만 갖춘 최소 정본 + 개별 JSON 시드 1건. 반환: (repo root, knowledge)."""
    root = tmp_path / "repo"
    knowledge = root / "knowledge"
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text("", encoding="utf-8")  # project_root 마커
    shutil.copytree(project_root() / "knowledge" / "schema", knowledge / "schema")
    seeds = knowledge / "game-data" / "skills"
    seeds.mkdir(parents=True)
    (seeds / "fireball.json").write_text(
        json.dumps(SEED, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return root, knowledge


def _intermediate(tmp_path: Path) -> Path:
    p = tmp_path / "intermediate.json"
    p.write_text(json.dumps(ITEMS, ensure_ascii=False), encoding="utf-8")
    return p


def _snapshot(knowledge: Path) -> dict[str, str]:
    gems = knowledge / "game-data" / "gems"
    files = {name: (gems / name).read_text(encoding="utf-8") for name in SHARDS}
    files["fireball.json"] = (knowledge / "game-data/skills/fireball.json").read_text(
        encoding="utf-8"
    )
    return files


def test_merge_twice_is_idempotent(tmp_path: Path) -> None:
    """채워진 KB에 두 번째 merge — 샤드 줄 수·내용 불변 (0줄 붕괴 회귀 방지)."""
    _, knowledge = _minimal_kb(tmp_path)
    inter = _intermediate(tmp_path)

    first = merge_patch(tmp_path, inter, knowledge, "t")
    assert (first["updated_seeds"], first["bulk_skills"], first["bulk_supports"]) == (1, 2, 2)
    before = _snapshot(knowledge)
    assert [before[n].count("\n") for n in SHARDS] == [2, 2]

    second = merge_patch(tmp_path, inter, knowledge, "t")
    assert second == first, "요약 수치도 동일 — 샤드 레코드가 시드로 재분류되지 않는다"
    assert _snapshot(knowledge) == before, "두 번째 실행이 정본을 바꾸지 않는다"

    # 파괴 형태 자체를 못 박는다: 샤드는 여전히 레코드 1건/줄인 NDJSON이다
    for name in SHARDS:
        lines = [line for line in before[name].splitlines() if line.strip()]
        assert len(lines) == 2
        assert all(json.loads(line)["id"].startswith(("skill.", "support.")) for line in lines)


def test_curated_seed_fields_survive_merge(tmp_path: Path) -> None:
    """시드는 개별 JSON에만 갱신되고 수작업 필드(relations·facets·notes)는 보존된다 (KD-1)."""
    _, knowledge = _minimal_kb(tmp_path)
    merge_patch(tmp_path, _intermediate(tmp_path), knowledge, "t")

    seed_path = knowledge / "game-data/skills/fireball.json"
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    assert seed["relations"] == SEED["relations"]
    assert seed["facets"] == SEED["facets"]
    assert seed["notes"] == SEED["notes"]
    assert seed["name"]["ko"] == "화염구", "D11: 게임 공식명이 시드 추정값을 대체"
    assert seed["tags"] == ["fire"]
    assert seed["data"]["cost_resource"] == "mana", "시드 수작업 data 키 유지"
    assert seed["data"]["description"], "ingest 산출 data 병합"
    assert "skill.fireball" not in (knowledge / "game-data/gems/skills.ndjson").read_text(
        encoding="utf-8"
    ), "시드는 샤드로 중복 기록되지 않는다"


def test_shard_enrichment_survives_but_stale_machine_values_do_not(tmp_path: Path) -> None:
    """샤드에 후속 단계가 붙인 필드는 재실행에도 남고, 기계 소유 키는 소스 값으로 되돌아간다."""
    _, knowledge = _minimal_kb(tmp_path)
    inter = _intermediate(tmp_path)
    merge_patch(tmp_path, inter, knowledge, "t")

    shard = knowledge / "game-data/gems/skills.ndjson"
    records = [json.loads(line) for line in shard.read_text(encoding="utf-8").splitlines()]
    records[0]["data"]["acquisition"] = "liquid-emotion"  # 후속 보강 (성유 반영과 동형)
    records[0]["data"]["tier"] = 99  # 기계 소유 키를 손댄 경우
    shard.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )

    merge_patch(tmp_path, inter, knowledge, "t")
    after = [json.loads(line) for line in shard.read_text(encoding="utf-8").splitlines()]
    assert len(after) == 2
    assert after[0]["data"]["acquisition"] == "liquid-emotion", "보강 필드 보존"
    assert after[0]["data"]["tier"] == 2, "기계 소유 키는 소스 값으로 갱신"


def test_deletion_needs_a_ruling(tmp_path: Path) -> None:
    """샤드 삭제는 원장 근거가 있을 때만 — 근거 없는 미포함분은 보존하고 후보로 리포트한다.

    무조건 삭제하면 부분 merge가 KB를 깎고(2026-08-02 830건 손실), 무조건 보존하면
    사용자 제외 판정(통합·현 패치 미획득)이 무효가 된다.
    """
    _, knowledge = _minimal_kb(tmp_path)
    merge_patch(tmp_path, _intermediate(tmp_path), knowledge, "t")
    shard = knowledge / "game-data/gems/supports.ndjson"
    assert len(shard.read_text(encoding="utf-8").splitlines()) == 2

    # Fork = 원장 근거로 제외(통합), Freeze = 이번 판정에서 빠졌을 뿐 근거 없음
    ruled = [
        _item("Fork", "Fork", "분기", "support-gems", verdict="excluded-superseded"),
        _item("Freeze", "Freeze", "빙결", "support-gems", verdict="pob-only-or-parse-gap"),
    ]
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps([ITEMS[0], *ruled], ensure_ascii=False), encoding="utf-8")

    summary = merge_patch(tmp_path, partial, knowledge, "t")
    assert summary["removed_by_ruling"] == ["support.fork"], "판정된 제외분만 삭제"
    assert summary["deletion_candidates"] == [
        "skill.ice-nova",
        "skill.spark",
        "support.freeze",
    ], "근거 없는 미포함분은 전부 후보로만 (부분 merge에서 빠진 것 포함)"
    left = [json.loads(line) for line in shard.read_text(encoding="utf-8").splitlines()]
    assert [r["id"] for r in left] == ["support.freeze"], "후보는 지우지 않고 남긴다"
    # 이번 수록분에 없던 skill 샤드도 근거가 없으므로 그대로 남는다
    skills = (knowledge / "game-data/gems/skills.ndjson").read_text(encoding="utf-8")
    assert len(skills.splitlines()) == 2, "부분 merge가 다른 샤드를 깎지 않는다"
