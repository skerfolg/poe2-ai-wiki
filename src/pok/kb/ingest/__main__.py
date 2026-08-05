"""ingest CLI — kb-ingest 스킬이 호출하는 진입점 (KI-7: 수집=코드).

사용:
  python -m pok.kb.ingest plan   --patch 0.5.4b
  python -m pok.kb.ingest fetch  --patch 0.5.4b [--limit N] [--rate 1.0] [--lang us kr]
  python -m pok.kb.ingest status --patch 0.5.4b
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pok.common.paths import project_root
from pok.kb.ingest.fetch import run_fetch, status_report
from pok.kb.ingest.plan import build_plan


def _raw_dir(patch: str) -> Path:
    return project_root() / "artifacts" / "ingest-raw" / patch


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pok.kb.ingest")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="목록 페이지 수집 → fetch-plan.json (이미 있으면 불변)")
    p_plan.add_argument("--patch", required=True)
    p_plan.add_argument("--category", nargs="*", default=None)
    p_plan.add_argument(
        "--extend", nargs="*", default=None, help="확정 plan에 새 카테고리 append (append-only)"
    )

    p_fetch = sub.add_parser("fetch", help="계획 항목 수집 (멱등·체크포인트·레이트리밋)")
    p_fetch.add_argument("--patch", required=True)
    p_fetch.add_argument("--limit", type=int, default=None)
    p_fetch.add_argument("--rate", type=float, default=1.0)
    p_fetch.add_argument("--lang", nargs="*", default=None)

    p_status = sub.add_parser("status", help="계획 대비 진행 요약")
    p_status.add_argument("--patch", required=True)

    p_proc = sub.add_parser("process", help="parse→match→KI-8 판정→리포트 (오프라인)")
    p_proc.add_argument("--patch", required=True)

    p_merge = sub.add_parser("merge", help="수록 판정분 → knowledge/ 기록 (④, 승인 후에만)")
    p_merge.add_argument("--patch", required=True)

    p_oil = sub.add_parser("oils", help="성유(액체 감정) 부여 정보: fetch|apply")
    p_oil.add_argument("--patch", required=True)
    p_oil.add_argument("step", choices=["fetch", "apply"])

    p_uni = sub.add_parser("uniques", help="유니크 아이템: fetch|process|merge")
    p_uni.add_argument("--patch", required=True)
    p_uni.add_argument("step", choices=["fetch", "process", "merge"])

    p_mods = sub.add_parser("mods", help="베이스+모드 풀(④): process (PoB 덤프 소스, 오프라인)")
    p_mods.add_argument("--patch", required=True)
    p_mods.add_argument("step", choices=["process", "merge", "catalog"])

    p_cur = sub.add_parser("currency", help="화폐 아이템(④ 보강): merge (Stackable_Currency 원시)")
    p_cur.add_argument("--patch", required=True)

    p_ail = sub.add_parser(
        "ailments", help="상태이상·축적 계열 전량 수록 (오프라인, PoB Data.lua·Misc.lua)"
    )
    p_ail.add_argument("--patch", required=True)

    p_me = sub.add_parser(
        "meta-energy", help="메타 젬 에너지 규칙 수록 (오프라인, ingest-raw Stats 재파싱)"
    )
    p_me.add_argument("--patch", required=True)

    p_gc = sub.add_parser(
        "gem-costs", help="젬 코스트·점유 전수 수록 (오프라인, ingest-raw Stats 재파싱)"
    )
    p_gc.add_argument("--patch", required=True)

    p_gcol = sub.add_parser(
        "gem-colors", help="보조 젬 색상(요구 속성) 수록 (오프라인, PoB 젬 데이터)"
    )
    p_gcol.add_argument("--patch", required=True)

    p_nar = sub.add_parser(
        "narrative", help="⑤ 서술: fetch(poe2wiki 원문)|check(wiki 산출물 게이트)"
    )
    p_nar.add_argument("--patch", required=True)
    p_nar.add_argument("step", choices=["fetch", "check"])

    p_manifest = sub.add_parser(
        "manifest", help="증거 체인 기록 (KB_INGEST §5): 데이터repo·PoB commit → knowledge/ingest/"
    )
    p_manifest.add_argument("--patch", required=True)

    p_tree = sub.add_parser("tree", help="패시브 트리: fetch(일괄 2회)|process(청크 분류)|merge")
    p_tree.add_argument("--patch", required=True)
    p_tree.add_argument("step", choices=["fetch", "process", "merge"])
    p_tree.add_argument(
        "--kind",
        choices=["keystone", "ascendancy-start", "notable", "mastery", "jewel", "small", "all"],
        default="all",
        help="merge 분할 단위",
    )

    args = ap.parse_args(argv)
    raw_dir = _raw_dir(args.patch)

    if args.cmd == "plan":
        if args.extend:
            from pok.kb.ingest.plan import extend_plan

            plan = extend_plan(raw_dir, args.extend)
        else:
            plan = build_plan(args.patch, raw_dir, args.category)
        for key, cat in plan["categories"].items():
            listed, planned = cat["listed_count"], cat["planned_count"]
            flag = "" if listed == planned else f"  ⚠ 표시 {listed} ≠ 계획 {planned}"
            print(f"{key}: planned={planned} listed={listed}{flag}")
    elif args.cmd == "fetch":
        plan_path = raw_dir / "fetch-plan.json"
        if not plan_path.exists():
            print("fetch-plan.json 없음 — 먼저 plan을 실행하세요", file=sys.stderr)
            return 1
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        s = run_fetch(plan, raw_dir, rate_seconds=args.rate, limit=args.limit, langs=args.lang)
        print(f"fetched={s.fetched} skipped={s.skipped} failed={s.failed} remaining={s.remaining}")
    elif args.cmd == "status":
        plan_path = raw_dir / "fetch-plan.json"
        if not plan_path.exists():
            print("fetch-plan.json 없음", file=sys.stderr)
            return 1
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        c = status_report(plan, raw_dir)
        line = f"planned={c['planned']} fetched={c['fetched']}"
        print(line + f" failed={c['failed']} pending={c['pending']}")
        done = c["planned"] > 0 and c["pending"] == 0 and c["failed"] == 0
        print("완전성 기준 ① (계획 대비 완수):", "통과" if done else "미달")
    elif args.cmd == "process":
        from pok.kb.ingest.process import process_patch

        out_dir = project_root() / "var" / "ingest" / args.patch
        report = process_patch(raw_dir, out_dir)
        print(json.dumps(report["totals"], ensure_ascii=False, indent=1))
        print(f"리포트: {raw_dir / 'report.json'}")
    elif args.cmd == "merge":
        from pok.common.paths import knowledge_dir
        from pok.kb.ingest.merge import merge_patch

        inter = project_root() / "var" / "ingest" / args.patch / "intermediate.json"
        summary = merge_patch(raw_dir, inter, knowledge_dir(), args.patch)
        print(json.dumps(summary, ensure_ascii=False, indent=1))
    elif args.cmd == "oils":
        from pok.common.paths import knowledge_dir
        from pok.kb.ingest import liquid_emotions as oils

        if args.step == "fetch":
            print(json.dumps(oils.fetch_pages(raw_dir), ensure_ascii=False, indent=1))
        else:
            print(
                json.dumps(oils.apply_to_kb(raw_dir, knowledge_dir()), ensure_ascii=False, indent=1)
            )
    elif args.cmd == "uniques":
        from pok.common.paths import knowledge_dir
        from pok.kb.ingest import uniques_page

        out_dir = project_root() / "var" / "ingest" / args.patch
        if args.step == "fetch":
            print(json.dumps(uniques_page.fetch_pages(raw_dir), ensure_ascii=False, indent=1))
        elif args.step == "process":
            pob = project_root() / "external" / "pob" / "5d173cb" / "src" / "Data" / "Uniques"
            print(
                json.dumps(
                    uniques_page.process(raw_dir, pob, out_dir), ensure_ascii=False, indent=1
                )
            )
        else:
            print(
                json.dumps(
                    uniques_page.merge(out_dir, knowledge_dir(), args.patch),
                    ensure_ascii=False,
                    indent=1,
                )
            )
    elif args.cmd == "mods":
        out_dir = project_root() / "var" / "ingest" / args.patch
        if args.step == "process":
            from pok.kb.ingest.mods import process_mods

            mods_report = process_mods(raw_dir, out_dir)
            print(
                json.dumps(
                    {k: v for k, v in mods_report.items() if k != "verification"},
                    ensure_ascii=False,
                    indent=1,
                )
            )
            print(f"리포트: {raw_dir / 'pob' / 'mods-report.json'}")
        elif args.step == "catalog":
            from pok.kb.ingest.mod_catalog import process_catalog

            plan = json.loads((raw_dir / "fetch-plan.json").read_text(encoding="utf-8"))
            cat_report = process_catalog(raw_dir, out_dir, plan)
            print(
                json.dumps(
                    {k: v for k, v in cat_report.items() if k != "verification"},
                    ensure_ascii=False,
                    indent=1,
                )
            )
            print(f"리포트: {raw_dir / 'modifiers' / 'catalog-report.json'}")
        else:
            from pok.common.paths import knowledge_dir
            from pok.kb.ingest.mods import merge_mods

            print(
                json.dumps(
                    merge_mods(out_dir, knowledge_dir(), args.patch), ensure_ascii=False, indent=1
                )
            )
    elif args.cmd == "currency":
        from pok.common.paths import knowledge_dir
        from pok.kb.ingest.currency import process_and_merge

        cur_report = process_and_merge(raw_dir, knowledge_dir(), args.patch)
        print(
            json.dumps(
                {k: v for k, v in cur_report.items() if k != "verification"},
                ensure_ascii=False,
                indent=1,
            )
        )
        print(f"리포트: {raw_dir / 'currency' / 'report.json'}")
    elif args.cmd == "ailments":
        from pok.kb.ingest.ailments import ingest_ailments

        print(json.dumps(ingest_ailments(args.patch), ensure_ascii=False, indent=1))
    elif args.cmd == "meta-energy":
        from pok.kb.ingest.meta_energy import apply_meta_energy

        print(json.dumps(apply_meta_energy(raw_dir), ensure_ascii=False, indent=1))
    elif args.cmd == "gem-costs":
        from pok.common.paths import knowledge_dir
        from pok.kb.ingest.gem_costs import apply_gem_costs

        print(json.dumps(apply_gem_costs(raw_dir, knowledge_dir()), ensure_ascii=False, indent=1))
    elif args.cmd == "gem-colors":
        from pok.common.paths import knowledge_dir
        from pok.kb.ingest.gem_colors import apply_gem_colors

        print(json.dumps(apply_gem_colors(raw_dir, knowledge_dir()), ensure_ascii=False, indent=1))
    elif args.cmd == "narrative":
        from pok.common.paths import knowledge_dir
        from pok.kb.ingest import narrative

        if args.step == "fetch":
            targets = narrative.curated_targets(knowledge_dir())
            print(
                json.dumps(
                    narrative.fetch_narratives(raw_dir, targets), ensure_ascii=False, indent=1
                )
            )
        else:
            result = narrative.check_wiki_docs(knowledge_dir())
            print(json.dumps(result, ensure_ascii=False, indent=1))
            if result["errors"]:
                return 1
    elif args.cmd == "manifest":
        import subprocess

        from pok.common.paths import knowledge_dir
        from pok.kb.ingest.merge import POB_COMMIT

        def _git_head(cwd: Path) -> str:
            return subprocess.run(
                ["git", "-C", str(cwd), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

        manifest = {
            "patch": args.patch,
            "data_repo": "https://github.com/skerfolg/poe2-ai-wiki-data",
            "data_repo_commit": _git_head(raw_dir),
            "pob_commit": POB_COMMIT,
            "tool": "pok.kb.ingest",
            "note": "이 값으로 knowledge/ 커밋 → 원시까지 기계적 역추적 (KB_INGEST §5)",
        }
        dst = knowledge_dir() / "ingest" / "manifest.json"
        dst.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(manifest, ensure_ascii=False, indent=1))
        print(f"기록: {dst}")
    elif args.cmd == "tree":
        from pok.common.paths import knowledge_dir
        from pok.kb.ingest import tree as tree_mod

        out_dir = project_root() / "var" / "ingest" / args.patch
        if args.step == "fetch":
            pob = project_root() / "external" / "pob" / "5d173cb"
            print(json.dumps(tree_mod.fetch_tree(raw_dir, pob), ensure_ascii=False, indent=1))
        elif args.step == "process":
            print(json.dumps(tree_mod.process_tree(raw_dir, out_dir), ensure_ascii=False, indent=1))
        else:
            from pok.kb.ingest.tree_merge import merge_tree

            kinds = tree_mod.CHUNKS if args.kind == "all" else (args.kind,)
            for kind in kinds:
                chunk_summary = merge_tree(out_dir, knowledge_dir(), args.patch, kind)
                print(f"{kind}: {json.dumps(chunk_summary, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
