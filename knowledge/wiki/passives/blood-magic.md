---
id: passive.blood-magic
label: UNVERIFIED
source: poe2wiki
source_title: Blood Magic
source_revid: 96639
source_timestamp: 2025-12-11
patch: 0.5.4b
---

# 혈마법 (Blood Magic)

마나를 전부 제거하고 **마나 비용을 생명력 비용으로 바꾸는** 키스톤.
자원 체계를 생명력 하나로 통합하는 대신, 스킬을 쓸 때마다 체력을 태운다.

## 메커니즘

- 마나가 0으로 고정된다. 0.2.0부터 "값 고정" 계열이 전환(conversion)보다
  먼저 적용되도록 정리됐다 (카오스 면역의 생명력 1 고정과 같은 규칙).
- 같은 효과를 부여하는 유니크 아이템이 존재하며, 키스톤과 **중복 이득은 없다**.

## 판단 노트 (생성기 관점)

- 관계: `replaces → resource.mana` · `consumes → resource.life` ·
  `conflicts_with → passive.eldritch-battery` (ES→마나 전환이 무의미해짐).
- 물질보다 정신(마나로 피해 흡수)과도 사실상 배타 — 마나가 없다.
- 생명력 회복 밀도(재생·흡수)가 스킬 비용을 상쇄할 수 있는지가 채택 판정
  기준이다. 비용이 큰 스킬 + 회복 부족 = 자멸 루프 (RC1 유형).

## 패치 이력 요점

- 0.2.0: 값 고정이 전환보다 먼저 적용되도록 변경.
- 0.1.0: 출시.
