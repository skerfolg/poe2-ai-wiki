---
id: insight.whirlwind-absorbs-one-ground-only
label: IN_GAME
verified_by: 사용자 판정 2026-08-25 (와류 × 원소 지면 동시 보유 한도)
lang: ko
source: feedback
source_title: 와류는 원소 지면을 하나만 흡수한다
source_revid: 8a1c47d2
source_timestamp: 2026-08-25
feedback_id: 20260825-와류-원소-지면-동시-보유-한도
patch: 0.5.4b
---

# 와류는 원소 지면을 **하나만** 흡수한다 — 「연결된다」가 「쓸 수 있다」가 아니다

**판정**: 와류가 여러 원소 지면과 겹쳐도 **하나만** 흡수한다(사용자 인게임 확인
2026-08-25). 즉 **먼저 붙은 지면이 자리를 차지한다** — 맵의 잡 지면이 선점하면 강한
지면으로 덮어쓸 수 없다.

**왜 정본 문구로는 못 갈랐나**: `mechanic.whirlwinds`는 *"A Whirlwind that overlaps an
allied Elemental Ground Surface takes on **that** element…"* 라고만 적는다. 단수를
함의하지만 **동시 보유 한도를 명시하지 않는다**. 그래서 도구는 이 사슬을 「성립」으로
보고하는데 실제 운용에서는 지면 선점 때문에 못 쓰는 경우가 생긴다 — §0 ⑩(조용한 거짓
성립)의 상태 그래프판이다.

⚠ **같은 레코드의 다른 줄과 헷갈리지 말 것**: *"Trying to create a Whirlwind that would
overlap with an existing Whirlwind instead moves the existing Whirlwind and **grants it a
stage**"* — 이건 **와류끼리**의 규칙이고 **병합·강화**다. 지면 흡수의 배타와 **정반대
성질**이라 한 문단으로 읽으면 오판한다.

**도구에 무엇을 뜻하나**: `scan_state_edges`의 `ground_*` 축 소비 엣지는 **동시에 하나만**
성립한다. 지면 축 둘을 잇는 사슬은 「둘 다 켜진다」가 아니라 **「둘 중 하나」**다.

**설계에 무엇을 뜻하나**: 지면을 여러 종류 까는 구성은 와류 쪽에서 **이득이 안 쌓인다**.
반대로 다수 지면을 만드는 수단은 **선점 위험**이 되므로, 그 조합은 이득이 아니라 **대가**다.
