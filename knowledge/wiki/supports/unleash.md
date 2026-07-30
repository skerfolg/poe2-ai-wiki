---
id: support.unleash
label: SUPPORTED_INFERENCE
verified_by: model-spotcheck 2026-07-30 (원문 revid·KB 구조 레코드 대조, 메커니즘 섹션 모순 0)
lang: ko
source: poe2wiki
source_title: Unleash
source_revid: 131380
source_timestamp: 2026-06-26
patch: 0.5.4b
---

# 촉발 (Unleash)

직접 시전하는 **반복 가능(Repeatable) 주문**을 지원해, 시간이 지나며 **봉인
(Seal)을 축적**시키는 서포트. 시전하는 순간 쌓인 봉인이 전부 깨지며 봉인당
한 번씩 주문이 **반복**된다. 쿨다운이 있거나 이미 봉인을 얻는 스킬은 지원 불가.

## 메커니즘

- 운용 리듬이 바뀐다: 연사보다 **묵혀서 한 번에 터뜨리는** 패턴 — 이동·회피
  중에 봉인이 쌓이므로 실전 가동률(uptime)이 낮은 플레이일수록 이득이 크다.
- 0.5.0에서 봉인 체계가 표준화됐다 — Unleash·Expand·Salvo·Freezing Salvo가
  각자 다른 규칙을 갖던 것을 단일 Seal 규칙으로 통합 (동작 세부가 일부 변경).
- 기점(Payoff) 스킬과의 상호작용: 소비형 효과가 봉인 반복마다 한 번씩 더
  발동하는 사례가 보고돼 있다 (감쇠된 피해로).

## 판단 노트 (생성기 관점)

- KB 실측 주의: PoB와 poe2db의 **Tier 값이 다른 유일한 젬**이었다
  (⑥ fact_mismatch 실측 1건) — 티어 표기를 쓸 때 소스 확인 필요.
- "직접 시전 + Repeatable + 무쿨다운" 세 조건을 모두 만족해야 한다 (RC1) —
  토템/트리거 시전과는 무관.

## 패치 이력 요점

- 0.5.0: 봉인 체계 4종 통합·표준화.
- 0.1.0: 출시.
