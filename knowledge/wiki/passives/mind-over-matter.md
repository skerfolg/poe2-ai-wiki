---
id: passive.mind-over-matter
label: SUPPORTED_INFERENCE
verified_by: model-spotcheck 2026-07-30 (원문 revid·KB 구조 레코드 대조, 메커니즘 섹션 모순 0)
lang: ko
source: poe2wiki
source_title: Mind Over Matter
source_revid: 96569
source_timestamp: 2025-12-11
patch: 0.5.4b
---

# 물질보다 정신 (Mind Over Matter, MoM)

생명력으로 갈 피해를 **마나가 전부 대신 받는** 키스톤. 대가로 마나 회복이
절반이 된다.

## 메커니즘

- 생명력에 가해질 피해가 먼저 마나에서 차감되고, 마나가 부족하면 나머지만
  생명력으로 넘어온다 (PoE1의 비율 분담과 달리 **전액 마나 우선**).
- 총 피해량을 줄이는 게 아니므로 **스턴·상태이상 임계치에는 도움이 안 된다**
  (임계치는 여전히 생명력 기준).
- 카오스 면역(CI)과 결합하면 ES → 마나 → 생명력 순서가 되어, ES와 마나를
  모두 비워야 생명력이 깎인다. 섬뜩한 충전기까지 더하면 커진 마나 풀이
  전면 방어가 되고, 출혈도 사실상 무력화된다(피해가 먼저 마나로 가므로).
- 세케마의 시험에서는 최대 마나가 명예(Honour) 총량에 합산된다.

## 판단 노트 (생성기 관점)

- 관계: `mitigates → resource.life` · `scales_with → resource.mana`.
- 실효 체력 = 생명력 + 마나이지만, **마나는 스킬 비용과 경합**한다 — 비용
  지불 직후 얻어맞으면 흡수량이 줄어 있다. 마나 회복 절반 페널티까지 겹쳐
  회복 밀도 계산이 채택 판정의 핵심.
- 혈마법과는 정의상 배타 (마나가 없으면 흡수할 것도 없다).

## 패치 이력 요점

- 0.1.0: 출시. 구조 변화 없음.
