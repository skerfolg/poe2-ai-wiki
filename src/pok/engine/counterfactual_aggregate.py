"""반사실 **2층 집계** — 빌드별 관측을 노드별 가치로 묶는다 (M4).

1층(`counterfactual_campaign`)은 빌드마다 「이 노드를 빼면 얼마나 나빠지나」를 잰다.
그건 **그 빌드의** 값이라 엔진이 읽을 수 없다 — 새 빌드를 짤 때 참고하려면 노드
하나에 대해 「여러 빌드에서 대체로 얼마나 아프더라」가 있어야 한다. 여기가 그 자리다.

## 왜 손실을 **비율**로 모으나

빌드마다 DPS가 100배씩 다르다. 절대 델타를 더하면 큰 빌드 몇 벌이 전부를 정한다.
손실률(제거 후 대비)은 **척도 불변**이라 빌드를 넘어 합칠 수 있다.

## 왜 축을 합치지 않나

아픔은 축마다 다르다 — 어떤 노드는 DPS만, 어떤 노드는 EHP만 아프다. 축을 하나로
접는 것은 **목적함수를 아는 쪽만** 할 수 있는 판단이고, 그건 `suggest_anchors`를
부르는 시점에 정해진다(철칙 3 · RC3). 그래서 축별 분포를 그대로 낸다.

## 왜 주얼 오염을 여기서 거르나

1층은 주얼을 꽂은 채 쟀으므로 **빌드별로는 옳다**. 섞이는 것은 집계할 때다 —
타임리스가 바꾼 노드, 반경 부여가 값을 얹은 노드는 「그 노드의 값」이 아니다
(`jewel_taint`, BACKLOG #81).

⛔ **관측이 0인 노드도 레코드를 만든다.** 「빼도 안 아프다」와 「재지 못했다」는 다른
말인데, 레코드가 없으면 후자가 전자로 읽힌다(BACKLOG 형태 ①).
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import statistics
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pok.common.paths import knowledge_dir
from pok.engine.counterfactual_campaign import REMOVALS, build_id, campaign_dir
from pok.engine.jewel_taint import classify
from pok.engine.ladder_aggregate import _tree_index
from pok.engine.tree.graph import TreeGraph
from pok.kb.store import write_shard

_ZERO_EPS = 1e-9  # PoB는 결정적 — 0은 진짜 0이다
BASELINES = "baselines.ndjson"


def load_baselines(season: str, *, base: Path | None = None) -> dict[str, dict[str, float]]:
    """빌드별 기준 스탯. **1층에 없다** — 델타만 싣고 있다(실측 2026-08-18).

    손실을 **비율**로 모으려면 기준이 있어야 하는데 1층 행은 델타뿐이라, 같은 스펙을
    PoB로 한 번 더 계산해 채운다(빌드당 0.58초). ⚠ `pob_commit`이 같아야 유효하다 —
    PoB가 바뀌면 그 기준은 다른 계산기의 값이다.

    ⛔ 다음 재측정 때는 **1층 행에 함께 싣는다**. 이 사이드카는 그때까지의 임시다.
    """
    path = campaign_dir(season, base=base) / BASELINES
    if not path.exists():
        return {}
    out: dict[str, dict[str, float]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            doc = json.loads(line)
            out[str(doc["build"])] = {k: float(v) for k, v in doc["stats"].items()}
    return out


@dataclass
class _Node:
    kind: str = ""
    label: str = ""
    points: list[int] = field(default_factory=list)
    axes: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    tainted: int = 0
    unmeasured: int = 0
    # 그룹 리프트를 **축마다** 센다 — DPS 조건을 정하는데 EHP가 움직인 것까지
    # 「작동」으로 세면 다른 축의 상관이 조건으로 둔갑한다.
    n_rows: Counter[str] = field(default_factory=Counter)
    n_fired: Counter[str] = field(default_factory=Counter)
    # 이 노드가 **작동한** 빌드들이 쓰던 메커니즘 그룹 (M4.5 조건 층)
    fired_groups: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    seen_groups: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))

    def groups_for(self, stat: str) -> dict[str, float]:
        """이 축에서 이 노드를 켜는 그룹 → 리프트.

        ⛔ **지금 이 값은 레코드에 싣지 않는다**(BACKLOG #85). 컨셉 홀드아웃에서
        일반화되지 않았다 — 재현 58.5% vs 기저 53.0%, 5회 중 2회는 기저보다 낮았다.
        코퍼스가 컨셉 112종에 50벌씩으로 잘려 있어, 그 안에서만 성립하는 상관이 조건처럼
        보인 것이다. 계산은 **버리지 않고 남긴다** — 표본 설계를 고치거나 조건을
        PoB로 직접 재게 되면 그때 다시 쓴다.

        ⛔ **대조군을 본다.** P(작동 | 그룹 있음) / P(작동 | 그룹 없음). 안 보면
        노드마다 16~18개가 전부 붙는다(실측 2026-08-18) — `마나`는 젬 55종이라
        거의 모든 빌드가 해당해서, 「작동한 빌드가 이 그룹을 썼다」는 늘 참이다.

        ⚠ **그룹끼리 겹치는 것은 정상이다**(사용자 정리 2026-08-18). 빌드는 여러
        그룹의 합이고, 고르는 용도로는 상관된 그룹이 해롭지 않다 — 함성과 격노가
        늘 함께 온다면 어느 쪽으로 골라도 같은 빌드가 걸린다. 인과를 가리는 것은
        이 층의 일이 아니다.
        """
        rows, fired = self.n_rows.get(stat, 0), self.n_fired.get(stat, 0)
        out: dict[str, float] = {}
        for name, seen in self.seen_groups.get(stat, Counter()).items():
            without = rows - seen
            hit = self.fired_groups.get(stat, Counter()).get(name, 0)
            if seen < 5 or without < 5:  # 양쪽 표본이 있어야 비교가 성립한다
                continue
            p_with = hit / seen
            p_without = (fired - hit) / without
            if p_with < 0.3:
                continue
            lift = float("inf") if p_without == 0 else p_with / p_without
            if lift >= 2.0:
                out[name] = round(min(lift, 999.0), 2)
        return out


def _spread(values: list[float]) -> dict[str, float]:
    """p10 · 중앙 · p90. ⛔ 평균을 쓰지 않는다 — 한 벌이 끌고 간다."""
    if not values:
        return {"p10": 0.0, "median": 0.0, "p90": 0.0}
    ordered = sorted(values)
    last = len(ordered) - 1
    return {
        "p10": round(ordered[int(last * 0.1)], 4),
        "median": round(statistics.median(ordered), 4),
        "p90": round(ordered[int(last * 0.9)], 4),
    }


def _loss_pct(base: float, delta: float) -> float | None:
    """제거 시 손실률(%). 양수 = 빼면 나빠진다. 기준이 0이면 비율이 없다."""
    if base is None or abs(base) < _ZERO_EPS:
        return None
    return -delta / base * 100.0


def _build_groups(spec: Any, groups: dict[str, Any]) -> set[str]:
    """이 빌드가 든 젬 → 메커니즘 그룹 (M4.5 조건 층)."""
    from pok.engine.mechanism_groups import groups_of

    names = []
    for group in spec.skills:
        for gem in getattr(group, "gems", ()) or ():
            name = getattr(gem, "name", None) or getattr(gem, "skill_id", "")
            if name:
                names.append(str(name))
    return groups_of(names, groups)


def _spec_of(doc: dict[str, Any]) -> Any:
    from pok.pob.buildxml import spec_from_dict
    from pok.pob.restore import spec_from_pob_xml

    xml = zlib.decompress(base64.urlsafe_b64decode(doc["pob_export"])).decode("utf-8")
    return spec_from_dict(spec_from_pob_xml(xml, assume_stages=1).spec, validate_catalog=False)


def collect(
    season: str,
    graph: TreeGraph,
    *,
    raw_root: Path,
    base: Path | None = None,
    limit: int | None = None,
) -> tuple[dict[int, _Node], dict[str, int], str]:
    """1층 결과를 훑어 노드별로 모은다. 반환은 (노드별, 시즌 커버리지, pob_commit)."""
    from pok.engine.mechanism_groups import derive

    results = campaign_dir(season, base=base) / REMOVALS
    baselines = load_baselines(season, base=base)
    groups = derive()
    if not baselines:
        raise SystemExit(
            f"⛔ 기준값이 없다 ({campaign_dir(season, base=base) / BASELINES}) — "
            "손실을 비율로 모을 수 없다. 1층 행은 델타만 싣는다(2026-08-18 확인). "
            "먼저 `python -m pok.engine.counterfactual_aggregate baseline --season <시즌>`"
        )
    nodes: dict[int, _Node] = defaultdict(_Node)
    seen: set[str] = set()
    cov = {"builds_measured": 0, "rows_total": 0, "rows_kept": 0}
    pob_commit = ""

    for path in sorted(raw_root.glob("*/*.json")):
        if limit is not None and cov["builds_measured"] >= limit:
            break
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            bid = build_id(doc)
            if bid in seen:
                continue
            seen.add(bid)
            result_path = results / f"{bid}.json"
            if not result_path.exists():
                continue
            result = json.loads(result_path.read_text(encoding="utf-8"))
            spec = _spec_of(doc)
        except Exception:  # 복원 실패는 표본에서 빠질 뿐이다 (커버리지에 안 센다)
            continue

        base_stats = baselines.get(bid)
        if base_stats is None:
            continue  # 기준을 못 구한 빌드는 비율을 못 낸다 — 세지도 않는다
        # 이 빌드가 쓰는 메커니즘 — 노드의 **조건**을 짚는 데 쓴다(M4.5)
        build_groups = _build_groups(spec, groups)
        taint = classify(spec, graph)
        pob_commit = pob_commit or str(result.get("pob_commit") or "")
        cov["builds_measured"] += 1
        # ⚠ fail-closed: 오염 범위를 모르는 빌드는 통째로 뺀다(반경을 못 읽은 주얼)
        usable = taint.usable

        for row in result["removals"]:
            nid = int(row["node_id"])
            here = nodes[nid]
            here.kind = here.kind or str(row.get("kind") or "?")
            here.label = here.label or str(row.get("name_en") or f"node {nid}")
            cov["rows_total"] += 1
            if not row["deltas"]:
                here.unmeasured += 1
                continue
            if not usable or nid in taint.tainted_nodes:
                here.tainted += 1
                continue
            cov["rows_kept"] += 1
            here.points.append(int(row.get("points") or 1))
            # **축마다** 따로 센다 — 축을 안 가리면 다른 축의 상관이 조건이 된다
            for stat, delta in row["deltas"].items():
                moved = abs(float(delta)) > 0
                here.n_rows[stat] += 1
                here.n_fired[stat] += int(moved)
                for name in build_groups:
                    here.seen_groups[stat][name] += 1
                    if moved:
                        here.fired_groups[stat][name] += 1
            for stat, delta in row["deltas"].items():
                loss = _loss_pct(base_stats.get(stat, 0.0), float(delta))
                if loss is not None and math.isfinite(loss):
                    here.axes[stat].append(loss)
    return dict(nodes), cov, pob_commit


def build_records(
    season: str,
    nodes: dict[int, _Node],
    coverage: dict[str, int],
    *,
    pob_commit: str,
    tree_nodes: int,
    refs: dict[int, tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """노드별 `NodeValue` 레코드. **관측 0도 만든다** — 없으면 0으로 읽힌다.

    ⚠ `refs`(node_id → KB id)를 반드시 넘긴다. **이게 조인 키다** — `UsageProfile`의
    채택률은 `passive.<슬러그>` ref로 실려 있어(`observed.passives[].ref`) node_id로는
    못 잇는다. 이 층의 존재 이유가 「채택률 곱하기 손실률」로 **메타 습관**을 드러내는
    것이라(#62), 키가 없으면 두 층이 나란히 놓여 있기만 하고 곱해지지 않는다.
    """
    index = refs if refs is not None else _tree_index()
    observed = sum(1 for n in nodes.values() if n.points)
    cov = {
        "tree_nodes": tree_nodes,
        "nodes_observed": observed,
        "builds_measured": coverage["builds_measured"],
        "rows_kept": coverage["rows_kept"],
        "rows_total": coverage["rows_total"],
    }
    basis = (
        f"래더 {season} 제거 반사실 {coverage['rows_kept']:,}행 "
        f"({coverage['builds_measured']:,}벌) · 주얼 오염 제외(BACKLOG #81)"
    )
    out: list[dict[str, Any]] = []
    for nid, node in sorted(nodes.items()):
        axes: dict[str, dict[str, Any]] = {}
        for stat, values in sorted(node.axes.items()):
            if not values:
                continue
            # ⛔ **작동한 관측만 따로 낸다.** 전 빌드를 뭉친 중앙값은 조건부 노드를
            #    「쓸모없는 노드」와 같은 0으로 만든다(#84). 실측 2026-08-18:
            #    Mind Over Matter는 전체 중앙 거의 0인데 작동률 1.4%·작동시 36.6%고,
            #    Gathering Winds는 어느 빌드에서도 안 움직인다 — 둘이 갈려야 한다.
            active = [v for v in values if abs(v) >= _ZERO_EPS]
            zero_share = round((len(values) - len(active)) / len(values) * 100, 2)
            axes[stat] = {
                "n": len(values),
                "loss_pct": _spread(values),
                "zero_share": zero_share,
                "active_share": round(100.0 - zero_share, 2),
                "n_active": len(active),
                "when_active": _spread(active),
            }
        ref, kb_kind = index.get(nid, ("", ""))
        node_block: dict[str, Any] = {
            "node_id": nid,
            "kind": node.kind or kb_kind or "?",
            "label": node.label or f"{nid}",
        }
        if ref:  # KB에 없는 노드(트리 수집 갭)는 ref 없이 node_id로만 잡는다
            node_block["ref"] = ref
        data = {
            "season": season,
            "node": node_block,
            "sample": {
                "n": len(node.points),
                "excluded": {"jewel_tainted": node.tainted, "unmeasured": node.unmeasured},
                "basis": basis,
                "pob_commit": pob_commit or "unknown",
                "coverage": cov,
            },
            "points": _spread([float(p) for p in node.points]),
            "axes": axes,
        }
        out.append(
            {
                # id는 **점 하나 + `[a-z0-9-]`**만 받는다 — 시즌과 번호를 대시로 잇는다
                "id": f"node-value.{season}-{nid}",
                "type": "NodeValue",
                "name": {
                    "ko": f"{node.label} 제거 가치 ({season})",
                    "en": f"{node.label} removal value ({season})",
                },
                "tags": ["node-value", season, node.kind or "?"],
                "data": data,
                "verification": "COMMUNITY",
                "sources": [
                    {
                        "src": "community",
                        "ref": "https://poe.ninja/poe2/builds",
                        "note": f"PoB 실측 제거 델타 집계 · pob {pob_commit or 'unknown'}",
                    }
                ],
            }
        )
    return out


def backfill_baselines(
    season: str,
    *,
    raw_root: Path,
    base: Path | None = None,
    limit: int | None = None,
    stats: tuple[str, ...] = ("CombinedDPS", "TotalEHP", "Life"),
) -> int:
    """빌드별 기준 스탯을 PoB로 채운다 — **이미 잰 빌드만**, 이어서 돌 수 있게.

    ⚠ 임시다. 다음 재측정에서 1층 행이 기준을 함께 실으면 이 명령은 필요 없다.
    """
    from pok.pob.daemon import PobDaemon

    out = campaign_dir(season, base=base) / BASELINES
    have = load_baselines(season, base=base)
    results = campaign_dir(season, base=base) / REMOVALS
    done = failed = 0
    seen: set[str] = set()
    daemon: Any = None
    # ⚠ **데몬을 갈아 끼운다.** 오래 산 데몬은 느려지다 죽는다(캠페인 실측: 50벌 9.2초 →
    #   250벌 이후 77초). 실측 2026-08-18: 재활용 없이 돌렸더니 489벌에서 데몬이 죽고
    #   **나머지를 전부 조용히 건너뛴 채 성공으로 보고했다** — 예외를 삼킨 탓이다.
    recycle = 50
    try:
        with out.open("a", encoding="utf-8", newline="\n") as sink:
            for path in sorted(raw_root.glob("*/*.json")):
                if limit is not None and done >= limit:
                    break
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                    bid = build_id(doc)
                    if bid in seen or bid in have or not (results / f"{bid}.json").exists():
                        continue
                    seen.add(bid)
                except Exception:
                    continue
                if daemon is None or done % recycle == 0:
                    if daemon is not None:
                        daemon.close()
                    daemon = PobDaemon()
                    daemon.__enter__()
                try:
                    got = daemon.compute_build(_spec_of(doc)).stats or {}
                except Exception:
                    # ⛔ 조용히 넘기지 않는다 — 연달아 실패하면 데몬이 죽은 것이고,
                    #    그대로 두면 「전부 처리했다」는 거짓 보고가 된다.
                    failed += 1
                    if failed % 20 == 0:
                        print(f"  ⚠ 연속 실패 {failed}건 — 데몬을 다시 세운다", flush=True)
                        daemon.close()
                        daemon = None
                    continue
                failed = 0
                row = {"build": bid, "stats": {k: got.get(k, 0.0) for k in stats}}
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                sink.flush()
                done += 1
                if done % 100 == 0:
                    print(f"  기준값 {done}벌", flush=True)
    finally:
        if daemon is not None:
            daemon.close()
    return done


def main(argv: list[str] | None = None) -> int:
    # 윈도우 콘솔은 기본이 cp949라 한글 note가 그대로 죽는다 — 진입점마다 고정한다
    from pok.common.stdio import force_utf8_stdio

    force_utf8_stdio()
    ap = argparse.ArgumentParser(description="반사실 2층 집계 — 노드별 NodeValue 생성")
    ap.add_argument("command", choices=["aggregate", "baseline"], nargs="?", default="aggregate")
    ap.add_argument("--season", required=True)
    ap.add_argument("--raw-root", type=Path, default=None, help="래더 원시 폴더")
    ap.add_argument("--limit", type=int, default=None, help="빌드 N벌만 (검증용)")
    ap.add_argument("--out", type=Path, default=None, help="기본 = knowledge/game-data/tree/")
    args = ap.parse_args(argv)

    kb = knowledge_dir()
    raw_root = args.raw_root or Path("artifacts/ingest-raw/ladder") / args.season
    if args.command == "baseline":
        got = backfill_baselines(args.season, raw_root=raw_root, limit=args.limit)
        print(json.dumps({"baselines_added": got}, ensure_ascii=False))
        return 0
    graph = TreeGraph(kb)
    nodes, cov, pob_commit = collect(args.season, graph, raw_root=raw_root, limit=args.limit)
    records = build_records(
        args.season, nodes, cov, pob_commit=pob_commit, tree_nodes=len(graph.nodes)
    )
    linked = sum(1 for r in records if "ref" in r["data"]["node"])
    out = args.out or (kb / "game-data" / "tree")
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"node-values-{args.season}.ndjson"
    # ⛔ 직접 write_text 하지 않는다 — 스키마 검사가 **쓴 뒤** 남의 시험에서 터진다.
    #    store API가 쓰고 곧바로 전량 로드로 검증한다(깨진 채로 안 남는다).
    report = write_shard(path, records)
    print(
        json.dumps(
            {
                "records": len(records),
                "kb_linked": linked,
                "added": len(report.added),
                "updated": len(report.updated),
                "coverage": cov,
                "out": str(path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
