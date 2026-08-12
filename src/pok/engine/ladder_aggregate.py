"""수집된 PoB 코드 N벌을 겹쳐 채택률을 낸다 (#67 · 사용자 승인 2026-08-12).

**왜 engine인가**: 이 일은 `artifacts`(파일 읽기)와 `pob`(코드 파싱)을 **둘 다**
필요로 하는데 그 둘은 같은 층이라 서로 import할 수 없다(의존 방향 단방향 —
import-linter가 강제한다). 둘을 쓰는 조합은 한 층 위, 즉 여기다.

**철칙 3과 어긋나지 않는다**: 엔진은 결정적이어야 하고 빌드 솔버·생성 판단을
넣지 않는다. 여기서 하는 것은 **세는 일**뿐이다 — "몇 %부터 필수인가" 같은
임계값은 표본 크기에 따라 달라지는 판단이라 **코드에 박지 않았다**. 그건
해석 층(skills·에이전트)의 몫이다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pok.artifacts.ladder import LadderError, ladder_dir
from pok.pob.parse import parse_pob

# ────────────────────── 겹쳐 읽기 (안층) ──────────────────────
#
# 같은 컨셉 N벌을 겹치면 축마다 **불변(N/N=필수) vs 가변(3/N=자유석)**이 갈린다.
# 그 차이가 「어디까지 바꿔도 되는가」 = 생성에 필요한 문법이다. 그래서 여기서
# 하는 일은 세는 것뿐이고, 무엇이 필수인지 **판정하지 않는다** — 임계값을 코드에
# 박으면 그게 곧 해석이고, 표본이 작을 때 조용히 틀린다.


def _tally(rows: list[list[str]]) -> list[dict[str, Any]]:
    """등장한 빌드 수를 센다. 한 빌드 안에서 여러 번 나와도 **1로 센다** —
    "몇 명이 쓰나"를 묻는 것이지 "몇 번 끼나"가 아니다."""
    n = len(rows)
    counts: dict[str, int] = {}
    for row in rows:
        for name in set(row):
            counts[name] = counts.get(name, 0) + 1
    return [
        {"ref": name, "share": round(cnt * 100 / n, 1), "count": cnt}
        for name, cnt in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def aggregate_concept(
    season: str, concept: str, *, base: Path | None = None, basis: str = ""
) -> dict[str, Any]:
    """수집된 PoB 코드들을 겹쳐 `data.observed` 꼴로 낸다.

    표본이 작으면 작다고 말한다 — `sample.n`이 그것이고, `count`를 함께 실어
    "3/10"이 "30%"로 뭉개지지 않게 한다.
    """
    folder = (base or ladder_dir()) / season / concept
    files = sorted(folder.glob("*.json"))
    if not files:
        raise LadderError(f"수집된 것이 없다: {folder}")

    gems: list[list[str]] = []
    items: list[list[str]] = []
    for path in files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        summary = parse_pob(doc["pob_export"])
        gems.append([g for grp in (summary.skill_groups or []) for g in (grp.gems or ())])
        items.append([getattr(it, "name", "") or "" for it in (summary.items or [])])

    return {
        "sample": {
            "n": len(files),
            "unit": "sampled-builds",
            "basis": basis or f"poe.ninja 래더 PoB 실측 — {season}/{concept} {len(files)}벌",
        },
        "gems": _tally(gems),
        "items": _tally([[i for i in row if i] for row in items]),
    }


# ──────────────────────────── CLI ────────────────────────────
#
# 저비용 에이전트(코덱스·저티어)가 재량 없이 돌릴 수 있어야 한다. 그래서 판단이
# 필요한 값은 **기본값을 주지 않고 필수 인자로 만든다** — 기본값을 주면 그게
# 조용히 판단이 되고, 표본이 모자란 채로 정본에 들어간다.


def _cli(argv: list[str] | None = None) -> int:
    import argparse

    from pok.artifacts.ladder import collect

    p = argparse.ArgumentParser(prog="python -m pok.engine.ladder_aggregate")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="컨셉 하나의 상위 N명 PoB 코드를 쌓는다")
    c.add_argument("--league", required=True, help="리그 슬러그 (예: runesofaldur)")
    c.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="컨셉 정의. 반복 가능 (예: --filter class=Chronomancer)",
    )
    c.add_argument("--limit", type=int, default=10)

    a = sub.add_parser("aggregate", help="쌓인 코드를 겹쳐 data.observed를 낸다")
    a.add_argument("--season", required=True, help="예: 0-5")
    a.add_argument("--concept", required=True, help="예: class-Chronomancer")
    a.add_argument(
        "--min-sample",
        type=int,
        required=True,
        help="이 표본 수 미만이면 **중단한다**. 기본값이 없다 — 표본이 몇 벌이어야 "
        "믿을 만한가는 게임 지식 판단이라 호출자가 정한다",
    )
    a.add_argument(
        "--min-count",
        type=int,
        default=2,
        help="이 개수 미만으로 겹친 항목은 싣지 않는다(작은 표본의 꼬리는 노이즈다)",
    )

    args = p.parse_args(argv)

    if args.cmd == "collect":
        filters: dict[str, str] = {}
        for item in args.filter:
            if "=" not in item:
                print(f"오류: --filter는 KEY=VALUE 꼴이어야 한다: {item!r}")
                return 2
            k, v = item.split("=", 1)
            filters[k] = v
        report = collect(args.league, filters=filters, limit=args.limit)
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return 0

    observed = aggregate_concept(args.season, args.concept)
    n = observed["sample"]["n"]
    if n < args.min_sample:
        print(
            json.dumps(
                {
                    "error": "표본 부족",
                    "have": n,
                    "need": args.min_sample,
                    "how": "collect를 --limit 올려 더 모으거나, "
                    "--min-sample을 낮출 근거를 사람에게 확인할 것",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    for key in list(observed):
        if key != "sample":
            observed[key] = [e for e in observed[key] if e["count"] >= args.min_count]
    print(json.dumps(observed, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
