---
name: build-generation
description: PoE2 빌드를 설계 루프로 생성·개정한다. 컨셉을 받아 KB 조회 → 성립 질문 → 제약 원장 기계 검증 → 3티어 조립 → PoB 실측까지. 빌드 설계·수정·검증, design.md 작성·갱신, 스킬/보조젬/트리/장비 선택, PoB 코드 생성 요청에 쓴다.
---

# build-generation

**정본 지침은 [AGENTS.md](../../../skills/build-generation/AGENTS.md)다 — 먼저 그것을 읽고 그대로 따른다.** 이 파일은
진입점일 뿐이라 규율을 여기 복사하지 않는다(두 벌이 되면 어긋난다).

## 시작 전 3가지

1. **기존 문서부터 읽는다** — 이어받는 설계면 `parse_design_doc(build_id)`로 `상태:` 줄과
   검증 큐를 먼저 본다. 새 설계면 건너뛴다.
2. **차단 경로를 먼저 조회한다** — `search_insights(scope="durable")`로 "무엇이 **안 되는가**"를
   본다. 이미 막힌 것으로 확인된 연쇄가 있고, 그걸 모르면 계산을 다 하고 나서 전제가
   무너진다(v6·CoMD 실측).
3. **결정 관문을 설계 초반에 적는다** — "이 컨셉을 계속 팔 값어치가 있는가"의 기준.
   나중에 적으면 이미 투자한 것을 정당화하는 쪽으로 기운다.

## 역할 분담 (AD-3)

판단·창의는 **이 스킬을 실행하는 에이전트**, 산수·검증·기록은 **엔진**. PoB는 계기다 —
효율을 추측하지 말고 측정해 읽는다(AD-8).

## 도구

설계 루프 `parse_design_doc`·`check_constraints`·`evaluate_objective`·`parse_pob` ·
조회 `search_kb`·`get_entry`·`related`·`search_insights`·`get_insight` ·
계산 `compute_pob`·`evaluate_delta`·`check_item_legality`·`assemble_pob`·`optimize_tree`

⛔ KB 질의를 파일 탐색(Grep/Read)으로 하지 말 것 — 실측 7분 vs 도구 1초.
