"""M5 제안 흐름 — 전개(결정적)와 저장(출처 분리) (확정 설계 2026-08-20).

## 전개기 (3단 구조의 중간)

`stacking-supply` 경로의 제안을 공급 그래프(#91)로 **결정적으로** 펼친다. LLM이
기억으로 담체를 나열하면 환각·구변형 위험이 있다(#91 함정 ① — Prism Guardian
구변형 오판 실측). 그래프는 정본만 읽으므로 전개가 검증 가능해진다.

다른 경로는 전개기가 없다 — 제안의 bundle이 그대로 측정으로 간다. **그 사실을
노트로 남긴다**(전개기 부재도 갭이다).

## 저장 — 출처를 섞지 않는다 (M5 함정 ②)

제안(LLM 출처)과 측정(PoB 출처)이 **같은 필드에 섞이면** LLM 가설이 측정된 사실로
굳는다 — 백로그 §3에 이관 보고 3건이 틀렸던 기록이 있고, 그래서 함정 ②가 명문화됐다.
파일 구획을 출처별로 강제한다:

    proposal     LLM 출처 — 계약 통과본 + 낸 주체(model·session)
    expansion    엔진 출처 — 결정적 전개 (재현 가능)
    measurements PoB 출처 — pob_commit 계보와 함께 **추가만** 된다

저장 위치는 데이터 repo(`artifacts/ingest-raw/proposals/<시즌>/`) — 계획·측정과
같은 결정(2026-08-13: 양쪽 PC가 이어받아야 하므로 gitignore 폴더 불가, 재생성
가능한 파생이라 정본도 아님)을 따른다.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pok.engine.proposal import Proposal
from pok.kb.store import Store

_MAX_BUNDLES = 20  # 전개 상한 — 넘으면 잘랐다고 말한다(조용한 절단 금지)


@dataclass(frozen=True)
class Expansion:
    """결정적 전개 결과 — 점수 없음, 후보·근거·배타 재료만(AD-3)."""

    route: str
    bundles: tuple[dict[str, Any], ...]
    notes: tuple[str, ...]


def expand(proposal: Proposal, store: Store) -> Expansion:
    """제안 → 측정 후보 묶음. `stacking-supply`만 전개기가 있다.

    ⚠ 전개기가 없는 경로는 bundle이 그대로 간다 — 전개기 부재를 노트로 남긴다.
    전개기 없는 경로가 쌓이는 것도 도구 갭 데이터다.
    """
    if proposal.route != "stacking-supply":
        return Expansion(
            route=proposal.route,
            bundles=({"changes": list(proposal.bundle), "origin": "proposal"},),
            notes=(
                f"경로 {proposal.route!r}에는 전개기가 없다 — 제안의 bundle을 "
                "그대로 잰다(전개기 부재도 갭이다. 쌓이면 만들 근거가 된다)",
            ),
        )
    from pok.kb.graph.supply import trace_chains

    # 전제 기재에서 축을 찾는다 — 축 키 직접 지정 또는 담체 이름 매칭
    axes = _premise_axes(proposal.premise, store)
    if not axes:
        return Expansion(
            route=proposal.route,
            bundles=(),
            notes=(
                "⚠ 전제 기재에서 스택 축을 못 찾았다 — 축 키(예: strength)나 "
                "공급 그래프에 있는 담체 이름을 premise에 넣어라. 전개 0건",
            ),
        )
    bundles: list[dict[str, Any]] = []
    notes: list[str] = []
    for axis in axes:
        trace = trace_chains(store, axis)
        for chain in trace.chains:
            if len(bundles) >= _MAX_BUNDLES:
                notes.append(f"⚠ 전개 상한 {_MAX_BUNDLES}에서 잘랐다 — 축을 좁혀 다시")
                break
            bundles.append(
                {
                    "origin": "supply-graph",
                    "axes": list(chain.axes),
                    "carriers": [
                        {
                            "id": e.carrier_id,
                            "name": e.carrier_name,
                            "kind": e.carrier_kind,
                            "slot": e.slot,
                            "evidence": e.evidence,
                        }
                        for e in chain.edges
                    ],
                    # 배타 재료를 그대로 실어 보낸다 — 게이트가 먼저다(M5 함정 ①)
                    "conflicts": list(chain.conflicts),
                }
            )
        if trace.cycles:
            notes.append(f"{axis}: 순환 후보 {len(trace.cycles)}건 — viable 사유를 볼 것")
    return Expansion(route=proposal.route, bundles=tuple(bundles), notes=tuple(notes))


def _premise_axes(premise: tuple[str, ...], store: Store) -> list[str]:
    from pok.kb.graph.supply import AXIS_VOCAB, scan_supply_edges

    keys = {key for key, _ in AXIS_VOCAB}
    out = [p for p in premise if p in keys]
    if out:
        return out
    scan = scan_supply_edges(store)
    wanted = {p.casefold() for p in premise}
    return sorted({e.source_axis for e in scan.edges if e.carrier_name.casefold() in wanted})


# ── 저장 (출처 분리) ─────────────────────────────────────────────────────


def proposals_dir(season: str, *, base: Path | None = None) -> Path:
    root = base or Path("artifacts/ingest-raw")
    return root / "proposals" / season


def proposal_id(proposal: Proposal) -> str:
    """제목 슬러그 + 내용 해시 — 같은 제안은 같은 id(재실행 멱등), 다르면 다른 파일."""
    slug = re.sub(r"[^a-z0-9]+", "-", proposal.title.casefold()).strip("-")[:40]
    digest = hashlib.sha256(
        json.dumps(asdict(proposal), ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:8]
    return f"{slug}-{digest}"


def save(
    season: str,
    proposal: Proposal,
    expansion: Expansion,
    *,
    proposed_by: dict[str, str],
    base: Path | None = None,
) -> Path:
    """제안+전개를 쓴다. `proposed_by`(model·session 등)는 **필수다** —
    누가 낸 가설인지 없으면 측정이 계보를 잃는다(M5 함정 ③ 재현성)."""
    if not proposed_by:
        raise ValueError(
            "proposed_by가 비었다 — 어느 모델·세션이 낸 가설인지 없으면 "
            "재현도 교차 검증도 불가능하다(M5 함정 ③)"
        )
    folder = proposals_dir(season, base=base)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{proposal_id(proposal)}.json"
    doc = {
        "id": proposal_id(proposal),
        "season": season,
        # ── LLM 출처 ──
        "proposal": {**asdict(proposal), "proposed_by": proposed_by},
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        # ── 엔진 출처 (결정적 — 재현 가능) ──
        "expansion": asdict(expansion),
        # ── PoB 출처 — record_measurement만 여기 쓴다 ──
        "measurements": [],
    }
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    return path


def record_measurement(path: Path, measurement: dict[str, Any]) -> None:
    """측정 결과를 **추가만** 한다. `pob_commit` 없는 측정은 거부 — 계보 없는
    수치는 무효화 판정을 못 한다(캠페인과 같은 규약)."""
    if not measurement.get("pob_commit"):
        raise ValueError("측정에 pob_commit이 없다 — PoB가 바뀌면 무효인지 판정할 수 없다")
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["measurements"].append(
        {**measurement, "measured_utc": datetime.now(UTC).isoformat(timespec="seconds")}
    )
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
