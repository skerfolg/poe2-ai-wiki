---
id: insight.low-life-supply-is-reservation
label: IN_GAME
verified_by: 사용자 판정 2026-08-04 (능동 탐사 gap 가설에 대한 게임 지식 판정)
lang: ko
source: feedback
source_title: 능동 탐사 가설 큐
source_revid: b6d2b057
source_timestamp: 2026-08-04
feedback_id: 20260803-능동-탐사-가설-큐
patch: 0.5.4b
scope: durable
scope_verified_by: 사용자 판정 2026-08-04 (로우라이프는 계속 쓰일 메커니즘 — 인사이트로만 두지 않는다)
promoted_to: mechanic.reservation, resource.life
---

# 로우라이프 공급은 점유이지 소모가 아니다

## 로우라이프의 공급은 점유(reserve)뿐이다

로우라이프(잔여 생명력 35% 이하)를 **성립시키는** 것은 생명력 **점유**다.
생명력을 쓰는 것(소모)은 아니다.

| 구분 | 문구 형태 | 로우라이프 공급 |
|---|---|---|
| 점유 | `Reserves N% of Life` · `Reserve Life instead of Spirit/Mana` | **성립** |
| 소모 | `turning its Mana cost into a Life cost` · `Lose N% of maximum Life` | 아님 |

**왜 갈리는가**: 점유는 최대 생명력의 일부를 묶어 잔여를 *영구히* 낮추므로 로우라이프가
유지된다. 소모는 쓰고 나면 회복으로 돌아오므로 조건을 유지하지 못한다 — 로우라이프를
전제로 한 효과들이 상시로 켜져 있어야 하는 설계에서는 소모 경로를 공급으로 셀 수 없다.

또한 **내 생명력**이어야 한다. `Targets Cursed by you have at least 15% of Life Reserved`
처럼 적을 점유시키는 효과는 내 로우라이프 조건과 무관하다.

## 설계에서의 쓰임

로우라이프를 요구하는 효과를 빌드에 넣기로 했다면, **점유 경로를 먼저 확보**해야 한다.
소모 계열(생명력 전환·아탈루이의 사혈 등)로 대체할 수 없다 — 이건 수치의 문제가 아니라
조건 성립 여부의 문제다.

점유 축 검사는 `check_constraints`의 reservation 원장으로 한다(생명력 축 pool=100).
