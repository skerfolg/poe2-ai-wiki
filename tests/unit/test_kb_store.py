"""P1a Exit: 시드 KB가 4층 검증(envelope·타입·vocab·참조 무결성)을 통과한다."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pok.common.paths import project_root
from pok.kb import store as store_mod
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


def _write(path: Path, raw: object) -> None:
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")


def _mini_kb(tmp_path: Path) -> Path:
    """스키마 **전량** + 레코드 1건짜리 최소 정본.

    아래 거부 시험들이 재는 것은 **검증기의 판정**이지 정본의 내용이 아니다 — 레코드는
    1건이면 족하다. 정본 사본(695파일·81MB)을 뜨면 복사에 ~10초, 전 검증에 수십 초가
    더 든다. 거부 시험 4건이 시험마다 그 값을 물고 있었다(실측 2026-08-26: 이 파일이
    CI에서 4분 40초). 정본 **자체**의 정합은 `test_seed_kb_loads_and_validates`·
    `test_all_relation_targets_resolve`·`test_translation_pairs_line_up_across_the_whole_kb`
    가 여전히 **전량으로** 본다 — 줄어든 것은 사본 비용이지 검사 범위가 아니다.
    """
    kdir = tmp_path / "knowledge"
    shutil.copytree(ROOT / "knowledge/schema", kdir / "schema")
    raw = json.loads((ROOT / "knowledge/game-data/skills/spark.json").read_text(encoding="utf-8"))
    raw.pop("relations", None)  # 참조 무결성 — 이 정본엔 가리킬 상대가 없다
    raw.pop("conditions", None)
    (kdir / "game-data/skills").mkdir(parents=True)
    _write(kdir / "game-data/skills/spark.json", raw)
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")  # project_root 마커
    return kdir


def test_bad_subject_rejected(tmp_path: Path) -> None:
    """vocab에 없는 조건 subject → 로드 실패 (임의 문자열 우회 금지, KD-2)."""
    kdir = _mini_kb(tmp_path)
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
    kdir = _mini_kb(tmp_path)
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
    kdir = _mini_kb(tmp_path)
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
    kdir = _mini_kb(tmp_path)
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


# ── 로드 캐시가 안전장치를 무력화하지 않는가 (#127) ──────────────────────────
#
# `load()`에는 캐시가 둘 있다. 디렉터리 단위 `_LOAD_CACHE`(지문이 같으면 스냅샷 재사용)와
# 레코드 단위 `_VALIDATION_MEMO`(원문 바이트 + 스키마 지문이 같으면 검증 결과 재사용).
# 캐시는 정의상 **검증을 건너뛰는 장치**라 조건이 하나만 새도 깨진 정본이 조용히 통과한다.


def test_record_edit_is_never_served_from_the_memo(tmp_path: Path) -> None:
    """①바이트가 바뀌면 다시 잰다 — 통과한 뒤에 오염시켜도 잡혀야 한다."""
    kdir = _mini_kb(tmp_path)
    load(tmp_path)  # 통과 — 메모에 '합격'이 남는다

    spark = kdir / "game-data/skills/spark.json"
    raw = json.loads(spark.read_text(encoding="utf-8"))
    raw["relations"] = [{"rel": "scales_with", "target": "modifier.does-not-exist"}]
    _write(spark, raw)

    with pytest.raises(KBValidationError, match="실존하지 않는 id"):
        load(tmp_path)


def test_schema_edit_is_never_served_from_the_cache(tmp_path: Path) -> None:
    """②**스키마**가 엄격해져도 다시 잰다.

    검증은 (데이터, 스키마) 둘의 함수인데 지문이 데이터만 보면 스키마를 조여도 옛 통과가
    돌아온다 — `_fingerprint`의 "한 바이트라도 바뀌면 다시 검증한다"가 스키마 쪽에서만
    거짓이었다. 그래서 지문은 `schema/`까지 세고, 메모 키에는 스키마 지문이 함께 들어간다.
    둘 중 하나만 빠져도 이 시험이 깨진다.
    """
    kdir = _mini_kb(tmp_path)
    load(tmp_path)

    sp = kdir / "schema/record.schema.json"
    schema = json.loads(sp.read_text(encoding="utf-8"))
    schema["required"] = [*schema.get("required", []), "no-such-field"]
    _write(sp, schema)

    with pytest.raises(KBValidationError, match="envelope"):
        load(tmp_path)


def test_memoized_verdict_still_names_the_offending_file(tmp_path: Path) -> None:
    """③메모는 **판정만** 재사용한다 — 경로는 매번 그 파일 것이어야 한다.

    메시지째 캐시하면 둘째 파일의 오류가 **첫째 파일 이름으로** 보고된다. 지목이 틀리면
    세션은 멀쩡한 파일을 뜯어본다(#21이 그 방식으로 몇 분을 태웠다).
    """
    kdir = _mini_kb(tmp_path)
    broken = {"id": "skill.broken", "type": "Skill"}  # data 없음 = envelope 위반

    _write(kdir / "game-data/skills/first.json", broken)
    with pytest.raises(KBValidationError) as first:
        load(tmp_path)
    assert "first.json" in str(first.value)

    (kdir / "game-data/skills/first.json").unlink()
    _write(kdir / "game-data/skills/second.json", broken)  # 바이트 동일 = 메모 적중
    with pytest.raises(KBValidationError) as second:
        load(tmp_path)
    assert "second.json" in str(second.value), "메모 적중이어도 경로는 이 파일 것"
    assert "first.json" not in str(second.value)


def test_unchanged_records_are_not_revalidated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """④안 바뀐 레코드는 **다시 재지 않는다** — 속도 규율의 강제 지점이다.

    `_LOAD_CACHE`는 디렉터리 단위라 레코드 하나만 달라도 전량을 다시 검증한다. 정본
    사본을 떠 한 줄만 고치는 시험이 11개 있었고 그 하나하나가 33초였다(실측 2026-08-26:
    로드 33.10초 중 jsonschema가 94%). 메모가 빠지면 그 33초가 돌아오는데 **아무도 못
    본다** — 느려진 것은 실패가 아니기 때문이다. 그래서 시간이 아니라 **횟수로** 잠근다.
    """
    kdir = _mini_kb(tmp_path)
    load(tmp_path)  # 메모를 채운다

    seen: list[object] = []
    real = store_mod._validate_record
    monkeypatch.setattr(
        store_mod,
        "_validate_record",
        lambda *a: (seen.append(a[0].get("id")), real(*a))[1],
    )

    # 레코드를 하나 **추가**한다 — 디렉터리 지문이 바뀌어 전 검증이 다시 돈다
    raw = json.loads((kdir / "game-data/skills/spark.json").read_text(encoding="utf-8"))
    raw["id"] = "skill.spark-twin"
    _write(kdir / "game-data/skills/twin.json", raw)
    load(tmp_path)

    assert seen == ["skill.spark-twin"], f"새 레코드 1건만 다시 잰다 (실제: {seen})"
