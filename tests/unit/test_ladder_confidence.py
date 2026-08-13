"""꼬리를 **자르지 않고** 신뢰도로 싣는 계약을 잠근다 (2026-08-13).

절단(`min_count>=2`)은 노이즈를 줄이는 것처럼 보이지만 실제로는 목록을 **거짓으로
좁힌다**. 실측 2026-08-12: 마셜 아티스트 목적지는 106종인데 레코드엔 53종만 실려,
그 목록으로 대조하니 멀쩡한 래더 빌드의 목적지 41개 중 20개(49%)가 「표본 밖」으로
찍혔다. 2026-08-13 재측정에서는 손실이 축마다 더 컸다 — `keypassives-Chaos_Inoculation`
목적지 254종 중 **221종(87%)**이 잘려 있었다.

그리고 잘려 나간 1~2벌 항목은 「아무도 안 쓴다」가 아니라 **「소수가 쓴다」**다.
그 구분이 창의의 재료이므로(#62) 절단이 아니라 `ci_low`로 다룬다.
"""

from __future__ import annotations

import json

from pok.engine import ladder_aggregate as agg


def test_신뢰_하한은_표본이_커지면_오른다() -> None:
    """`share`만으로는 표본 크기가 사라진다 — 10/10과 50/50이 둘 다 100%다.

    하한은 그 둘을 갈라 준다(72.2 vs 92.9). **표본을 늘려야 하는 이유가 레코드
    안에서 보이는 유일한 자리**다.
    """
    assert agg._wilson_low(10, 10) == 72.2
    assert agg._wilson_low(50, 50) == 92.9
    assert agg._wilson_low(100, 100) == 96.3
    # 같은 10%도 표본이 커지면 믿을 만해진다 — 꼬리를 자를 이유가 아니라 잴 이유다
    assert agg._wilson_low(1, 10) < agg._wilson_low(5, 50)
    assert agg._wilson_low(0, 10) == 0.0


def test_채택률에_신뢰_하한이_함께_실린다() -> None:
    rows = agg._tally([["a", "b"], ["a"], ["a"]])
    top = next(r for r in rows if r["ref"] == "a")
    tail = next(r for r in rows if r["ref"] == "b")
    assert top["count"] == 3 and top["share"] == 100.0
    assert top["ci_low"] == agg._wilson_low(3, 3)
    # 꼬리도 실린다 — 자르면 「1/3이 쓴다」가 「아무도 안 쓴다」로 바뀐다
    assert tail["count"] == 1 and tail["ci_low"] < top["ci_low"]


def test_절단은_기본이_아니다() -> None:
    """`min_count=1`은 전량이고, 그것이 기본이다. 선언만으로는 사고가 안 막혔다."""
    observed = {
        "sample": {"n": 10, "unit": "sampled-builds", "basis": "x"},
        "passives": [{"ref": "a", "share": 100.0, "count": 10, "ci_low": 72.2}],
    }
    kept = json.loads(json.dumps(observed))
    agg._truncate(kept, 1)
    assert kept["sample"]["min_count"] == 1
    assert len(kept["passives"]) == 1, "전량이어야 하는데 잘렸다"

    # 명시적으로 주면 여전히 자른다(호출자가 짧은 목록을 원할 수 있다) — 단 선언이 남는다
    cut = json.loads(json.dumps(observed))
    agg._truncate(cut, 11)
    assert cut["passives"] == [] and cut["sample"]["min_count"] == 11


