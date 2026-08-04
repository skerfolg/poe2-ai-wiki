"""승격 — 큐레이션 승인분만 정본(`knowledge/`)에 기록 (PROJECT_STRUCTURE §6).

"학습이 KB를 직접 수정하지 않는다"(BLUEPRINT §7)를 물리적으로 보장하는 지점:
- 입력은 **승인된 주장만** — pending·rejected는 통과 못 한다.
- 산출물엔 검증 라벨과 `verified_by`(승인 주체·근거)가 반드시 박힌다.
- 계보(피드백 id·원문 해시)를 front-matter에 남겨 원문으로 되짚을 수 있게 한다.

## 3계층 사다리 (BLUEPRINT §15 미결 3번, 사용자 결정 2026-08-04)

    시즌 인사이트 ──▶ durable 인사이트 ──▶ canonical 레코드
      (scope=season)     (scope=durable)      (Mechanic/Resource)

지식이 오래 쓰일수록 위로 올린다. 한 폴더에 평평하게 쌓으면 "이번 시즌 관찰"과
"게임의 항구적 규칙"이 같은 무게로 보이고, 후자가 *지워도 되는 아이디어*처럼
읽힌다(사용자 지적 2026-08-04 — 로우라이프 점유 규칙이 그 상태였다).

각 칸은 **사람 판정**으로만 넘어간다. 자동 승격은 없다:
- season → durable: 여러 빌드·시즌에서 재확인됨 (`set_scope`)
- durable → canonical: 게임의 규칙·상수·공식으로 확정됨 (`promote_to_record`)

레코드로 올라간 뒤에도 인사이트를 지우지 않는다 — **사실은 레코드로, 그 사실을
설계에서 어떻게 쓰는가(규율)는 인사이트로** 남는다. 둘은 대체재가 아니다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pok.common.paths import artifacts_dir, knowledge_dir
from pok.kb.insights import dump_front_matter, parse_insight, patch_front_matter

SCOPES = ("season", "durable")


def promote_insight(
    feedback_id: str,
    slug: str,
    title: str,
    body: str,
    *,
    label: str,
    verified_by: str,
    target_id: str | None = None,
    patch: str,
    scope: str = "season",
    root: Path | None = None,
    now: datetime | None = None,
) -> Path:
    """승인분을 `knowledge/insights/<slug>.md`로 기록한다.

    body는 호출자가 승인된 주장들로 구성한 본문 — 이 함수는 계보·라벨을 박고
    파일로 떨어뜨리는 일만 한다(내용 판단 없음, AD-3).

    scope 기본값은 `season`이다 — 새 인사이트는 **시즌 한정으로 시작**하고,
    오래 간다는 판단은 나중에 사람이 `set_scope`로 올린다. 반대로 두면(기본
    durable) 검증되지 않은 관찰이 항구적 지식 행세를 하게 된다.
    """
    if not verified_by.strip():
        raise ValueError("verified_by 없음 — 승격에는 검증 주체 기록이 필수다")
    if scope not in SCOPES:
        raise ValueError(f"scope 어휘 밖: {scope!r} (허용: {list(SCOPES)})")
    raw_manifest = artifacts_dir(root) / "feedback" / "raw" / feedback_id / "manifest.json"
    if not raw_manifest.exists():
        raise FileNotFoundError(f"피드백 원문 없음: {feedback_id} — 계보 없는 승격 금지")
    meta = json.loads(raw_manifest.read_text(encoding="utf-8"))
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%d")
    front = dump_front_matter(
        {
            "id": target_id or f"insight.{slug}",
            "label": label,
            "scope": scope,
            "verified_by": verified_by,
            "lang": "ko",
            "source": "feedback",
            "source_title": meta.get("title", ""),
            "source_revid": str(meta.get("content_sha256", ""))[:8],
            "source_timestamp": stamp,
            "feedback_id": feedback_id,
            "patch": patch,
        }
    )
    out = knowledge_dir(root) / "insights" / f"{slug}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"{front}\n# {title}\n\n{body.strip()}\n", encoding="utf-8")
    meta["state"] = "promoted"
    meta.setdefault("promoted", []).append({"slug": slug, "at": stamp})
    raw_manifest.write_text(
        json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return out


def set_scope(
    slug: str,
    scope: str,
    *,
    verified_by: str,
    root: Path | None = None,
) -> Path:
    """사다리 1칸 — 인사이트의 scope를 바꾼다 (season ↔ durable).

    "여러 빌드에서 재확인됐다"는 판단은 기계가 못 한다. 그래서 이 함수는 판정을
    **기록**할 뿐이고, 무엇을 올릴지는 사람이 정한다(AD-3). 근거를 남기지 않는
    승격은 나중에 "왜 durable이지?"에 답할 수 없으므로 verified_by를 강제한다.
    """
    if scope not in SCOPES:
        raise ValueError(f"scope 어휘 밖: {scope!r} (허용: {list(SCOPES)})")
    if not verified_by.strip():
        raise ValueError("verified_by 없음 — scope 변경도 판정이다")

    path = knowledge_dir(root) / "insights" / f"{slug}.md"
    if not path.exists():
        raise FileNotFoundError(f"인사이트 없음: {slug}")
    return patch_front_matter(path, {"scope": scope, "scope_verified_by": verified_by})


def promote_to_record(
    slug: str,
    updates: dict[str, dict[str, Any]],
    *,
    verified_by: str,
    relations: dict[str, list[dict[str, str]]] | None = None,
    root: Path | None = None,
) -> list[Any]:
    """사다리 2칸 — 인사이트의 **사실**을 canonical 레코드에 반영한다.

    updates = {레코드 id: data 패치} · relations = {레코드 id: [{rel, target, note?}]}

    인사이트에 담긴 것 중 *게임의 규칙·상수·공식*은 레코드로 내려가야 한다.
    한 폴더에 남겨두면 "지워도 되는 아이디어"처럼 읽히기 때문이다(사용자 지적
    2026-08-04). 대신 **인사이트를 지우지 않는다** — 사실은 레코드로, 그 사실을
    설계에서 어떻게 쓰는가(규율)는 인사이트로 남는다.

    쓰기는 `store.patch_records` 단일 경로를 탄다(B-6) — 배치 규칙과 재검증이
    거기 있다. 반영 사실은 인사이트 front matter(`promoted_to`)에 기록해
    "이 규칙이 어느 레코드로 갔는지" 역추적할 수 있게 한다.
    """
    if not verified_by.strip():
        raise ValueError("verified_by 없음 — 정본 레코드 반영은 판정이다")

    from pok.kb import store as kb_store

    # 중첩 병합·소실 차단은 store가 한다(B-7) — 여기서 다시 하지 않는다.
    reports = kb_store.patch_records(updates, root=root) if updates else []

    if relations:
        loaded = kb_store.load(root)
        for rid, edges in relations.items():
            record = loaded.records[rid]
            existing = record.relations
            known = {(e.get("rel"), e.get("target")) for e in existing}
            merged = existing + [e for e in edges if (e.get("rel"), e.get("target")) not in known]
            kb_store.patch_record_field(rid, "relations", merged, root=root)

    path = knowledge_dir(root) / "insights" / f"{slug}.md"
    if path.exists():
        _append_promoted_to(path, set(updates) | set(relations or {}))
    return reports


def _append_promoted_to(path: Path, targets: set[str]) -> None:
    """인사이트 front matter의 `promoted_to`에 레코드 id를 **누적**한다.

    한 인사이트의 사실이 여러 레코드로 나뉘어 갈 수 있으므로 덮어쓰면 앞서 올린
    계보가 사라진다 — 실측(2026-08-04)에서 로우라이프가 `resource.life` 계보를
    잃었다. `_verification`과 같은 성질이다: 이런 대장은 교체가 아니라 누적이다.

    쓰기 자체는 `patch_front_matter` 단일 경로가 한다(B-8) — 다른 키를 보존하고
    소실을 거부하는 안전장치가 거기 있다.
    """
    if not targets:
        return
    prior = set(parse_insight(path.read_text(encoding="utf-8"), path).promoted_to)
    patch_front_matter(path, {"promoted_to": ", ".join(sorted(prior | targets))})
