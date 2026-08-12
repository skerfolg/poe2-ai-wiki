"""Build 엔티티의 계약을 잠근다 (#67, 사용자 승인 2026-08-11).

이 엔티티의 값어치는 레코드가 있다는 게 아니라 **역방향 조회가 된다**는 데 있다 —
「이 스킬을 쓰는 메타 빌드는?」. 그게 되려면 세 가지가 동시에 참이어야 하고, 셋 중
하나만 어긋나도 **조용히** 쓸모가 없어진다:

1. 레코드가 `knowledge/game-data/` 안에 있어야 한다 — `store.load()`가 거기만 스캔한다.
   (제안 원안은 `knowledge/builds/`였는데, 거기 두면 로더가 못 봐서 도구에 안 보인다.)
2. `uses` 관계가 어휘에 있어야 한다.
3. `uses` 대상이 **실존 id**여야 한다 — 참조 무결성이 깨지면 KB 로드 자체가 실패한다.
"""

from __future__ import annotations

import pytest

from pok.common.paths import knowledge_dir
from pok.kb.store import load


@pytest.fixture(scope="module")
def builds() -> list:
    return [r for r in load().records.values() if r.type == "Build"]


def test_builds_live_where_the_loader_can_see_them(builds: list) -> None:
    """`game-data/` 밖이면 `search_kb`·`related`가 통째로 못 본다."""
    assert builds, "Build 레코드가 하나도 로드되지 않았다 — 배치를 확인할 것"
    game_data = knowledge_dir() / "game-data"
    for record in builds:
        assert game_data in record.path.parents, (
            f"{record.id}가 game-data/ 밖에 있다({record.path}) — store.load()가 못 본다"
        )


def test_uses_edges_point_at_real_records(builds: list) -> None:
    """`uses` 대상이 실존해야 역방향 조회가 성립한다 (참조 무결성은 로더도 검사한다)."""
    known = set(load().records)
    for record in builds:
        targets = [e["target"] for e in record.raw.get("relations", []) if e["rel"] == "uses"]
        assert targets, f"{record.id}에 uses 간선이 없다 — 역방향 조회가 안 된다"
        missing = [t for t in targets if t not in known]
        assert not missing, f"{record.id}의 uses 대상이 KB에 없다: {missing}"


def test_every_build_declares_its_coupling(builds: list) -> None:
    """⑧ 공수 결합은 **분류가 목적**이라 비워 두면 축이 죽는다.

    4유형은 실측 분류다 — 0.5 메타 8종에서 넷 다 관찰됐고, 그 분포가
    "상위 빌드는 자원을 공유한다"는 초기 가설을 기각했다.
    """
    kinds = {r.raw["data"]["coupling"]["kind"] for r in builds}
    assert kinds <= {
        "shared-resource",
        "separate",
        "offense-feeds-defense",
        "defense-action-feeds-offense",
    }


def test_no_build_claims_a_tier(builds: list) -> None:
    """⛔ **티어·메타 순위는 담지 않는다** (`[빌드]` 정정 통보 2026-08-11).

    처음 8종은 웹 가이드의 티어를 그대로 실었는데, 그 소스가 **0.4 시절 빌드를 재탕한
    SEO 기사**였다. poe.ninja 실측(Runes of Aldur 124,254 캐릭터)과 대조하니 뒤집혔다:
    Invoker는 "S티어"인데 래더 **0.5%**, Amazon은 "메타 1위"인데 **1.0%**였다.
    실제 상위는 Martial Artist 20.7% · Gemling 15.7% · Spirit Walker 11.5%다.

    `COMMUNITY` 라벨의 신뢰 범위는 **「구성」까지**다 — 어떤 축을 어떻게 엮었는지는
    가이드가 실제로 돌려 본 것이라 믿을 수 있지만, **순위 주장은 근거가 없다**.
    순위가 필요하면 poe.ninja 사용률 실측으로만 채운다.

    문서에만 적으면 다음 세션이 가이드를 읽고 또 넣는다 — 그래서 시험으로 막는다(철칙 5).
    """
    offenders = [r.id for r in builds if "tier" in (r.raw.get("facets") or {})]
    assert not offenders, (
        f"티어를 주장하는 Build 레코드: {offenders} — 웹 가이드의 티어는 오염된 적이 있다. "
        "순위는 poe.ninja 사용률 실측으로만 담을 것"
    )