def test_cli_기본값이_전량이다(capfd) -> None:
    """기본값이 곧 정책이다 — 여기서 2·3으로 돌아가면 잘린 정본이 다시 쌓인다.

    `capsys`가 아니라 `capfd`다: `_cli`가 `force_utf8_stdio()`로 `sys.stdout`을
    갈아 끼우므로 파이썬 층 캡처는 빈 문자열을 받는다(실측).
    """
    import contextlib

    for cmd in ("aggregate", "profile"):
        with contextlib.suppress(SystemExit):
            agg._cli([cmd, "--help"])
        out = capfd.readouterr().out
        assert "--min-count" in out, f"{cmd}에 --min-count가 없다"
        line = out[out.index("--min-count") :]
        assert "기본은 1" in line or "기본 1" in line, (
            f"{cmd}의 --min-count 도움말이 전량 기본을 밝히지 않는다"
        )


def test_레벨_분포를_레코드에_남긴다(tmp_path, monkeypatch) -> None:
    """표본을 래더 **아래로** 늘릴 때 미완성 캐릭터가 섞이는데, 그것과 「설계 선택」은
    겉보기가 같다. 레벨 분포가 없으면 읽는 쪽이 구분할 방법이 없다(철칙 5 — 기계가
    재는 조건이니 문서가 아니라 레코드에 둔다).
    """
    monkeypatch.setattr(agg, "_tree_index", lambda: {1: ("passive.a", "notable")})
    monkeypatch.setattr(agg, "_node_positions", lambda: {})

    class _Fake:
        skill_groups = ()
        items = ()
        ascendancy = "Lich"
        tree_nodes = (1,)

    monkeypatch.setattr(agg, "parse_pob", lambda _code: _Fake())
    folder = tmp_path / "0-5" / "x"
    folder.mkdir(parents=True)
    for i, lv in enumerate((100, 92, 100)):
        (folder / f"{i}.json").write_text(
            json.dumps({"pob_export": "x", "raw": {"level": lv}}), encoding="utf-8"
        )

    out = agg.aggregate_concept("0-5", "x", base=tmp_path)
    assert out["sample"]["level"] == {"min": 92, "median": 100, "max": 100}


def test_레벨이_없으면_조용히_0을_내지_않는다(tmp_path, monkeypatch) -> None:
    """`level: 0`은 「레벨 0짜리 표본」으로 읽힌다 — 없으면 키를 아예 안 낸다."""
    monkeypatch.setattr(agg, "_tree_index", lambda: {1: ("passive.a", "notable")})
    monkeypatch.setattr(agg, "_node_positions", lambda: {})

    class _Fake:
        skill_groups = ()
        items = ()
        ascendancy = "Lich"
        tree_nodes = (1,)

    monkeypatch.setattr(agg, "parse_pob", lambda _code: _Fake())
    folder = tmp_path / "0-5" / "x"
    folder.mkdir(parents=True)
    (folder / "a.json").write_text(json.dumps({"pob_export": "x"}), encoding="utf-8")

    out = agg.aggregate_concept("0-5", "x", base=tmp_path)
    assert "level" not in out["sample"]


def _fake_parse(monkeypatch) -> None:
    monkeypatch.setattr(agg, "_tree_index", lambda: {1: ("passive.a", "notable")})
    monkeypatch.setattr(agg, "_node_positions", lambda: {})

    class _Fake:
        skill_groups = ()
        items = ()
        ascendancy = "Lich"
        tree_nodes = (1,)

    monkeypatch.setattr(agg, "parse_pob", lambda _code: _Fake())


def _write(folder, stem: str, *, account: str, name: str, updated: str) -> None:
    (folder / f"{stem}.json").write_text(
        json.dumps(
            {
                "pob_export": "x",
                "character_updated_utc": updated,
                "raw": {"account": account, "name": name, "level": 100},
            }
        ),
        encoding="utf-8",
    )


