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
import re
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
        # 빈 이름을 거르지 않으면 ''가 한 항목으로 잡혀 스키마(minLength 1)에 걸린다 —
        # PoB 코드에 이름 없는 젬 슬롯이 실제로 들어 있다(실측).
        for name in {s.strip() for s in row if s and s.strip()}:
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
    ascendancies: list[list[str]] = []
    for path in files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        summary = parse_pob(doc["pob_export"])
        gems.append([g for grp in (summary.skill_groups or []) for g in (grp.gems or ())])
        items.append([getattr(it, "name", "") or "" for it in (summary.items or [])])
        asc = getattr(summary, "ascendancy", None) or doc.get("raw", {}).get("class")
        ascendancies.append([str(asc)] if asc else [])

    return {
        "sample": {
            "n": len(files),
            "unit": "sampled-builds",
            "basis": basis or f"poe.ninja 래더 PoB 실측 — {season}/{concept} {len(files)}벌",
        },
        "gems": _tally(gems),
        "items": _tally([[i for i in row if i] for row in items]),
        # 표본의 어센던시 구성. A군(메커니즘 축)에서 이게 없으면 한 클래스가 표본을
        # 독점했는데 「클래스를 넘는 공통점」으로 읽힌다 — 조용한 거짓말이다.
        "_class_spread": _tally([r for r in ascendancies if r]),
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

    pr = sub.add_parser("profile", help="A군 — 메커니즘 동반 프로파일(UsageProfile)을 만든다")
    pr.add_argument("--season", required=True)
    pr.add_argument("--concept", required=True)
    pr.add_argument("--anchor", required=True, help="KB 실존 id (예: mechanic.totems)")
    pr.add_argument("--label", required=True, help="사람이 읽을 이름 (예: 토템 (Totem))")
    pr.add_argument("--filter", action="append", default=[], metavar="KEY=VALUE")
    pr.add_argument("--min-sample", type=int, required=True)
    pr.add_argument("--min-count", type=int, default=3)
    pr.add_argument("--write", action="store_true", help="정본에 파일로 쓴다(없으면 stdout만)")

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

    if args.cmd == "profile":
        return _cli_profile(args)

    observed = aggregate_concept(args.season, args.concept)
    observed.pop("_class_spread", None)
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


def profile_id_slug(concept: str) -> str:
    """수집 디렉터리 이름 → **레코드 id로 쓸 수 있는** 슬러그.

    둘은 같은 문자열이 될 수 없다. 디렉터리 이름은 `_safe()`가 만드는데 공백을
    `_`로 바꾸고 필터 여러 개를 `__`로 잇는다(`skills-Herald_of_Ice`). 그런데
    envelope의 `entityId`는 `[a-z0-9][a-z0-9-]*`만 받는다 — `_`가 없다.
    그래서 **값이 두 단어 이상인 컨셉은 전부** id가 스키마에 걸린다(실측
    2026-08-12: `skills=Herald of Ice`에서 정본이 깨져 수집이 중단됐다.
    앵커 표 8종 중 5종이 여기 해당한다).

    디렉터리 이름은 고치지 않는다 — 원시는 이미 그 이름으로 데이터 repo에
    쌓였고 편집·삭제가 금지다. 변환은 **id를 만드는 이 지점에서만** 한다.
    """
    return re.sub(r"[^a-z0-9]+", "-", concept.lower()).strip("-")


def _parse_filters(items: list[str]) -> dict[str, str] | None:
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            print(f"오류: --filter는 KEY=VALUE 꼴이어야 한다: {item!r}")
            return None
        k, v = item.split("=", 1)
        out[k] = v
    return out


def _cli_profile(args) -> int:
    from pok.common.paths import knowledge_dir
    from pok.kb.store import KBValidationError, KBWriteError, load, write_record

    # 앵커가 KB에 없으면 **여기서 멈춘다**. 파일을 쓴 뒤에 알면 정본이 잠깐 깨지고,
    # 코덱스는 그 실패를 보고 되돌릴 판단을 못 한다.
    if args.anchor not in load().records:
        print(
            json.dumps(
                {
                    "error": "앵커가 KB에 없다",
                    "anchor": args.anchor,
                    "how": "search_kb로 실존 id를 확인할 것. "
                    "못 찾으면 사람에게 보고(임의 생성 금지)",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    query = _parse_filters(args.filter)
    if query is None:
        return 2

    # 컨셉 이름은 손으로 옮겨 적는 값이라 어긋나기 쉽다(디렉터리는 공백이 `_`다).
    # 역추적 붙임 없이 트레이스백만 내면 저비용 에이전트가 「수집이 실패했다」로 읽는다.
    try:
        record = build_usage_profile(
            args.season,
            args.concept,
            anchor_ref=args.anchor,
            anchor_label=args.label,
            query=query,
        )
    except LadderError as exc:
        season_dir = ladder_dir() / args.season
        have = (
            sorted(p.name for p in season_dir.iterdir() if p.is_dir())
            if (season_dir.exists())
            else []
        )
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "concept": args.concept,
                    "available": have,
                    "how": "--concept은 수집 디렉터리 이름과 **정확히** 같아야 한다 "
                    "(공백은 `_`다 — 예: skills-Herald_of_Ice). "
                    "목록에 없으면 1단계 collect부터 다시 할 것",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    data = record["data"]
    n = data["observed"]["sample"]["n"]
    if n < args.min_sample:
        print(
            json.dumps(
                {"error": "표본 부족", "have": n, "need": args.min_sample},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    for key in list(data["observed"]):
        if key != "sample":
            data["observed"][key] = [
                e for e in data["observed"][key] if e["count"] >= args.min_count
            ]

    if args.write:
        # 파일명은 id와 같은 슬러그다 — 둘이 갈리면 나중에 id로 파일을 못 찾는다.
        out = (
            knowledge_dir()
            / "game-data"
            / "usage-profiles"
            / f"{profile_id_slug(f'{args.season}-{args.concept}')}.json"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        # 정본 쓰기는 store API로만 — 직접 write_text하면 스키마 검사가 **쓴 뒤**
        # 남의 테스트에서 터진다. 실측 2026-08-12: 깨진 레코드가 정본에 남은 채
        # 수집 작업이 통째로 중단됐다(되돌릴 판단까지 저비용 에이전트 몫이 됐다).
        prior = out.read_text(encoding="utf-8") if out.exists() else None
        try:
            write_record(out, record)
        except (KBValidationError, KBWriteError) as exc:
            # 되돌린다 — 갱신이었다면 **이전 정본을 되살린다**(지우면 멀쩡하던 게 사라진다)
            if prior is None:
                out.unlink(missing_ok=True)
            else:
                out.write_text(prior, encoding="utf-8")
            print(
                json.dumps(
                    {
                        "error": "정본 검증 실패 — 쓰지 않았다",
                        "id": record["id"],
                        "detail": str(exc)[:800],
                        "how": "원시는 그대로 있다. 사유를 그대로 사람에게 보고할 것",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        print(f"기록: {out}")
        print(f"클래스 구성: {[(e['ref'], e['count']) for e in data['class_spread']]}")
        return 0

    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def build_usage_profile(
    season: str,
    concept: str,
    *,
    anchor_ref: str,
    anchor_label: str,
    query: dict[str, str],
    base: Path | None = None,
) -> dict[str, Any]:
    """A군(메커니즘 축) 레코드를 만든다.

    Build는 「이 빌드가 어떻게 생겼나」에, 이건 「이 메커니즘을 쓰면 무엇이 따라오나」에
    답한다. 표본에 클래스가 섞여 있는 것이 **결함이 아니라 요점**이다 — 클래스를 넘어
    따라붙는 것이 곧 이식 가능한 문법이다.

    ⚠ `class_spread`를 반드시 함께 낸다. 한 클래스가 표본을 독점했는데 「클래스를
    넘는 공통점」으로 읽히면 프로파일이 조용히 거짓말을 한다.
    """
    agg = aggregate_concept(season, concept, base=base)
    spread = agg.pop("_class_spread", [])
    return {
        # envelope의 entityId는 `[a-z0-9-]`만 받는다 — 디렉터리 이름을 그대로 쓰면 안 된다
        "id": f"usage-profile.{profile_id_slug(f'{season}-{concept}')}",
        "type": "UsageProfile",
        "name": {
            "ko": f"{anchor_label} 동반 프로파일 ({season})",
            "en": f"{anchor_label} usage profile ({season})",
        },
        "tags": ["usage-profile", season],
        "data": {
            "season": season.replace("-", "."),
            "anchor": {"ref": anchor_ref, "label": anchor_label},
            "query": query,
            "class_spread": spread,
            "observed": agg,
        },
        "relations": [{"rel": "uses", "target": anchor_ref}],
        "verification": "COMMUNITY",
        "sources": [
            {
                "src": "community",
                "ref": "https://poe.ninja/poe2/builds",
                "patch": "0.5.4b",
                "note": f"래더 PoB 실측 — 질의 {query}",
            }
        ],
    }


if __name__ == "__main__":
    raise SystemExit(_cli())
