"""M5 제안 계약 — 3필드를 **검증기로** 강제한다 (확정 설계 2026-08-20).

## 왜 검증기인가

제안 형식을 문서에 적으면 안 지켜진다(철칙 5 — 실측: 문서에만 있던 규율은 인용까지
하고도 어겨졌다). LLM 제안이 안쪽 루프에 들어오는 관문이 여기고, 세 필드가 빠지면
여기서 거부된다.

## 세 필드가 각각 막는 함정

1. **메커니즘 유형** — 제안이 어느 창의 축인지. 없으면 잴 수 있는 조각(스태킹)으로
   제안이 쏠려도 아무도 모른다(가로등 밑 열쇠 찾기).
2. **전제 기재(조건 선언)** — 이 묶음이 어느 기재 위에서 성립하는가. 측정 결과가
   **조건의 실측 증거로 이중 사용**된다(#89 부활 경로) — 이 선언이 없으면 측정이
   「어느 가설 아래서 나왔나」 계보를 잃고 정본 오염 경로가 열린다(M5 함정 ②).
3. **검증 경로** — 안쪽 루프가 이 제안을 **무엇으로 재는가**. 등록된 경로여야 하고,
   없으면 버리는 게 아니라 `route="unverifiable"`로 **도구 갭 라벨**을 달아 남긴다 —
   조용히 빠지는 대신 갭이 기록되고, 라벨 누적이 다음 측정기의 우선순위 데이터가
   된다(형태 ①의 반대. 사용자 지적 2026-08-20: 트리거 연쇄·DoT·플레이 패턴이
   창의의 중심 축인데 공급 그래프 밖이다 — 배제하면 계산기보다 조금 나은 도구가 된다).

⛔ **여기서 제안의 좋고 나쁨을 판단하지 않는다**(철칙 3). 형식과 검증 가능성만 본다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── 검증 경로 등록부 ─────────────────────────────────────────────────────
#
# 경로마다 「무엇으로 재나」와 **알려진 한계**를 함께 든다 — 한계 없이 도구 이름만
# 들면 측정이 만능으로 읽힌다(철칙 4: PoB는 계산기지 검증기가 아니다).
VERIFICATION_ROUTES: dict[str, dict[str, str]] = {
    "stacking-supply": {
        "measure": "공급 그래프 전개(kb.graph.supply) + evaluate_bundles PoB 델타",
        "limits": "비례 문구 축만 — 사건·메커니즘 관계는 이 그래프 밖이다",
    },
    "trigger-rate": {
        "measure": "compute_trigger_rate (메타 젬 에너지 모델)",
        "limits": "Power 기반 젬 한정 · 대상 Power는 등급 범위 기반 예상치",
    },
    "dot-axes": {
        "measure": "PoB DoT 축 + evaluate_change_bundle",
        "limits": "⚠ #44 — 주력 딜이 PoB가 못 재는 축이면 조립이 정상으로 보인다. "
        "실측: 검사기 5종을 통과한 빌드가 출혈 강도를 2.76배 부풀렸다(철칙 4)",
    },
    "pob-delta": {
        "measure": "evaluate_bundles / evaluate_change_bundle (일반 델타)",
        "limits": "철칙 4 — 값이 나온다는 것이 인게임 성립을 뜻하지 않는다",
    },
    "config-assumption": {
        "measure": "PoB config 토글 + 가정 수치 등재(설계 규율)",
        "limits": "가동률·로테이션 가정은 사람 선언이다 — 등재 없는 가정은 무효",
    },
}

UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class Proposal:
    """검증기를 통과한 제안 — 안쪽 루프가 받는 형태."""

    title: str
    mechanism: str  # 창의 축 (자유 문자열 — 유형을 좁히는 것 자체가 판단이라 안 좁힌다)
    premise: tuple[str, ...]  # 전제 기재(담체·메커니즘) — 조건 선언
    route: str  # VERIFICATION_ROUTES 키 또는 "unverifiable"
    bundle: tuple[str, ...]  # 안쪽 루프에 넘길 구체 변경안(자유 서술 — 전개기가 받는다)
    notes: tuple[str, ...] = field(default=())

    @property
    def verifiable(self) -> bool:
        return self.route != UNVERIFIABLE


class ProposalError(ValueError):
    """세 필드 중 무엇이 왜 빠졌는지 — LLM이 읽고 고칠 수 있게 문장으로."""


def validate(doc: dict[str, Any]) -> Proposal:
    """제안 dict → 계약 통과본. 실패는 예외로, 갭은 라벨로.

    ⚠ **갭은 거부가 아니다.** 검증 경로를 모르겠으면 `route: "unverifiable"`을
    명시하고 이유를 `route_gap`에 적어야 한다 — 그러면 통과하되 라벨이 남는다.
    경로를 **비우거나 아무 문자열이나 넣는 것**만 거부된다: 전자는 조용한 갭,
    후자는 가짜 검증이다.
    """
    missing = [k for k in ("title", "mechanism", "premise", "route", "bundle") if not doc.get(k)]
    if missing:
        raise ProposalError(
            f"제안에 {missing}이 없다 — 메커니즘 유형·전제 기재·검증 경로는 "
            "선택이 아니라 계약이다(M5 확정 설계). 검증 경로를 모르겠으면 "
            f'route: "{UNVERIFIABLE}"을 명시하고 route_gap에 이유를 적어라'
        )
    route = str(doc["route"])
    notes: list[str] = []
    if route == UNVERIFIABLE:
        gap = str(doc.get("route_gap") or "").strip()
        if not gap:
            raise ProposalError(
                'route가 "unverifiable"이면 route_gap(무엇이 없어서 못 재는가)이 '
                "필수다 — 이 라벨의 누적이 다음 측정기의 우선순위 데이터다"
            )
        notes.append(f"⚠ 도구 갭: {gap} — 이 제안은 측정 없이 채택될 수 없다(철칙 4)")
    elif route not in VERIFICATION_ROUTES:
        raise ProposalError(
            f"모르는 검증 경로 {route!r} — 허용: {sorted(VERIFICATION_ROUTES)} "
            f'또는 "{UNVERIFIABLE}"(+route_gap). 가짜 경로는 가짜 검증이 된다'
        )
    else:
        notes.append(f"검증 한계: {VERIFICATION_ROUTES[route]['limits']}")
    premise = tuple(str(x) for x in doc["premise"])
    return Proposal(
        title=str(doc["title"]),
        mechanism=str(doc["mechanism"]),
        premise=premise,
        route=route,
        bundle=tuple(str(x) for x in doc["bundle"]),
        notes=tuple(notes),
    )
