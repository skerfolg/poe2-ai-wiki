---
id: support.scattershot
label: SUPPORTED_INFERENCE
verified_by: model-spotcheck 2026-07-30 (원문 revid·KB 구조 레코드 대조, 메커니즘 섹션 모순 0)
source: poe2wiki
source_title: Multishot I
source_revid: 127204
source_timestamp: 2026-06-01
patch: 0.5.4b
---

# 산탄 (Scattershot) → **Multishot I로 개명·티어화됨**

> 0.3.0에서 개명("Scattershot" → "Multishot I") + 티어 체계 도입.
> KB 시드가 구명칭을 가리키므로 레코드 갱신 검토 대상.

투사체 스킬을 지원해 **추가 투사체를 발사**하게 하는 서포트. 대가로 공격/시전
속도가 느려지고 피해가 감폭된다.

## 메커니즘

- 추가 투사체 부여 + 공·시전 속도 저하 + 피해 감폭 (0.2.0에서 감폭
  20%→35%로 강화, 이후 티어 I 기준).

## 판단 노트 (생성기 관점)

- 투사체 수는 **광역 처리량**의 곱셈이지만 단일 대상 DPS는 3중 페널티
  (속도·피해)로 순손해가 되기 쉽다 — 다중 투사체가 같은 대상을 때릴 수 있는
  스킬(샷건 가능 여부)인지가 판정 기준 (RC2).
- 화염구처럼 2차 투사체에 추가 투사체가 안 붙는 스킬이 있다 — 스킬별 예외
  확인 필요.

## 패치 이력 요점

- 0.3.0: 개명 + 티어화.
- 0.2.0: 피해 감폭 20% → 35%.
- 0.1.0: 출시.
