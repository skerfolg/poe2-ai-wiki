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
