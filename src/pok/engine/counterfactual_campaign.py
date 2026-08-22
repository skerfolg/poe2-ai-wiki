"""반사실 측정 캠페인 P1~P3 — 계획·멱등 측정·체크포인트 (M3, BACKLOG #73).

래더 코퍼스는 **채택된 것**만 담는다(positive only). 「이 노드를 빼면 얼마나
나빠지나」를 재서 negative를 만들면, 채택률과 곱해 「전원이 찍지만 빼도 손실 0.1%」
= **메타 습관**이 드러난다. 그게 갈아탈 수 있는 예산이다(#62).

**여기는 오케스트레이션만 한다** — 무엇을 뺄지 고르는 판단은 없다(철칙 3).
후보 열거는 `counterfactual.removable_nodes`(연결성이라는 결정적 규칙)가 하고,
이 모듈은 그 전량을 잰다. 「우선순위를 어떻게 줄 것인가」가 필요해지는 것은 교체
축이고(전수 46일), 그건 3층(LLM)의 몫이다.

## 저장 규약 (사용자 승인 2026-08-17)

```
<데이터 repo>/counterfactual/<시즌>/
  measure-plan.json      작업 목록 + 계보. **한 번 만들면 불변**이고 완전성 기준이다
  measure-status.json    완료 단위 — 재개는 여기를 보고 건너뛴다
  removals/<빌드 id>.json  빌드 1벌 = 파일 1개
```

**빌드당 파일 1개**는 래더 원시와 같은 이름 규약이다(`계정__캐릭터__갱신시각`).
재개 판정이 「파일 있으면 건너뛴다」로 끝나고, 큰 파일을 다시 쓰지 않아 append-only와
맞는다. ⛔ NDJSON 한 덩어리로 쌓으면 중단 지점에서 부분 기록 판정이 모호해진다.

⛔ **`knowledge/`(정본)에 쓰지 않는다** — 1층 관측은 재생성 가능한 파생이고, 정본
커밋을 측정 로그로 덮는다. 정본에 올라갈 것은 **2층 집계**(M4에서 레코드 타입 신설).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pok.artifacts.ladder import LadderError, ladder_dir
from pok.engine.corpus_fidelity import _snapshot_stamp
from pok.engine.tree.counterfactual import (
    _DEFAULT_STATS,
    evaluate_removals,
    removable_nodes,
)
from pok.engine.tree.graph import TreeGraph
from pok.pob.restore import spec_from_pob

PLAN = "measure-plan.json"
STATUS = "measure-status.json"
REMOVALS = "removals"
# 캠페인 축 — 하네스와 **같은 것을 쓴다**. 갈라 두면 한쪽만 넓혀도 모른다.
_STATS = _DEFAULT_STATS

# 데몬을 몇 벌마다 갈아 끼우나. **오래 산 데몬은 느려진다**(실측: 50벌 9.2초 →
# 250벌 이후 77초, 11배). 부팅이 2초뿐이라 50벌마다 갈아도 상각은 1벌당 0.04초다.
# 상수를 박는 대신 인자로도 뚫는다 — 「몇 벌이 적정인가」는 환경마다 다르다.
_DAEMON_RECYCLE = 50


def campaign_dir(season: str, *, base: Path | None = None) -> Path:
    """데이터 repo 안의 캠페인 자리. 래더 원시와 **같은 repo**다(체크포인트가 공유된다)."""
    return (base or ladder_dir()).parent / "counterfactual" / season


def build_id(doc: dict[str, Any]) -> str:
    """래더 원시 파일명과 같은 규약 — `계정__캐릭터__갱신시각`.

    ⚠ **`raw` 안을 본다.** `_record_path`는 poe.ninja가 준 **원본 문서**를 받는데,
    저장된 payload는 그것을 `raw`로 감싸고 위에는 계보(`concept`·`query`…)를 얹는다.
    감싼 쪽을 그대로 넘기면 계정·이름이 `None`이라 **모든 빌드가 같은 id로 뭉친다** —
    실측 2026-08-17: 계획의 `total`이 2,689이어야 하는데 **1**이 나왔다. 계획은
    완전성 기준이므로 이 한 줄이 캠페인 전체를 1벌로 축소시킨다.
    """
    from pok.artifacts.ladder import _record_path

    return _record_path(Path(), "runesofaldur", doc.get("raw") or doc, "x").stem


def _character_key(doc: dict[str, Any]) -> tuple[str, str]:
    """중복 판정은 **갱신시각을 뺀 (계정, 캐릭터)**로 한다.

    같은 캐릭터가 여러 컨셉 폴더에 있고, 수집 시점이 달라 갱신본이 갈리기도 한다
    (`sample.superseded` 참조). id로만 묶으면 같은 사람을 두 번 재게 된다 —
    `corpus_fidelity.survey`가 쓰는 기준과 같게 맞춘다(표본 수가 어긋나면 안 된다).
    """
    raw = doc.get("raw") or {}
    return (str(raw.get("account") or ""), str(raw.get("name") or ""))


def _unique_builds(season: str, *, base: Path | None = None) -> list[tuple[str, Path]]:
    """(빌드 id, 원시 경로) — 같은 캐릭터는 **처음 것 하나만**."""
    root = (base or ladder_dir()) / season
    if not root.exists():
        raise LadderError(f"수집된 시즌이 없다: {root}")
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, Path]] = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        for path in sorted(folder.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            key = _character_key(doc)
            if key in seen:
                continue
            seen.add(key)
            out.append((build_id(doc), path))
    return out


# ────────────────────────── P1. 계획 ──────────────────────────


def make_plan(
    season: str, *, base: Path | None = None, fidelity: Path | None = None
) -> dict[str, Any]:
    """작업 목록을 만든다. **한 번 만들면 불변**이고, 「다 했나」는 여기에만 묻는다.

    ⚠ 계보(`pob_commit`·P0 `usable`)를 **박아 넣는다.** 계획이 어느 전제에서 만들어졌는지가
    없으면 재개 판정을 할 수 없다 — 스냅샷이 바뀌면 서로 다른 계산기로 잰 값이 한
    데이터셋에 섞인다(재개 규약 2단계가 이 값을 대조한다).
    """
    stamp = _snapshot_stamp()
    builds = _unique_builds(season, base=base)
    usable: dict[str, Any] = {}
    src = fidelity or (campaign_dir(season, base=base) / "fidelity.json")
    if src.exists():
        usable = (json.loads(src.read_text(encoding="utf-8")) or {}).get("usable", {})
    return {
        "season": season,
        "axis": "removals",  # 교체 축은 전수 46일이라 이 계획에 없다(3층이 좁힌 뒤에)
        "provenance": {
            **stamp,
            # P0의 수치를 그대로 옮긴다 — 계획을 만든 전제가 무엇이었나
            "fidelity_usable": usable,
            "fidelity_source": src.name if src.exists() else "",
        },
        "units": [
            {"build": bid, "source": str(path.parent.name + "/" + path.name)}
            for bid, path in builds
        ],
        "total": len(builds),
    }


# ────────────────────────── P2. 측정 ──────────────────────────


def measure_build(
    graph: TreeGraph,
    doc: dict[str, Any],
    *,
    pob_commit: str,
    daemon: Any = None,
    stats: tuple[str, ...] = _STATS,
) -> dict[str, Any]:
    """빌드 1벌의 **제거 전량**을 잰다. 못 잰 것은 버리지 않고 사유로 남긴다.

    필수 3종(스킬 P2)이 여기서 붙는다:
      1. `pruned`가 비지 않은 측정은 **값을 쓰지 않는다** — 그건 「A를 뺀 효과」가
         아니라 「A + 알 수 없는 N개를 뺀 효과」다(철칙 4).
      2. `coverage: {measured, candidates}` — 부분 데이터셋이 전량으로 읽히는 것을 막는다.
      3. `pob_commit` — 무효화 키.
    """
    from pok.pob.buildxml import spec_from_dict

    restored = spec_from_pob(str(doc.get("pob_export") or ""))
    # ⚠ `validate_catalog=False`는 하네스(`corpus_counterfactuals`)와 **같은 선택**이다.
    #    켜 두면 아이템 부여 스킬을 든 빌드가 복원 단계에서 거부되어 표본에서 빠진다
    #    (실측 2026-08-16: 무작위 11벌 중 6벌). 여기서 재는 것은 **트리**이고 스킬은
    #    기준·변경안 양쪽에 똑같이 들어가므로 델타에 영향을 주지 않는다.
    spec = spec_from_dict(restored.spec, validate_catalog=False)
    candidates = removable_nodes(spec, graph)
    # 기준 스탯을 **행과 함께** 싣는다 — 델타만 실으면 손실을 비율로 못 만든다
    # (M4 실측 2026-08-18: 사이드카(baselines.ndjson)로 2,687벌을 따로 채워야 했다).
    # 데몬이 스펙을 캐시하므로 이 계산은 evaluate_removals의 기준 계산과 겹치지 않는다.
    #
    # ⚠ 행과 **같은 보호 수준**이어야 한다. 전직 없는 캐릭터(ascendancy='None', 재측정
    #   실측 3/2,689벌)는 기준 계산부터 죽는데, 여기서 예외가 새면 **파일 자체가 안
    #   쓰여** pending이 영원히 남는다 — 1차분은 같은 빌드를 「전 행 실패」로 기록하고
    #   넘어갔다. 기준을 못 재면 빈 dict로 두고 행들이 각자 사유를 남기게 한다.
    try:
        baseline = daemon.compute_build(spec).stats or {}
        rows = evaluate_removals(spec, graph, list(candidates.nodes), stats=stats, daemon=daemon)
        failed = ""
    except Exception as exc:
        # 빌드 통째의 실패도 **파일로 기록**한다 — 안 쓰면 pending이 영원히 남아
        # 다음 세션이 미완으로 읽는다. 실측 2026-08-20: 전직 없는 캐릭터 3벌이
        # `to_xml`의 전직 검증(#78, PR #84)에 걸려 기준 계산부터 죽었다. 1차분은
        # 검증이 없던 때라 「전 행 실패」로 기록되고 넘어갔었다 — 같은 결말을
        # 명시적으로 만든다. 실패 사유가 파일에 남으므로 조용한 결손이 아니다.
        baseline = {}
        rows = []
        failed = f"{type(exc).__name__}: {exc}"

    measured = [r for r in rows if r.measured and not r.pruned]
    return {
        "build": build_id(doc),
        "pob_commit": pob_commit,
        "baseline": {k: baseline.get(k, 0.0) for k in stats},
        # 빌드 통째 실패 사유 — 비어 있지 않으면 이 빌드의 관측은 0행이고 그 이유다
        "failed": failed,
        "restored": {
            "faithful": restored.faithful,
            "damage_comparable": restored.damage_comparable,
            "notes": list(restored.notes),
            "needs_decision": list(restored.needs_decision),
        },
        "tree": {
            "class_name": spec.class_name,
            "ascendancy": spec.ascendancy,
            "allocated": len(spec.tree_nodes),
        },
        # ⚠ 이 선언이 없으면 부분 데이터셋이 전량으로 읽힌다(BACKLOG #67의 재발 방지)
        #
        # `excluded`는 **후보에서 빠진 이유**다. 없으면 「할당 130개 중 21개를 쟀다」만
        # 남아 나머지 109개가 왜 빠졌는지 알 수 없다 — 그중 `graph_orphans`는
        # **연결 불요 주얼**(From Nothing 등, 코퍼스 48.8%) 때문에 길 없이 할당된
        # 정상 노드일 수 있다. 우리 그래프는 그걸 고아로 판정해 후보에서 빼는데,
        # 그 사실이 결과에 안 남으면 **없는 값이 0으로 읽힌다**(BACKLOG #87).
        # 실측 2026-08-18: 연결 불요 주얼 보유 빌드 39/40에서 고아 발생, 중앙 7개.
        "coverage": {
            "measured": len(measured),
            "candidates": len(candidates.nodes),
            "allocated": len(spec.tree_nodes),
            "excluded": {
                "graph_orphans": len(candidates.orphans),
                "blocked": len(candidates.blocked),
            },
            # 연결 불요 주얼 반경으로 **살아난** 노드 수(#87) — 0이 아니면 이 빌드의
            # 후보에는 길 없이 성립하는 노드가 섞여 있고, 그건 근거가 있는 정상이다
            "no_path_zone": len(candidates.no_path_zone),
        },
        "removals": [
            {
                "node_id": r.node_id,
                "name_en": r.name_en,
                "kind": r.kind,
                "points": r.points,
                "pool": r.pool,
                # 값은 **잰 것만** 싣는다 — pruned가 섰으면 비우고 사유를 남긴다
                "deltas": dict(r.deltas) if (r.measured and not r.pruned) else {},
                # 한쪽 실행에만 있던 축 — 0으로 메우지 않고 **왜 없는지 보이게** 남긴다.
                # 비어 있지 않으면 그 축은 이 관측에서 「0」이 아니라 「모름」이다 (#109)
                "unmeasured": list(r.unmeasured),
                "pruned": list(r.pruned),
                "failed": r.failed,
            }
            for r in rows
        ],
    }


def load_status(season: str, *, base: Path | None = None) -> dict[str, Any]:
    path = campaign_dir(season, base=base) / STATUS
    if not path.exists():
        return {"season": season, "done": []}
    return dict(json.loads(path.read_text(encoding="utf-8")))


def completed(season: str, *, base: Path | None = None) -> set[str]:
    """이미 결과 파일이 있는 빌드. **파일이 진짜 기록이다.**

    상태 파일은 편의이자 체크포인트이고, 소유자가 하나뿐이라 **다른 실행이 만든
    결과를 모른다**. 규약이 「빌드당 파일 1개 · 파일 있으면 건너뛴다」인 이유가
    이것이다 — 실측 2026-08-17: 상태 파일만 믿던 실행이 다른 프로세스가 이미 잰
    97벌을 끝에서 다시 재려 했다.
    """
    folder = campaign_dir(season, base=base) / REMOVALS
    if not folder.is_dir():
        return set()
    return {p.stem for p in folder.glob("*.json")}


def pending(
    plan: dict[str, Any], status: dict[str, Any], *, done_files: set[str] | None = None
) -> list[str]:
    """계획 빼기 완료. **계획에만 묻는다**(완전성 기준이 계획이다).

    완료 판정은 상태 파일 **또는** 결과 파일이다 — 둘 중 하나만 봐도 재개는 되지만,
    파일 쪽이 더 강하다(위 `completed` 참조).
    """
    done = set(status.get("done") or []) | (done_files or set())
    return [u["build"] for u in plan.get("units", []) if u["build"] not in done]


def write_result(season: str, result: dict[str, Any], *, base: Path | None = None) -> Path:
    """빌드 1벌 = 파일 1개. 원자적으로 쓴다 — 중단이 반쪽 파일을 남기면 재개가 틀린다."""
    folder = campaign_dir(season, base=base) / REMOVALS
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{result['build']}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    tmp.replace(path)
    return path


def check_resumable(plan: dict[str, Any]) -> str:
    """이어가도 되는가. 안 되면 **사유**를 낸다(빈 문자열이면 진행 가능).

    ⚠ 재개 규약 2단계: 계획의 `pob_commit`과 지금 스냅샷이 **다르면 이어가지 않는다.**
    서로 다른 계산기로 잰 값이 한 데이터셋에 섞이면 나중에 갈라낼 수 없다 — 겉보기가
    정상이라 사람이 못 잡는다(BACKLOG #58과 같은 형태: 검사가 스냅샷만 보고 출처를
    안 보면 조용히 틀린다). 그래서 **코드가 막는다**(철칙 5).
    """
    planned = str((plan.get("provenance") or {}).get("pob_commit") or "")
    now = str(_snapshot_stamp().get("pob_commit") or "")
    if not planned:
        return "계획에 pob_commit이 없다 — 어느 계산기로 잰 계획인지 모른다. 새 계획을 만들 것"
    if not now:
        return "지금 PoB 스냅샷을 못 읽는다 — 대조 없이 이어가면 섞인다"
    if planned != now:
        return (
            f"스냅샷이 다르다: 계획 {planned[:7]} vs 지금 {now[:7]} — "
            "이어가면 서로 다른 계산기로 잰 값이 한 데이터셋에 섞인다. "
            "사람에게 보고하고 새 계획으로 다시 시작할지 판정받을 것"
        )
    return ""


# ────────────────────────── CLI ──────────────────────────


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def _cli_plan(args: Any) -> int:
    out = campaign_dir(args.season) / PLAN
    if out.exists() and not args.force:
        print(
            json.dumps(
                {
                    "error": "계획이 이미 있다 — 계획은 **불변**이다(완전성 기준이므로)",
                    "path": str(out),
                    "how": "정말 다시 만들려면 --force. 그러면 완료분 판정 기준이 바뀐다",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    plan = make_plan(args.season)
    _write_json(out, plan)
    print(
        json.dumps(
            {
                "written": str(out),
                "total": plan["total"],
                "provenance": plan["provenance"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cli_status(args: Any) -> int:
    folder = campaign_dir(args.season)
    plan_path = folder / PLAN
    if not plan_path.exists():
        print(
            json.dumps(
                {"error": "계획이 없다 — plan부터", "path": str(plan_path)}, ensure_ascii=False
            )
        )
        return 1
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    status = load_status(args.season)
    left = pending(plan, status, done_files=completed(args.season))
    print(
        json.dumps(
            {
                "season": args.season,
                "total": plan["total"],
                "done": plan["total"] - len(left),
                "pending": len(left),
                "resumable": check_resumable(plan) or True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cli_measure(args: Any) -> int:
    from pok.common.paths import knowledge_dir
    from pok.pob.daemon import PobDaemon

    folder = campaign_dir(args.season)
    plan_path = folder / PLAN
    if not plan_path.exists():
        print(
            json.dumps(
                {"error": "계획이 없다 — plan부터", "path": str(plan_path)}, ensure_ascii=False
            )
        )
        return 1
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    blocked = check_resumable(plan)
    if blocked:
        print(json.dumps({"error": "이어갈 수 없다", "why": blocked}, ensure_ascii=False, indent=2))
        return 1

    status = load_status(args.season)
    # 상태 파일 + 결과 파일 **둘 다** 흡수한다 — 다른 실행이 만든 결과를 다시 재지 않는다
    have = completed(args.season)
    done: list[str] = sorted(set(status.get("done") or []) | have)
    left = pending(plan, status, done_files=have)
    if args.limit:
        left = left[: args.limit]
    by_build = {u["build"]: u["source"] for u in plan["units"]}
    graph = TreeGraph(knowledge_dir())
    commit = str((plan.get("provenance") or {}).get("pob_commit") or "")

    failed: list[dict[str, str]] = []
    daemon = PobDaemon()
    try:
        for i, bid in enumerate(left):
            # ⚠ **데몬을 주기적으로 갈아 끼운다.** 오래 살수록 느려진다 — 실측
            #    2026-08-17(같은 기계·동시 대조): 갓 띄운 데몬이 빌드당 6~7초인데
            #    6시간 45분·8,800계산을 지난 데몬은 **77초**였다(11배). 처음 50벌
            #    9.2초 → 150~250벌 36.8초 → 최근 50벌 76.9초로 단조 악화라, 그대로
            #    두면 전량이 7시간이 아니라 **2일**이 된다. 부팅은 2초뿐이므로
            #    상각이 압도적이다.
            if i and args.recycle and i % args.recycle == 0:
                daemon.close()
                daemon = PobDaemon()
                print(f"--- 데몬 재기동 ({args.recycle}벌마다) ---", flush=True)
            src = ladder_dir() / args.season / by_build[bid]
            try:
                doc = json.loads(src.read_text(encoding="utf-8"))
                result = measure_build(graph, doc, pob_commit=commit, daemon=daemon)
            except Exception as exc:  # 한 벌 실패로 캠페인을 멈추지 않는다 — 사유는 남긴다
                failed.append({"build": bid, "error": f"{type(exc).__name__}: {exc}"})
                continue
            write_result(args.season, result)
            done.append(bid)
            _write_json(folder / STATUS, {"season": args.season, "done": done})
            print(f"{len(done)}/{plan['total']}  {bid}  측정 {result['coverage']}", flush=True)
    finally:
        daemon.close()

    print(
        json.dumps(
            {"done": len(done), "total": plan["total"], "failed": failed},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cli(argv: list[str] | None = None) -> int:
    import argparse

    from pok.common.stdio import force_utf8_stdio

    force_utf8_stdio()
    parser = argparse.ArgumentParser(prog="python -m pok.engine.counterfactual_campaign")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="P1 작업 목록 — 한 번 만들면 불변")
    p.add_argument("--season", required=True)
    p.add_argument(
        "--force", action="store_true", help="이미 있어도 다시 만든다(완전성 기준이 바뀐다)"
    )
    p.set_defaults(fn=_cli_plan)

    m = sub.add_parser("measure", help="P2 멱등 측정 — 완료분은 건너뛴다")
    m.add_argument("--season", required=True)
    m.add_argument("--limit", type=int, default=0, help="이번 실행에서 잴 최대 빌드 수(0=전량)")
    m.add_argument(
        "--recycle",
        type=int,
        default=_DAEMON_RECYCLE,
        help="데몬을 몇 벌마다 갈아 끼우나(0=안 함). 오래 산 데몬은 11배까지 느려진다",
    )
    m.set_defaults(fn=_cli_measure)

    s = sub.add_parser("status", help="얼마나 남았나")
    s.add_argument("--season", required=True)
    s.set_defaults(fn=_cli_status)

    args = parser.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(_cli())