def test_같은_캐릭터의_옛_갱신본은_표본으로_세지_않는다(tmp_path, monkeypatch) -> None:
    """원시는 append-only라 **재수집하면** 리스펙한 캐릭터의 파일이 하나 더 생긴다.

    수집기의 중복 제거는 「같은 갱신본」까지이지 「같은 캐릭터」가 아니다 — 그대로
    세면 한 사람이 두 벌이 되어 `n`이 부풀고 그 사람의 젬·아이템이 두 번 계산된다.
    실측 2026-08-13: 기존 컨셉을 10 → 50벌로 올리자 `class-Amazon` 54파일이 실제로는
    50명이었다.
    """
    _fake_parse(monkeypatch)
    folder = tmp_path / "0-5" / "x"
    folder.mkdir(parents=True)
    _write(folder, "a_old", account="acc-1", name="Zed", updated="2026-07-01T00:00:00Z")
    _write(folder, "a_new", account="acc-1", name="Zed", updated="2026-08-01T00:00:00Z")
    _write(folder, "b", account="acc-2", name="Wye", updated="2026-08-01T00:00:00Z")

    out = agg.aggregate_concept("0-5", "x", base=tmp_path)
    assert out["sample"]["n"] == 2, "파일 3벌이지만 캐릭터는 2명이다"
    assert out["sample"]["superseded"] == 1, "버린 옛 갱신본 수를 **선언**한다"


def test_버린_것이_없어도_선언은_남는다(tmp_path, monkeypatch) -> None:
    """`superseded`가 없으면 「재수집을 안 거쳤다」와 「필드가 없던 시절」이 같아진다
    (형태 ① — 선언이 없으면 조용한 0)."""
    _fake_parse(monkeypatch)
    folder = tmp_path / "0-5" / "x"
    folder.mkdir(parents=True)
    _write(folder, "b", account="acc-2", name="Wye", updated="2026-08-01T00:00:00Z")

    out = agg.aggregate_concept("0-5", "x", base=tmp_path)
    assert out["sample"]["superseded"] == 0


def _keystone_env(monkeypatch) -> None:
    """키스톤 하나를 트리에 두고, poe.ninja 쪽 이름 매핑을 붙인다."""
    monkeypatch.setattr(agg, "_tree_index", lambda: {1: ("passive.unwavering-stance", "keystone")})
    monkeypatch.setattr(agg, "_node_positions", lambda: {})
    monkeypatch.setattr(
        agg, "_keystone_ids", lambda: {"unwavering stance": "passive.unwavering-stance"}
    )


def _ks_doc(*, on_tree: bool, held: str = "Unwavering Stance") -> str:
    return json.dumps(
        {
            "pob_export": "x",
            "raw": {
                "account": "a",
                "name": ("A" if on_tree else "B"),
                "keystones": [{"name": held}],
            },
        }
    )


def test_트리로_찍었나_장비로_받았나를_가른다(tmp_path, monkeypatch) -> None:
    """필터가 **전원 보유**를 보장하는데 트리 채택률은 그보다 낮을 수 있다 (#75).

    poe.ninja는 "Includes keystones from timeless jewels and allocated by equipment"라
    선언한다 — 우리 `passives`는 할당 트리만 읽으므로 둘이 갈린다. 실측 2026-08-13:
    `keypassives=Unwavering Stance` 50벌 중 트리 채택은 21벌(42%)뿐이고 29벌은
    `Flesh Crucible` 같은 주얼이 줬다. 42%를 「절반 이상이 안 쓴다」로 읽으면
    정반대 결론이 되므로 레코드가 셋을 갈라 실어야 한다.
    """
    _keystone_env(monkeypatch)

    class _OnTree:
        skill_groups = ()
        items = ()
        ascendancy = "Warrior"
        tree_nodes = (1,)

    class _OffTree(_OnTree):
        tree_nodes = ()

    monkeypatch.setattr(agg, "parse_pob", lambda code: _OnTree() if code == "on" else _OffTree())
    folder = tmp_path / "0-5" / "x"
    folder.mkdir(parents=True)
    for i, (stem, on) in enumerate((("a", True), ("b", False), ("c", False))):
        (folder / f"{i}{stem}.json").write_text(
            json.dumps(
                {
                    "pob_export": "on" if on else "off",
                    "raw": {
                        "account": f"acc-{i}",
                        "name": stem,
                        "keystones": [{"name": "Unwavering Stance"}],
                    },
                }
            ),
            encoding="utf-8",
        )

    record = agg.build_usage_profile(
        "0-5",
        "x",
        anchor_ref="passive.unwavering-stance",
        anchor_label="변함없는 자세",
        query={"keypassives": "Unwavering Stance"},
        base=tmp_path,
    )
    anchor = record["data"]["observed"]["anchor"]
    assert anchor["held"]["count"] == 3, "필터가 보장한 보유는 전원이다"
    assert anchor["on_tree"]["count"] == 1, "트리로 찍은 것은 1벌뿐"
    assert anchor["off_tree"]["count"] == 2, "나머지는 주얼·장비가 준 것"
    assert "why" in anchor, "트리 밖이 있는데 사유를 안 밝히면 42%가 그대로 오독된다"


