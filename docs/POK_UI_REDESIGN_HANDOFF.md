# pok-ui 세션용 PoK 재설계 연동 지침

2026-10-30. 정책 정본: [BLUEPRINT](BLUEPRINT.md).
세부 소비 계약/회귀: [검증 계획 §6](POK_REDESIGN_VALIDATION.md#6-pok-ui를-포함한-호환성-계획).
소스 관측과 후속 시험 입력: [UI 소비 계약 감사](POK_UI_CONTRACT_AUDIT.md). 실제 통합 검증 완료를 뜻하지 않는다.
엔진 기록 형식의 현재 경계: [설계·구성·근거 형식 감사](POK_DESIGN_FORMAT_AUDIT.md). R2 계약 확정 전에는 독립 UI 스키마를 새로 고정하지 않는다.

PoK는 PR #149 병합 `e7bd429`를 기준으로 생성 품질 저하 원인을 분리 검증한다.
이번 청사진 개정은 API 변경이나 새 엔진 배포가 아니다. 실제 사용 런타임을 별도로 확인한다.
현재 UI의 정상화와 개발을 계속하되 다음 경계를 유지한다.

- PoB 가져오기/복원·게임 의미 편집·계산·최적화·진단은 PoK에 요청한다.
  UI에 별도 계산 경로나 게임 규칙을 새로 만들지 않는다.
- UI는 원본 보존 XML, 작업 공간, 활성 세트 선택, buildId/baseRevision,
  계산 상태·오류 표시, 제안 검토·적용·undo를 담당한다.
- 현재 XML 편집과 정적 트리 렌더링은 유지한다. 의미 편집 이관은 계약 확정 후 진행한다.
- 동적 도구 목록을 사용하고 고정 도구 수/필수 최적화 호출 순서를 UI에 넣지 않는다.
- ready 여부, 계산 성공, 게임 성립, 미측정, 설계 품질을 하나의 성공 표시로 합치지 않는다.
  현행 필드를 먼저 정확히 표시하며 새 필드는 capability 확인 후 사용한다.
- `restore_pob_spec → compute_pob`의 현재 입력·진단과 세트 선택 동작을 fixture로 보존한다.
  복원 손실·미지원 구성은 사용자에게 표시하고 임의 기본값으로 감추지 않는다.
- 엔진 계약 변경은 추가형 우선으로 협의하며 엔진 버전/PoB 버전/스키마 지원 범위를 확인한다.
  현재 미구현 capability 협상을 이미 지원한다고 가정하지 않는다.
- 실제 모델 사용 검증과 합성 어댑터 테스트를 구분한다. 개인 XML/대화를 공개 fixture로 넣지 않는다.

UI 연동 불가 사유는 재현 입력·현재/기대 계약·영향을 PoK 작업 항목으로 남긴다.
사용자 검토 없는 AI 제안 자동 적용이나 UI에 엔진 기능 복제로 해결하지 않는다.

이 지침은 다른 세션에 자동 전달되지 않았다. UI 저장소를 이 작업에서 수정하지 않았다.

후속 합의: 구조화된 설계 기록의 목적·앵커(사용자 고정/필수 조건/잠정 구현/성능 후보)·미검증·재검토 대상을 UI가 같은 리비전으로 표시하는 방향이다. 기록 정본/렌더/API는 R2에서 확정하며 현재 필드를 임의로 만들지 않는다. 설계와 PoB를 함께 바꾸는 제안의 부분 적용·리비전 불일치를 방지하는 계약을 준비한다. AI의 다음 판단이나 앵커 규칙을 UI에 복제하지 않는다.


2026-11-01 R3 후속: 엔진의 현재 API/검증 범위는 POK_REDESIGN_CONTRACTS.md §14를 따른다.
UI 저장소는 이 후속에서 수정하지 않았다. 관측 meta.nativeSelection의 active_index는
활성 효과 순번, gem_index는 native 젬 슬롯이며 서로 바꿔 쓰지 않는다. native 그룹 순번을
원본 XML 그룹 순번으로 임의 치환하지 않는다. 관측 부재는 첫 스킬이나 정상 검증으로
만들지 않는다. 모드 목록 존재가 인게임 공급/유지 가능성을 뜻하지 않는다.
배포 런타임에는 scripts/pob_selection.lua와 이를 호출하는 두 driver를 함께 넣고
실제 파일 해시/코드 버전·cache protocol6을 확인해야 한다. 현재 stage-runtime은 준비된
런타임 디렉터리를 복사하므로 개발 checkout 변경만으로 기존 번들이 갱신되지 않는다.
이 반영·실제 번들/GUI 검증은 R6에서 남아 있다.

### R3 실행 감독을 UI에 연결할 때 (아직 UI 미구현)

server_info.capabilities.request_execution의 server_instance/예산을 읽는다.
긴 호출 전 클라이언트가 새32자리 hex request_id를 만들고 `_meta.pok_execution`에
request_id/timeout_s를 전달한다. timeout_s는 UI/SDK의 총 상한에서 정리 유예5초와
전송 여유를 뺀 값 이하로 설정한다. 서버 기본/최대는600초이며 capability를 우선한다.
진행 알림으로 총 기한을 갱신하지 않는다.

응답의 `_meta.pok_execution` 실행 참조도 bridge에서 보존해야 한다. content/structured
결과와 다른 메타데이터를 덮어쓰지 않는다. 초기 응답을 못 받았어도 위에서 만든 ID와
server_instance로 참조를 구성해 get_execution_status/cancel_execution을 호출할 수 있다.
로컬 UI/SDK 대기 태스크 취소만으로 서버 작업이 중단됐다고 표시하지 않는다.
명시 notifications/cancelled 또는 cancel_execution을 보내고 worker_finished 및 등록
자원 종료 상태를 확인한다. 종료 미확인/아직 실행 중을 cancelled로 바꾸지 않는다.

같은 서버에서 완료 결과는 read_execution_result로 회수할 수 있으나 새 서버 인스턴스나
정리된 기록은 unavailable이다. 완료/실패로 추정하지 말고 원래 문서 리비전을 보존한다.
이 경로는 현재 프로세스 내 보관이며 서버 재시작 복구는 미구현이다. 계산 결과 회수도
자동 적용을 뜻하지 않으며 원래 XML/설계 리비전을 대조해야 한다.
UI 저장소·번들·실제 GUI 연동은 이 후속에서 수정/검증하지 않았다.

server_info 응답 크기 교정: cap 요약은 inline으로 유지하고 상세는
capabilities.details_tool(현재 get_server_capabilities)에서 읽는다.
request_execution의 ID/기한/제어 도구 필드는 요약에 유지하지만 세부 보관/선점/프로세스 트리
한계 등 전체 기능 설명은 상세 응답을 사용한다. 초기 식별을 저장 결과 notice로 오인하지 않는다.

데몬 관측 인계: get_server_capabilities.daemon_startup_observation에 형식/조회 도구가 있다.
inspect_pob_runtime은 기존 공유 데몬만 조회하며 busy/미시작을 임의 실행/완료로 바꾸지 않는다.
계산 meta.daemon_execution.startup은 시작 시점의 관측이므로 현재 파일 버전으로 표시하지 않는다.
현재 파일 비교는 observe_current=True이며 큰 조회가 될 수 있다. PID/generation과
process_state를 함께 보존하고 과거 last_startup을 현재 실행으로 취급하지 않는다.
이 메타데이터도 실제 native 모듈 전체 인증은 아니며 실제 UI/번들 적용은 아직 미수행이다.

영속 실행 연결: recover_execution은 기존 참조로 검증된 저장 checkpoint를 회수하며
현재 서버 live cancel/status와 구분한다. Production은 시작/종료를 영속화하고 입력 원문과
CallToolResult JSON을 보존한다. 서버 중단 뒤 시작만 있으면 worker_finished=unknown이다.
완료 결과 회수도 자동 replay/현재 XML·설계 적용이 아니며 실제 current revision을 다시 대조한다.
저장 실패는 persistence.error와 실제 live 결과를 구분하고 UI가 이를 성공 도장으로 숨기지 않는다.
실제 stdio 재기동/중단과 PoB 취소 회수는 검증했으나 실제 UI/번들 채택은 아직 미수행이다.

예산 프로필 후속: generic600초를 모든 도구의 공통 기본으로 해석하지 않는다.
get_server_capabilities.request_execution.budget_profiles에서 도구별 default/maximum을 읽는다.
단일 계산180초, 선택 탐색 기본300초/최대1200초이며 메타 기한과 명시 time_budget_s가 함께
있으면 짧은 값을 적용한다. UI/CLI 자신의 총 기한에서 정리/전송 여유를 뺀 더 짧은 한도를
우선한다. 실제 탐색이 내부 예산으로 더 일찍 끝나는 것과 transport 상한을 구분한다.

대형 결과 소비 시 주의: 실제 FastMCP Client에서 배열형 도구의 큰 응답은 원문
structuredContent.result에 stored_tool_result/result_ref가 있지만 SDK의 자동 data 객체는
Root로 파싱되어 참조 필드가 생략된 사례를 확인했다. transport의 원문 structuredContent
(없으면 content의 JSON)을 먼저 해석하고 x-fastmcp-wrap-result 계약에 따라 한 번만 풀어
공식 get_tool_result 페이지로 회수한다. data 객체를 dict로 간주하거나 미노출 참조를
누락된 계산 결과로 판정하지 않는다. 원문 wire의 참조는 보존되어 있었으며 이것을
PoK 저장 손실로 단정하지 않는다. R6 실제 클라이언트·모델 어댑터에서 대조할 항목이다.

R6 현재 코드 읽기 감사(수정 없음): UI는 f6bc07b/작업트리 clean이며 schemaVersion1,
workspace.v1.json, XML-only undo/제안·계산 상태다. 새 design_ref/record_json/material/메타데이터를
같은 리비전으로 보존하는 저장·원자 적용/undo는 미구현이다. main/pok.ts는 실제 원문
structuredContent를 소비하므로 Python SDK data Root의 파싱 차이와 구분한다.
또한 UI가 전송하는 POK_DATA_HOME/POK_CACHE_HOME을 현재 engine/common/paths.py가
읽지 않는 실제 불일치가 있다. POK_RUNTIME_PATH_PROPOSAL.md에 기존 기본 경로 유지와
명시 설정 시 데이터/캐시 분리안을 준비했고 AGENTS 철칙1에 따라 사용자 협의 중이다.
승인 전 엔진 저장 경로·UI 코드는 변경하지 않았다. 별도 번들 리소스/serve 지원도
실제 구현을 확인해야 하며 문서의 배포 설명만으로 지원된다고 보지 않는다.

사용자 승인 후 경로 계약 구현: POK_DATA_HOME→그 아래 artifacts, POK_CACHE_HOME→폴더 자체,
미지정 기존 기본값·명시 root 우선·빈/상대/쓰기 실패 no fallback을 지원한다.
server_info.runtime_paths의 resource_root/artifacts_root/cache_root와 runtime_storage capability로
실제 적용을 확인한다. 관련28단위와 독립 설정13단위, 실제 stdio3서버의 재연결/기록 격리/
index.sqlite·PoB cache hit/miss 검증 통과(r6-storage-native-v2.xml).
UI f6bc07b의 기존 env 전달을 현재 엔진이 소비하지만 실제 GUI/번들 전체 검증은 아직 남았다.
R5 기준/개선 동결 제품은 변경하지 않았다. 이 승인된 경로 계약은 재확인 없이 진행한다.

## 2026-11-01 현재 소비 상태와 복귀 시험

과거 f6bc07b 미구현/협의 중 표기는 관측 시점 기록이다. UI PR2는 병합됐고 원본
UI 저장소 main은 d15bdab으로 동기화했다. 새 R6 작업은 별도 Orca worktree
pok-r6-design-records / skerfolg/pok-r6-design-records에서 main과 coho/4b86309를 통합 중이다.
merge는 전량 check/build 전이므로 아직 commit/PR 완료로 보고하지 않는다.

- 새 v2 문서는 XML·설계 원문/참조·획득 원문을 같은 입력 리비전/undo로 보존한다.
- 설계 조회/표시·엔진 원문 hash·현재 XML/metadata hash·AI 전체 입력 제안은 구현했고
  단위와 실제 렌더러 대역 동선/두 해상도/늦은 hash 응답을 확인했다.
- 실제 Electron IPC·실제 모델·연결/배포 조합·독립 수동 계산은 미완료다.
  현재 coho의 compute_pob_xml/render_pob_item 및 runtime identity 계약과 엔진 공개 계약의
  차이를 우회해 ready로 표시하지 않는다. standalone backend 경계 협의는 별도 대기다.
- 승인된 POK_DATA_HOME/POK_CACHE_HOME은 엔진에서 구현/실제 stdio 검증됐다.
  R5 동결 개선판7875ea2와 이후 현재 엔진의 storage 변경은 같은 제품 버전이 아니다.

r7-ui-storage-rollback-v1/result.json은 실제 구/신 저장 모듈로 v1→v2 이행→구 UI 재사용→
새 UI 재개의 보존을 확인했다. 구 UI에서 v1을 저장해도 v2는 바뀌지 않고 새 UI는 v2를
계속 사용한다. v2 수정은 구 UI로 자동 역변환하지 않는다. v2 파일/JSON export를 유지한 채
구 UI는 보존된 v1 분기로 돌아가며, 이후 분기 합치기는 명시적인 가져오기/제안으로 처리한다.
이 시험은 합성 데이터의 저장/파일 모듈 범위이며 구 실행 바이너리/PoB 버전 복귀는 아니다.

### 실제 앱 번들·file UI 검증 추가 — 2026-11-01

현재 R6 소스의 전체 합성 단위165개(파일별 직렬)·타입/계층 검사 후 npm.cmd run build를
수행해 main/preload/renderer 산출물을 확인했다. r6-ui-app-build-v1.json은 파일 SHA를 보존한다.
r6-electron-file-ui-v1은 그 번들을 실제 Electron44.5.1에서 file://로 읽어 설계 카드4개,
실제 저장 IPC·페이지 재로드·과거 설계와 바뀐 XML의 불일치 표시를 확인했다.
이는 개발 서버 대역보다 넓은 앱 로드 증거지만 설치 패키지/게임 backend·실제 모델의
전체 지원 조합 검증은 아니다. 앞선 '전체 build 대기' 표기는 앱 소스 번들에 한해 대체된다.
독립 backend 선택/실제 engine desktop 계약·설치 패키지·모델/오라클 동선은 남아 있다.
