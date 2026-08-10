"""P1a Exit: 시드 KB가 4층 검증(envelope·타입·vocab·참조 무결성)을 통과한다."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pok.common.paths import project_root
from pok.kb.store import KBValidationError, load

ROOT = project_root()


def test_seed_kb_loads_and_validates() -> None:
    store = load()
    assert len(store.records) >= 30, "시드는 30개 이상"
    spark = store.get("skill.spark")
    # 공식 한국어명 (poe2db kr) — 수작성 추정('스파크')이 ingest로 교정된 사례
    assert spark.name_ko == "전기불꽃"
    assert "lightning" in spark.tags


def test_all_relation_targets_resolve() -> None:
    store = load()
    for r in store.records.values():
        for edge in r.relations:
            assert edge["target"] in store.records


def _copy_knowledge(tmp_path: Path) -> Path:
    dst = tmp_path / "knowledge"
    shutil.copytree(ROOT / "knowledge", dst)
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")  # project_root 마커
    return dst


def test_bad_subject_rejected(tmp_path: Path) -> None:
    """vocab에 없는 조건 subject → 로드 실패 (임의 문자열 우회 금지, KD-2)."""
    kdir = _copy_knowledge(tmp_path)
    bad = json.loads((kdir / "game-data/skills/spark.json").read_text(encoding="utf-8"))
    bad["conditions"] = [
        {
            "text": "임의 조건",
            "expr": {"subject": "self.made-up-thing", "op": "==", "value": True},
            "satisfiable_by": [],
            "uptime": "always",
        }
    ]
    (kdir / "game-data/skills/spark.json").write_text(
        json.dumps(bad, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(KBValidationError, match="vocab에 없음"):
        load(tmp_path)


def test_dangling_relation_rejected(tmp_path: Path) -> None:
    """실존하지 않는 relations.target → 로드 실패 (참조 무결성 = 완전성 기준 ④)."""
    kdir = _copy_knowledge(tmp_path)
    bad = json.loads((kdir / "game-data/skills/spark.json").read_text(encoding="utf-8"))
    bad["relations"] = [{"rel": "scales_with", "target": "modifier.does-not-exist"}]
    (kdir / "game-data/skills/spark.json").write_text(
        json.dumps(bad, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(KBValidationError, match="실존하지 않는 id"):
        load(tmp_path)


def test_translation_pairs_line_up_across_the_whole_kb() -> None:
    """⑤ 전수: `<필드>` ↔ `<필드>_ko`의 줄 수가 어긋난 레코드가 없다.

    어긋남은 번역 품질 문제가 아니라 **옆 레코드의 줄이 섞였다**는 신호다. 실측
    2026-08-07: Modifier 1,536건이 그 상태였고(수집이 카탈로그 슬롯의 ko 목록을
    통째로 붙였다), 그 오염된 한글에 `pob_gaps` 반경 스캐너가 매칭해 비반경 모드
    519건에 `radius-grant`가 붙었으며, 한 세션이 그걸 "주얼 소켓은 PoB에서 구조적으로
    저평가된다"로 읽어 **측정 방법론을 바꿨다**.
    """
    store = load()
    bad: list[str] = []
    pairs = 0
    for r in store.records.values():
        data = r.raw.get("data") or {}
        for key, ko in data.items():
            source = data.get(key[:-3]) if key.endswith("_ko") else None
            if not isinstance(ko, list) or not isinstance(source, list):
                continue
            pairs += 1
            if len(source) != len(ko):
                bad.append(f"{r.id}: {key[:-3]} {len(source)}줄 ↔ {key} {len(ko)}줄")
    assert pairs > 1000, "검사가 빈손으로 통과하지 않는지 — 짝이 실제로 있어야 한다"
    assert bad == [], f"번역 짝 불일치 {len(bad)}건: {bad[:5]}"


def test_mismatched_translation_pair_rejected(tmp_path: Path) -> None:
    """짝이 어긋나면 **로드가 거부한다** — 문서가 아니라 도구가 막는다 (철칙 5).

    이 계열은 조용히 1,536건까지 쌓였다. 감지 가능한 규율이므로 모든 쓰기가 거쳐 가는
    `load()`에 둔다 — 여기서 막으면 다시 샐 수 없다.
    """
    kdir = _copy_knowledge(tmp_path)
    bad = json.loads((kdir / "game-data/skills/spark.json").read_text(encoding="utf-8"))
    bad["data"]["texts"] = ["Fires a projectile"]
    bad["data"]["texts_ko"] = ["투사체 발사", "반경 내 주요 패시브 스킬이 …도 부여"]
    (kdir / "game-data/skills/spark.json").write_text(
        json.dumps(bad, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(KBValidationError, match="번역 짝 불일치"):
        load(tmp_path)


def test_envelope_violation_rejected(tmp_path: Path) -> None:
    """envelope 위반(필수 필드 누락) → 로드 실패."""
    kdir = _copy_knowledge(tmp_path)
    (kdir / "game-data/skills/broken.json").write_text(
        json.dumps({"id": "skill.broken", "type": "Skill"}), encoding="utf-8"
    )
    with pytest.raises(KBValidationError, match="envelope"):
        load(tmp_path)


def test_load_cache_never_skips_validation_after_a_write() -> None:
    """캐시가 **안전장치를 무력화하면 안 된다** — 쓰기 후엔 반드시 다시 검증한다.

    `write_shard(validate=True)`가 이 `load`로 재검증하므로, 캐시가 낡은 스냅샷을
    돌려주면 깨진 정본이 조용히 통과한다. 지문은 mtime을 **나노초**로 본다 — 초
    단위면 같은 초 안의 연속 쓰기를 놓친다.
    """
    import json

    from pok.common.paths import knowledge_dir
    from pok.kb.store import _fingerprint, load

    kdir = knowledge_dir()
    first = load(kdir)
    assert load(kdir) is first, "내용이 같으면 같은 스냅샷 — 그래야 빠르다"

    before = _fingerprint(kdir)
    probe = kdir / "game-data" / "mechanics" / "_cache-probe.json"
    probe.write_text(json.dumps({"probe": True}), encoding="utf-8")
    try:
        assert _fingerprint(kdir) != before, "파일이 늘었는데 지문이 같으면 캐시가 위험하다"
    finally:
        probe.unlink(missing_ok=True)
    assert _fingerprint(kdir) == before, "되돌리면 지문도 돌아온다"
