---
id: insight.meta-gem-energy-mechanics
label: POB_CODE
verified_by: 사용자 승인 2026-08-03 (CoMD 폐기 노트 큐레이션 — 전재 승격, 주장별 라벨은 본문 표기)
lang: ko
source: feedback
source_title: 시신걸음 CoMD 루프 빌드 폐기 노트
source_revid: abc0bec8
source_timestamp: 2026-08-03
feedback_id: 20260803-시신걸음-comd-루프-빌드-폐기-노트
patch: 0.5.4b
---

# 메타 젬 에너지 수급의 결정 요소

메타 젬의 발동 빈도는 소켓 스펠의 시전 시간과 에너지 공급원의 성질로 정해진다.

- **메타 젬의 최대 에너지는 소켓된 스펠의 기본 시전 시간 0.1초당 10이다 — 긴 스킬을 즉발로 쏘는 이득이 구조적으로 상쇄된다** — §4 메타 젬 일반 + §3 '긴 스킬 즉발 이득' 항목과 정합 *(라벨 SUPPORTED_INFERENCE)*
- **CoMD 에너지는 하수인 생명력이 아니라 위세(Monster Power)가 결정한다** — §4 하수인 위세 표 (브루트 90·전사 66·강탈자 52·저격수 41·성직자 25~29) *(라벨 SUPPORTED_INFERENCE)*
- **빙결이 상태 이상 중 메타 젬 에너지 효율이 가장 높다 (Power당 10 vs 점화·감전 1)** — §4 메타 젬 일반 *(라벨 SUPPORTED_INFERENCE)*
- **영원한 행진의 부활 배수는 젬 레벨에 비례하고, 소모량은 고정이 아니라 상한이다 (죽은 만큼만 소모)** — §4 — PoB 실측: 레벨 31 → 배수 28, 최대 소모 2,910 워드 *(라벨 POB_CODE)*
