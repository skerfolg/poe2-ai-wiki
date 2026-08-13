"""래더 코퍼스를 우리 스펙으로 되돌릴 때 **무엇이 빠지는가**를 전수 조사한다.

## 왜 이것이 반사실 측정의 P0 게이트인가

반사실 측정(노드를 빼고 다시 재기)의 델타는 **기준선에 상대적**이다. 기준선이
원본 래더 빌드와 다르면 델타 자체는 여전히 유효하지만 **귀속(attribution)이
거짓이 된다** — "래더 상위가 찍은 이 노드는 실측상 죽어 있다"가 실은 "주얼과
보조가 빠진 약한 빌드에서 죽어 있다"였을 수 있다. 노드 가치는 문맥 의존적이므로
(같은 `increased`도 이미 쌓인 양에 따라 다르다) 그 둘은 같은 주장이 아니다.

그래서 측정에 들어가기 **전에** 표본마다 "무엇이 빠졌나"를 세어 두고, 쓸 수 있는
표본 수를 축마다 확정한다. 실측 2026-08-13(고유 캐릭터 231벌):

    복원 예외              0벌 — 전량 복원된다
    faithful               0벌 — 그런데 **한 벌도 완전하지 않다**
    damage_comparable     46벌 — 딜 축 반사실의 상한은 231이 아니라 46이다

`faithful`이 0인 것은 결함이 아니다. 231벌 전부가 `stat_set_index`를 **가정**하는데
(PoB 공유 코드가 어느 모드로 계산했는지 남기지 않는다) 그건 형식의 정보 손실이라
어떤 빌드도 통과할 수 없다. 즉 `faithful`은 캠페인 게이트로 쓸 수 없다.

## ⚠ 비교 가능성은 **축마다 다르다** (여기서 판정하지 않는다)

`RestoredBuild.damage_comparable`은 「부여 스킬 그룹이 보조와 함께 빠졌나」 하나로
딜 비교 가능성을 낸다. 그런데 실측에서 빠진 그룹 이름이 `Purity of Fire`·
`Raise Shield`였다 — **방어 스킬이다.** 그 빌드는 딜이 아니라 **방어** 축이 어긋난다.
플래그 하나로는 그 구분이 안 된다.

**그래서 이 모듈은 빠진 스킬 이름을 그대로 낸다 — 어느 축이 오염됐는지 판정하지
않는다**(철칙 3: 「이 스킬이 방어인가」는 게임 지식 판단이고 엔진 몫이 아니다).
축 판정은 호출자(스킬·에이전트)가 하고, 근거로 이 목록을 쓴다.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pok.artifacts.ladder import LadderError, ladder_dir
from pok.pob.restore import spec_from_pob


def _snapshot_stamp() -> dict[str, str]:
    """측정을 무효화하는 전제 — PoB 스냅샷 커밋.

    캠페인은 오래 돌고 중간에 스냅샷이 바뀔 수 있다. 스탬프가 없으면 서로 다른
    계산기로 잰 값이 한 데이터셋에 섞인다. 스냅샷이 없는 PC(수집 전용 Mac 등)에서도
    이 조사는 돌아야 하므로 **없으면 사유를 담아 낸다** — 조용히 비우지 않는다.
    """
    try:
        from pok.pob.versions import resolve_snapshot

        return {"pob_commit": resolve_snapshot().commit}
    except Exception as exc:  # 스냅샷 미설치·핀 불일치 등
        return {"pob_commit": "", "why": f"스냅샷을 못 읽었다: {type(exc).__name__} {exc}"}


def _norm(text: str) -> str:
    """숫자를 지워 사유를 묶는다 — "노드 3개"와 "노드 5개"는 같은 사유다."""
    return re.sub(r"\d+", "N", text)


def survey(season: str, *, concept: str | None = None, base: Path | None = None) -> dict[str, Any]:
    """코퍼스를 전량 복원해 빌드마다 「빠진 것」을 센다. PoB를 돌리지 않는다.

    복원은 base64 해제 + XML 파싱뿐이라 스냅샷도 LuaJIT도 필요 없다 — 그래서 이
    조사는 수집 전용 PC에서도 돈다(측정 단계만 PoB가 필요하다).

    ⚠ 같은 캐릭터가 여러 컨셉 폴더에 겹쳐 있다(실측: 파일 300개 = 고유 231명).
    겹친 것을 그대로 세면 표본 수가 부풀고, 반사실 측정을 같은 빌드에 두 번 돌린다.
    """
    root = (base or ladder_dir()) / season
    if not root.exists():
        raise LadderError(f"수집된 시즌이 없다: {root}")
    folders = [root / concept] if concept else sorted(p for p in root.iterdir() if p.is_dir())

    seen: set[tuple[str, str]] = set()
    builds: list[dict[str, Any]] = []
    note_tally: Counter[str] = Counter()
    need_tally: Counter[str] = Counter()
    failed: list[dict[str, str]] = []
    for folder in folders:
        for path in sorted(folder.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            raw = doc.get("raw") or {}
            key = (str(raw.get("account") or ""), str(raw.get("name") or ""))
            if key in seen:
                continue
            seen.add(key)
            try:
                restored = spec_from_pob(doc["pob_export"])
            except Exception as exc:  # 복원 불가 — 조용히 빼면 표본이 줄어든 걸 모른다
                failed.append({"build": "/".join(key), "error": f"{type(exc).__name__} {exc}"})
                continue
            for note in restored.notes:
                note_tally[_norm(str(note))] += 1
            for need in restored.needs_decision:
                need_tally[_norm(str(need))] += 1
            builds.append(
                {
                    "build": "/".join(key),
                    "concept": folder.name,
                    "level": raw.get("level"),
                    "ascendancy": raw.get("class"),
                    "faithful": restored.faithful,
                    "damage_comparable": restored.damage_comparable,
                    # ⚠ 이름을 그대로 낸다 — 어느 축이 오염됐는지는 호출자가 판정한다.
                    #   `Purity of Fire`·`Raise Shield`처럼 **방어** 스킬이 빠지는 경우가
                    #   있어 `damage_comparable`만 보면 방어 축 오염을 놓친다.
                    "dropped_granted": [
                        {"skill": name, "supports_lost": count}
                        for name, count in restored.dropped_item_granted
                    ],
                    "notes": len(restored.notes),
                    "needs_decision": len(restored.needs_decision),
                }
            )
    return {
        "season": season,
        "provenance": _snapshot_stamp(),
        "sample": {
            "files_seen": sum(len(list(f.glob("*.json"))) for f in folders),
            "unique_builds": len(seen),
            "restored": len(builds),
            "restore_failed": len(failed),
        },
        # 축마다 쓸 수 있는 표본 수. **캠페인 계획의 크기가 이 값이다.**
        "usable": {
            "damage_comparable": sum(1 for b in builds if b["damage_comparable"]),
            "faithful": sum(1 for b in builds if b["faithful"]),
            "any_dropped_granted": sum(1 for b in builds if b["dropped_granted"]),
        },
        "note_reasons": [{"reason": r, "builds": c} for r, c in note_tally.most_common()],
        "needs_decision_reasons": [{"reason": r, "builds": c} for r, c in need_tally.most_common()],
        "failed": failed,
        "builds": builds,
    }


def _cli(argv: list[str] | None = None) -> int:
    import argparse

    from pok.common.stdio import force_utf8_stdio

    force_utf8_stdio()  # 사유 문구에 em dash가 들어간다(Windows에서 죽던 것)

    p = argparse.ArgumentParser(prog="python -m pok.engine.corpus_fidelity")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("survey", help="복원 충실도 전수 조사 — 반사실 캠페인의 P0 게이트")
    s.add_argument("--season", required=True, help="예: 0-5")
    s.add_argument("--concept", help="한 컨셉만 (없으면 시즌 전량)")
    s.add_argument("--out", help="결과 JSON 경로 (없으면 stdout 요약만)")
    args = p.parse_args(argv)

    try:
        report = survey(args.season, concept=args.concept)
    except LadderError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )

    # 요약만 낸다 — 빌드 231행을 stdout에 부으면 읽는 쪽이 요점을 놓친다.
    summary = {k: report[k] for k in ("season", "provenance", "sample", "usable")}
    summary["note_reasons_top"] = report["note_reasons"][:5]
    summary["needs_decision_top"] = report["needs_decision_reasons"][:3]
    if report["failed"]:
        summary["failed"] = report["failed"][:5]
    if args.out:
        summary["written"] = args.out
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
