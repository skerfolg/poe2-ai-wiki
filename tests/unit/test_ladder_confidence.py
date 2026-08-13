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
