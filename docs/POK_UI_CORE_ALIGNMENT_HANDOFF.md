# 현재 UI 경로와 PoK 코어 — 읽기 전용 인계

2026-11-04. UI 코드는 변경하거나 병합하지 않았다. 아래 차이는 현재 코드/참조에서 관측한 것이며, 다른 세션의 의도를 추정하지 않는다.

## 실제 관측

| 대상 | 관측한 경로 | 검증과 한계 |
|---|---|---|
| UI main `d15bdab` | XML-only 문서/undo, PoK MCP의 복원→계산, schema1 | 실제 새 MCP/PoB 연결에서 비첫 활성 세트의763개 숫자와 입력 문서 보존 확인. GUI/모델 제안/설계 기록 지원의 증명은 아님 |
| 기존 R6 후보 `45951aa` | schema2 설계 snapshot·획득 메타데이터, Python worker 클라이언트 `pok.pob-worker.v1` | 실제 정식8b4f226 봉인 worker로 연결·763개 숫자 동일. 기존 resources/pok-runtime/.gitkeep WIP는 그대로 |
| 현재 별도 UI 작업 참조 `coho/42ad5f0` | `PobRuntime` 및 UI/runtime/pob의 별도 원본 PoB Lua 연결, schema1 | R6 Python worker 클라이언트 파일이 이 참조에 없음을 확인. 현재 다른 세션의 UI 구현이며 여기서 실제 GUI·런타임을 실행/수정하지 않음 |

coho의 PoB 원본 호출은 자체 게임 계산기를 구현했다는 뜻이 아니다. 다만 코어 소유·배포·프로토콜·설계 기록 결박이라는 기존 R6 계약과 자동으로 같다고 취급할 수 없다. main과 R6 후보를 검증했다고 coho 전체를 검증했다고 하지 않는다.

## 확정된 기존 방향

BLUEPRINT §1/§3은 UI용 PoB 해석·복원·계산도 코어 책임으로 둔다. ROADMAP R6의 승인 A안은 기존 src/pok/pob 소유를 유지하고 독립 worker를 UI에 포함하며 PoK/KB/AI 연결은 선택 사항으로 둔다. 새 공용 패키지나 UI의 별도 게임 판단을 만들지 않는다.

## 다음 연결의 구체적 선택지

### 기존 방향을 유지하며 coho 기능 보존 — 제안

현재 UI를 과거 R6 코드로 덮지 않는다. coho의 원본 PoB 연결을 코어 소유의 배포 자산/버전 계약으로 연결할지, Python worker에 필요한 원본 PoB 기능을 추가할지를 먼저 정한다. 선택에 따라 파일 소유·프로토콜이 바뀌므로 여기서 임의 이동/병합하지 않는다.

원본 Lua 연결을 코어 자산으로 수렴하는 경우 검토할 실제 파일은 다음14개다:

`worker.lua`, `editor.lua`, `inspect.lua`, `calcs.lua`, `party.lua`, `tree.lua`, `tree-state.lua`, `tree-workspace.lua`, `item-controls.lua`, `item-popups.lua`, `equipment.lua`, `loadouts.lua`, `loadout-management.lua`, `skill-groups.lua`.

현재 UI의 `PobRuntime` 전송/화면 책임은 유지하고, 코어가 upstream pin·배포 자산·원본 편집/계산 어댑터의 소유와 호환 계약을 책임지는 형태를 비교할 수 있다. 기존 Python worker/MCP 소비자를 제거하지 않는다. 실제 이전은 구체적 소유/입출력·복귀 계획을 확정한 후 수행한다.

### 별도 런타임을 계속 유지하는 경우

이는 기존 A안/청사진과의 경계 차이를 명시적으로 합의해야 한다. 같은 XML이라는 이유만으로 수치/근거를 교환하지 말고 실제 PoB pin·트리·스키마·출처를 대조하며, 다른 엔진에서 낸 근거를 현재 결과로 재사용하지 않는다.

## 공통 검증 입력과 이미 준비된 산출물

- 공개 fixture v2: 비첫 활성 아이템/스킬 ID37, 트리 순번2. 첫 비활성 프로필은 스킬레벨1·장비 없음·노드 없음으로 구별된다.
- raw native와 현재 main MCP 소비자, R6 worker 소비자의 수치 비교 및 단일 편집 후 원본 복귀를 각각 기록했다.
- 정식 코어 번들8b4f226: 공식 upstream 배포 자산 목록, HeadlessWrapper·license·manifest, KB/engine 패키지 없음. 포함 파일 전량 무결성 검사는 유지한다.
- 기존 전체 소스 복사 번들의 Node 읽기 실패와 모든 읽기 대조·시제품은 별도로 보존했다. OS 오류 원인을 해결했다고 주장하지 않는다.

## 아직 완료가 아닌 흐름

현재 실제 UI 개발 경로의 합의/소비, 원자적 설계+PoB 적용/undo, 실제 GUI, 실제 모델 제안→검토→적용→undo, 최종 애플리케이션 번들과 Mac 검증은 이 자료만으로 완료되지 않는다. 사용자 선호와 #188 품질 판정도 별도다. 다른 세션의 작업을 추측해서 완료 처리하거나 새 모델 실행을 임의 추가하지 않는다.

이 문서는 로컬 인계 자료다. 다른 세션에 메시지를 보내거나 UI 저장소를 수정하지 않았다.
