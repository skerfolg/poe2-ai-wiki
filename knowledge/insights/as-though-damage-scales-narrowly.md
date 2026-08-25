---
id: insight.as-though-damage-scales-narrowly
label: UNVERIFIED
scope: season
verified_by: 미검증 — 3자(유튜브) 주장 전사, [엔진] 세션 2026-08-25. 사용자 판정 대기
lang: ko
source: feedback
source_title: [유튜브] POE2 버리던 아이템이 전설급이던 건에 대하여 — 춘삼_CHOONSAM
source_revid: 1a2739aa
source_timestamp: 2026-08-25
feedback_id: 20260825-유튜브-poe2-버리던-아이템이-전설급이던-건에-대하여-춘삼-choonsam
patch: 0.5.4b
---

# 「~인 것처럼」 피해는 적중이 아니다 — 스케일링 축이 극히 좁다

**주장**: 「최대 생명력의 N%인 것처럼 점화시킨다」류의 고정형 피해는 **적중(Hit)이
아니라 상태이상 적용**이다. 무기 치명타도 주문 치명타도 붙지 않고 무기 옵션 대부분이
적용되지 않는다. 이런 피해원은 **크기가 아니라 스케일링 축의 개수**로 평가해야 한다.

**근거 (문구 = GAME_DATA)**: `item.beiras-anguish`의 문구는
`Creates Ignited Ground for 4 seconds when used, Igniting enemies as though dealing
Fire damage equal to 500% of your maximum Life`다. **적중을 만들지 않고 점화를 건다.**
계수가 최대 생명력의 500%라 커 보이지만 붙는 축은 최대 생명력 · 화염 피해 ·
엑스트라 데미지 · 점화 강도 정도로 끝난다.

**설계에 어떻게 쓰나**: 이런 피해원을 주력으로 놓으면 **치명타 트리와 무기
업그레이드가 전부 죽은 투자**가 된다. 반대로 생명력 스택과는 결이 맞는다.
「크다」가 아니라 「무엇으로 커지나」를 먼저 세고, 축이 서넛뿐이면 주력이 아니라
보조로 배치한다. 실제로 두 영상 모두 같은 결론에 도달했다 — 3티어 지도까지는
받쳐 주지만 고티어를 빠르게 도는 주력으로는 못 쓴다.

**연결**: 우리 KB는 이 아이템의 문구 **3줄 전부**를 PoB가 아이템 모드로 못 읽는다고
신고해 둔다(`pob_modeling.supported=false`). 즉 오라클로 재면 0이 나오고, 그 0을
값어치로 읽으면 안 된다 — [[pob-is-a-calculator-not-a-validator]]와 같은 축이다.

**미검증 경계**: 「치명타 약화 디버프를 걸면 무조건 치명타가 난다」는 우회가 있었고
0.5.5에서 수정됐다는 영상의 주장은 **확인하지 않았다** — 근거로 쓰지 않는다.
점화 강도·엑스트라 데미지가 실제로 이 문구에 붙는지도 인게임 확인 전이다.

**출처**: POE2 버리던 아이템이 전설급이던 건에 대하여 (03:21~05:21) ·
POE2에서 RF는 정말 불가능할까? (01:41~02:06) — 둘 다 춘삼_CHOONSAM ·
KB 대조 `item.beiras-anguish` (verification=GAME_DATA, patch 0.5.4b)
