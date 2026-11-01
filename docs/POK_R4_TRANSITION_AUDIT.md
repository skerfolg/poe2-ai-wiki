# R4 전환 사전 대조 — 2026-11-01

전체 통합 검사 중 구현을 바꾸지 않고 현재 지침/관문을 읽어 다음 변경 위치를 식별했다.
이 문서는 원인 입증이나 R4 구현 완료가 아니다. BLUEPRINT/ROADMAP과 R2 계약을 따른다.

| 현재 강제 지점 | 확인한 소스 | R4에서 대조할 요구 |
|---|---|---|
| compute_pob/assemble_pob 앞 procedure refusal | mcp/tools/build.py:_procedure_refusal, engine/procedures.py | 능력치 선택 누락/미확인과 희귀 출처 없는 수동안을 구분. 사실 진단을 유지하면서 호출 순서/optimizer 도장을 필수 해법으로 오독하지 않게 함 |
| 최종 recommendation readiness | engine/optimization_readiness.py:optimization_readiness | 현재 version1 계약의 의미 보존. 명시 v2에서 최종 주장/현재 구성에 맞는 실제 대체 근거를 허용하고 거짓 완료는 차단 |
| unique 최적화 실행 흔적 | engine/provenance.py:_REQUIRED_PROCEDURES,missing_procedures | optimize_items 흔적 부재는 미실행 자체가 아니라 unverified라고 이미 구분함. 유효 대체 탐색/측정 근거와 같은 범위를 판단할 경로가 필요 |
| 기본3티어 확장·정해진 생성 순서 | skills/build-generation/AGENTS.md | 사용자 요구 티어/목표와 구분. 공격→방어 고정 순서·매번 전체 확장이 자율 탐색/조기 계산을 막지 않게 함 |
| 조립 지침의 재량 제거/순서 준수 문구 | skills/build-assembly/AGENTS.md | 정본/정확성/적법성/근거 보존 의무는 유지. 창의적 선택과 구현 순서를 동일한 제약으로 묶지 않음 |
| 기존/백지 선택 질문 | skills/build-generation/AGENTS.md §0 | 대상이 이미 명확하면 재질문하지 않는 기존 예외를 보존. 실제 사용자 취향/고정 변경 협의까지 일괄 제거하지 않음 |
| 유한 탐색·초기 선택 재개방 | mcp/tools/tree.py와 engine/tree·items·rares 관련 생산자 | 이미 좋은 기능을 재사용하고 fixed base/scope/termination/missing과 공동 재투자 경로를 조사 |

변경 원칙: 감지 가능한 누락/현재 입력 불일치는 도구가 신고한다. 어떤 빌드를 고를지는 AI/사용자
판단으로 남긴다. 원장/Markdown/PoB가 같은 리비전을 가리키게 하고 문서만으로 새 규율을 강제했다고
말하지 않는다. v1 폐기/기본 경로 전환과 UI 채택은 R7 검증 전 미리 수행하지 않는다.

## 첫 구현: 명시 입력 계산

`compute_pob(input_policy="explicit")`은 주어진 스펙을 자동 채움 없이 계산한다.
능력치 선택 누락과 수동 희귀 출처 누락은 `calculation_contract.procedure_diagnostics`에
그대로 남긴다. 추천 검사나 인게임 성립 인증을 했다고 반환하지 않는다. 기본값 `legacy`와
조립 관문은 유지하며 capability에서 새 경로를 명시한다. 실제 MCP 포함23검사 및 해당
두 소스 mypy/Ruff가 통과했다(`r4-explicit-calculation-v1.xml`).

이는 불완전 탐색안을 계산하는 계약이다. XML/스펙 자체가 파싱되지 않거나 native 계산이
실패하는 경우까지 성공으로 바꾸지 않는다. 추천 v2의 저장 근거 검증, 유한 탐색 감사,
공동 재투자 실물 및 생성/조립 스킬 개편은 아직 구현하지 않았다.

## 추천 v2 저장 비교 경로 — 구현 중

optimization_contract={version:2,required_components:["items"],comparisons:[{result_id,
selected:"baseline" 또는 실제 variant 라벨,reason}]}를 명시하면 저장된 evaluate_delta
원본을 내용 해시로 읽고 실제 선택 입력의 서명/config와 현재 구성을 대조한다.
실제 변경된 구성 영역만 커버하며 비교 누락/미측정/진단 미해결/빈 통계/동일 대안은 거부한다.
optimizer 호출 도장은 요구하지 않는다. 선택 이유는 호출자 판단으로 표시하며 게임 성립·
전역 최적/품질 인증은 하지 않는다. 저장소는 로컬 신뢰 경계이며 암호학적 실행 인증이 아니다.
기존 v1과 합계105검사 통과(r4-comparison-readiness-v2.xml), 해당 mypy/Ruff 통과.
이는 첫 비교 검증 경로다. 실제 MCP/native 추천·출고·수동 아이템 경로와 전체 다층 판정,
대안 재개방·유한 탐색 및 스킬 개편은 계속 미완료다. 아직 제품 기본 경로로 전환하지 않았다.

실제 통합 보강: assemble_pob(input_policy=explicit)은 수동 희귀의 실행 도장 요구와
숨은 autofill만 생략하고 능력치 선택/정적/아이템/소켓/실제 native 편집 검사와 추천 근거
검사를 유지한다. r4-comparison-native-v3.xml에서 실제 MCP evaluate_delta 저장→v2 선택→
명시 조립→공유 코드·원래 선택 장비 보존을 확인했다. 관련 단위127검사 통과.
출고 엔진에서 정규화한 스펙으로도 근거 일치를 다시 검사했다. capability에 지원 범위를
추가했다. 전체 R4나 게임 성립 검증을 완료한 것은 아니다.