def test_usage_is_measured_not_claimed(builds: list) -> None:
    """점유는 **실측 출처를 달고** 들어온다 — 티어와 갈리는 지점이 이것이다.

    `tier`를 금지한 것은 순위 자체가 나빠서가 아니라 **근거가 SEO 기사**였기 때문이다.
    poe.ninja 래더 집계는 실제 캐릭터를 센 것이라 담아도 된다. 다만 두 가지를 지킨다:

    1. `basis`(출처)가 반드시 붙는다 — 없으면 다시 "누가 그랬다더라"가 된다.
    2. 값은 **어센던시 점유율**이지 이 빌드의 점유가 아니다. 뭉치면 "이 빌드가 래더의
       20.7%"라는 틀린 읽기가 나온다 — 그래서 `note`로 못박고 아키타입 지배력은
       `dominance`에 따로 적는다.
    """
    for record in builds:
        usage = (record.raw.get("facets") or {}).get("usage")
        if usage is None:
            continue
        assert usage.get("basis"), f"{record.id}의 usage에 출처(basis)가 없다"
        assert isinstance(usage.get("ascendancy_pct"), int | float)
        assert usage.get("note"), f"{record.id}: 어센던시 점유임을 밝히지 않으면 오독된다"


def test_transfer_axis_is_recorded(builds: list) -> None:
    """③ 전달 장치가 이 모델의 핵심이다 — 스택과 딜 사이의 다리.

    담체·스택만 적으면 「무엇을 쌓나」는 알아도 **「그게 왜 딜이 되나」**를 잃는다.
    다리가 없는 빌드(중독처럼 히트가 곧 강도)는 그 사실을 명시하게 한다.
    """
    for record in builds:
        transfer = record.raw["data"]["offense"].get("transfer")
        assert transfer, f"{record.id}에 transfer 축이 비어 있다 — 없으면 없다고 적을 것"


def test_관측은_표본을_밝힌다(builds: list) -> None:
    """`data.observed`는 **관측치**라 표본 없이는 읽을 수 없다 (사용자 승인 2026-08-12).

    「10명 중 10명이 혜성」과 「혜성을 쓴다」의 차이가 이 엔티티의 값어치다 —
    전자는 **불변(필수)**, 후자는 그냥 등장. 그런데 `share: 100`만 적혀 있으면
    3벌 중 3벌인지 1000명 중 1000명인지 알 수 없고, 그 둘은 신뢰도가 전혀 다르다.
    그래서 스키마가 `sample`을 필수로 걸고, 여기서 한 번 더 확인한다.

    8축(offense/defense)과 섞지 않는 것도 같은 이유다 — 그쪽은 해석이고 이쪽은 측정이다.
    """
    for record in builds:
        observed = record.raw["data"].get("observed")
        if observed is None:
            continue
        sample = observed["sample"]
        assert sample["n"] >= 1 and sample["basis"]
        for key, entries in observed.items():
            if key == "sample":
                continue
            assert entries == sorted(entries, key=lambda e: -e["share"]), (
                f"{record.id}의 {key}가 채택률 내림차순이 아니다"
            )
            for e in entries:
                # 안층(표본 N벌)은 개수를 함께 실어야 "3/10"이 "30%"로 뭉개지지 않는다
                if sample["unit"] == "sampled-builds":
                    assert "count" in e, f"{record.id}: {e['ref']}에 count가 없다"
                    assert e["count"] <= sample["n"]
