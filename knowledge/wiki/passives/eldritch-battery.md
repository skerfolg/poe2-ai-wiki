---
id: passive.eldritch-battery
label: UNVERIFIED
source: poe2wiki
source_title: Eldritch Battery
source_revid: 96607
source_timestamp: 2025-12-11
patch: 0.5.4b
---

# 섬뜩한 충전기 (Eldritch Battery)

에너지 보호막을 마나로 전환하고, 그 대가로 **스킬 마나 비용이 두 배**가 되는
키스톤. 방어 자원을 시전 자원으로 바꾸는 트레이드다.

## 메커니즘

- 전환되는 것은 **기본(flat) ES의 합**이며, 전환은 수정치 적용 *전*에 일어난다.
  따라서 이렇게 얻은 마나는 `마나 증가/증폭`으로는 스케일되지만
  `ES 증가/증폭`으로는 **스케일되지 않는다** — ES% 노드·장비가 사표가 된다.
- 같은 효과의 유니크 수정치가 존재하며 키스톤과 중복 이득 없음.

## 판단 노트 (생성기 관점)

- 관계: `converts → defence.energy-shield` · `overlaps → passive.mind-over-matter`
  (MoM과 결합하면 커진 마나 풀이 피해 흡수까지 맡는 고전 조합 — 카오스 면역까지
  삼중이면 마나를 전부 비워야 생명력이 깎인다).
- 비용 2배가 실질 세금 — 비용 감소 수단(고취/Efficiency 계열)과 궁합.
- 장비 평가가 바뀐다: ES flat은 가치 유지, ES%는 가치 0.

## 패치 이력 요점

- 0.2.0: "마나 비용 2배" 속성 추가 (그 전엔 전환만).
- 0.1.0: 출시.