def test_앵커가_키스톤이_아니면_0을_싣지_않는다(tmp_path, monkeypatch) -> None:
    """스킬·아이템 축에는 잴 것이 없다. 0을 실으면 「아무도 안 쓴다」로 읽힌다."""
    _keystone_env(monkeypatch)

    class _Fake:
        skill_groups = ()
        items = ()
        ascendancy = "Warrior"
        tree_nodes = (1,)

    monkeypatch.setattr(agg, "parse_pob", lambda _code: _Fake())
    folder = tmp_path / "0-5" / "x"
    folder.mkdir(parents=True)
    (folder / "a.json").write_text(_ks_doc(on_tree=True), encoding="utf-8")

    record = agg.build_usage_profile(
        "0-5",
        "x",
        anchor_ref="skill.spark",
        anchor_label="스파크",
        query={"skills": "Spark"},
        base=tmp_path,
    )
    assert "anchor" not in record["data"]["observed"]


def test_KB에_없는_키스톤은_트리밖으로_몰지_않는다(tmp_path, monkeypatch) -> None:
    """KB id가 없으면 트리 쪽과 맞댈 수가 없다 — 넣으면 전부 「트리 밖」이 되어
    모르는 것을 아는 척하게 된다. 다만 **버리지도 않는다**(수집 갭이 보여야 한다).
    실측 2026-08-13: poe.ninja 키스톤 39종 중 7종이 KB에 없다."""
    _keystone_env(monkeypatch)

    class _Fake:
        skill_groups = ()
        items = ()
        ascendancy = "Warrior"
        tree_nodes = (1,)

    monkeypatch.setattr(agg, "parse_pob", lambda _code: _Fake())
    folder = tmp_path / "0-5" / "x"
    folder.mkdir(parents=True)
    (folder / "a.json").write_text(
        _ks_doc(on_tree=True, held="Sacrifice of Flesh"), encoding="utf-8"
    )

    out = agg.aggregate_concept("0-5", "x", base=tmp_path)
    assert [e["ref"] for e in out["keystones"]] == ["unmapped:Sacrifice of Flesh"]
    assert out["keystones_off_tree"] == [], "매핑이 안 되는 것을 트리 밖이라 단정하지 않는다"


def test_신원이_없는_표본은_뭉치지_않는다(tmp_path, monkeypatch) -> None:
    """계정·이름이 없는 레코드끼리 같은 키가 되면 서로 다른 표본이 한 사람으로
    뭉쳐 `n`이 **줄어든다** — 부풀리는 것보다 나쁘다."""
    _fake_parse(monkeypatch)
    folder = tmp_path / "0-5" / "x"
    folder.mkdir(parents=True)
    for i in range(3):
        (folder / f"{i}.json").write_text(
            json.dumps({"pob_export": "x", "raw": {"level": 100}}), encoding="utf-8"
        )

    out = agg.aggregate_concept("0-5", "x", base=tmp_path)
    assert out["sample"]["n"] == 3
    assert out["sample"]["superseded"] == 0
