# UI 독립 PoB 실행과 선택 PoK 연동 — 백엔드 소유·배포 협의안

상태: 2026-11-02 사용자가 A안과 UI 원격 반영을 승인했다. 기존 모듈 안에서 독립 worker를
구현한다. 아래 B안은 비교 대안으로 보존하며 채택하지 않았다. 배포·실제 동선 검증은 미완료다.

## 확인한 최신 요구

UI coho/4b86309의 AGENTS/HANDOFF-20261030은 사용자 확정 목표를 다음처럼 기록한다:
“pok-ui는 PoK 설치·접속·AI 없이 PoB의 수동 편집·계산 작업을 완결하는 것이 우선”이며
“PoB 백엔드의 독립 제공/공유 구조는 미결정이므로 먼저 설계”한다.
동시에 계산·게임 규칙은 형제 엔진에 두고 renderer에 복제하지 않는다.

현재 main/d15bdab은 XML 편집을 제공하지만 계산은 PoK 연결에 의존한다. coho는 원문·
버전·제안 수명을 보강했고, 독립 백엔드 자체는 구현하지 않았다. Root R6의 실제 수동
흐름과 선택 AI 연동은 이 목표를 보존하며 구현해야 한다.

## A — 기존 엔진 소유 PoB 코어를 독립 worker로 제공 (추천)

- `src/pok/pob`의 PoB 호출·원문/선택·소유 실행 구현은 엔진에 유지한다.
- 같은 모듈 안에 제한된 standalone worker 진입점을 추가한다. XML·선택 입력을 받아
  실제 PoB로 계산하고 입력 hash/버전·한계·오류를 반환한다. 빌드 판단/KB 조회 기능은 없다.
- UI main이 번들된 PoB worker·PoB snapshot·LuaJIT를 구동한다. 사용자는 PoK 설치나
  외부 PoK 서버 없이 수동 작업을 한다. renderer에는 JSON 계약과 표시/편집만 남긴다.
- PoK MCP/KB/생성은 별도 선택 연결이다. 연결 종료·불일치가 독립 수동 계산을 막지 않는다.
  연결 시 PoB pin/worker 출처·실제 지원 조합을 확인하고 자동 업그레이드하지 않는다.
- 같은 소스에서 UI용 계산 런타임을 빌드하고 manifest로 식별한다. 원본 PoB의 규칙이나
  엔진 Lua 어댑터를 UI 저장소에 복사해 따로 유지하지 않는다.

새 최상위 소스 폴더/설계 DB 없이 기존 pob 모듈과 UI main/resources 경계에서 진행할 수 있다.
다만 새 공개 실행 경계와 배포 산출물 계약이 생기므로 이를 승인받고 구현한다.

## B — 공통 PoB 코어를 별도 패키지로 분리

PoB adapter/runtime 계약을 독립 패키지로 추출해 PoK와 UI가 같은 버전으로 소비한다.
두 제품 독립성과 계산 규칙의 단일 소유를 유지할 수 있지만 새 패키지 경계·의존 방향·
릴리스/호환 정책을 정해야 한다. 현재 R5 동결 제품은 유지하고 후속 버전에서 분리한다.

## 두 안에 공통인 구현·검증 조건

- 승인된 데이터/캐시 경로 분리를 사용하며 원본 XML·설계 JSON 원문·미지 정보를 보존한다.
- UI v2 저장/적용/undo는 XML·설계·획득 메타데이터를 같은 리비전 단위로 다룬다.
  PoK 미연결의 수동 문서는 설계 기록을 필수로 요구하지 않는다.
- PoK 없음/종료 상태의 열기→수동 편집→실제 계산→저장/재시작을 검증한다.
- 선택 PoK 연결의 버전 일치/불일치, AI 제안 검토→원자 적용→undo를 별도로 검증한다.
- 기능 대응표와 대표 동선으로 지원 범위를 확인한다. 이 worker 추가나 메뉴 존재만으로
  원본 PoB 전체 기능의 동등성을 선언하지 않는다. 미지원 기능을 조용히 계산하지 않는다.

R5 기준/개선 제품과 공통 수집기는 이 결정으로 변경하지 않는다. UI의 다른 작업 트리와
원본 파일은 유지한다. 결정 전에도 기존 XML/기록 저장 계약의 독립적인 준비는 계속한다.

## 실제 계약 차이 감사 — 2026-11-01

r6-ui-current-engine-connect-v1/result.json의 실제 stdio 시험에서 현재 엔진은73도구와
read_design_record를 제공했다. UI d33b3c3은 compute_pob_xml/render_pob_item 부재로
incompatible를 반환하고 연결을 정리했다. 이 거절은 현재 지원 완료가 아니라 실제 갭이다.
아래는 구현 승인이 아닌 대응 설계이며, A/B 결정 뒤 같은 계약 생산자를 기준으로 검증한다.

| 기능 | 현재 엔진에서 확인한 경로 | UI d33b3c3의 기대 | 필요한 연결·검증 |
| --- | --- | --- | --- |
| 저장·설계 | runtime_paths, read_design_record의 record_json/record_ref/current_assessment | 별도 v2 문서와 원문 snapshot | 기록 소비·로컬 hash·저장 IPC 일부 검증. 실제 선택 PoK 연결의 버전 대조가 남음 |
| 정확한 XML 계산 | capture_design_material의 XML blob ref → compute_pob_document(xml_ref)의 문서 결박 receipt | compute_pob_xml(xml, stats), runtime identity 및 직접 stats | 단순 이름 alias가 아님. 원문/활성 선택/actual receipt/오류와 기한을 보존하는 adapter 또는 독립 worker 계약 필요 |
| 아이템 생성 | pob.roundtrip.build_items의 PoB 명세→실제 문구 및 daemon.build_item | ItemRenderRequest의 base/unique/rare ID·variant/mod/roll 선택 → text | 원시 PoB ID와 명세 의미를 실제 PoB builder로 연결. UI에서 모드 문구/수치를 조립하거나 KB ID로 대체하지 않음 |
| 편집 카탈로그 | KB 검색과 PoB raw 자료는 서로 다른 층 | CatalogExport v1의 base/unique/mod/gem/skill ID·class/tree·출처 | 독립 수동 편집이 KB 없이 쓰는 실제 raw exporter/번들 필요. KB 결과를 raw 카탈로그처럼 표시하지 않음 |
| 실행 식별 | server_info의 loaded/source commit·도구/capability와 실제 계산의 pok.pob-input-observation.v1 | RuntimeIdentity apiVersion1의 pok/pob/kb와 bundle manifest/catalog.source | 범위·해시 알고리즘이 다름. 기존 관측 SHA를 UI sourceDigest에 옮겨 동등성을 주장하지 않음. 공통 producer가 범위/버전/관측 한계를 명시해야 함 |
| 실행 수명 | 요청 ID·native budget·소유 자원/영속 회수·데몬 시작 관측 | Electron 관리 연결·취소/재연결 및 입력 provenance | worker/선택 MCP의 소유 수명과 UI 취소·마감·닫기 동선을 실제 실행으로 검증 |

참고 소스: 엔진 src/pok/mcp/server.py의 server_info/compute_pob_document,
src/pok/pob/execution_identity.py의 관측 범위(시각 asset·외부 native library 제외),
src/pok/pob/roundtrip.py의 build_items. UI src/shared/game-data.ts와
scripts/prepare-data-bundle.mjs는 runtime manifest와 raw catalog 출처 동등성을 요구한다.
이 감사는 KB/게임 지식을 파일로 조사한 것이 아니라 소프트웨어 입력/출력 경계의 코드 감사다.

## 결정 후 필요한 지원 조합

수동 backend와 선택 PoK 연결의 준비 상태는 분리해야 한다. PoK 없음/종료/불일치가
검증된 수동 XML 편집·계산을 막지 않아야 하며, PoK가 연결됐다는 것만으로 수동 카탈로그/
PoB 버전 일치를 인증하지 않는다. 현재 코드가 이 요구를 충족했다고 보고하지 않는다.

1. 독립 worker/공통 core의 actual producer가 PoB pin·읽은 데이터·adapter/실행기 관측과
   algorithm/scope/version을 낸다. Git HEAD나 캐시 경로만으로 실행 판을 인증하지 않는다.
2. 수동 카탈로그와 아이템 renderer는 그 producer의 같은 PoB 자료에서 생성한다.
   미수록/미지원·범위/기한·원문을 보존하며 renderer에 게임 규칙을 복제하지 않는다.
3. 선택 PoK는 자기 실행 식별과 지원 도구를 제공한다. 두 backend가 다른 판이면 결과를
   같은 기준으로 섞지 않고 AI 제안/계산의 source와 현재 문서 리비전을 함께 표시한다.
4. 실제 앱에서 PoK 없는 수동 열기/편집/계산/저장/재시작, 일치·불일치한 선택 PoK 연결,
   실제 모델 제안/검토/원자 적용/undo·중간 편집·취소·마감·닫기·재연결을 확인한다.
5. 검증한 조합과 미지원 조합을 배포 manifest/문서에 고정한다. 전체 PoB 기능 동등성이나
   게임 성립·품질 개선을 이 연결 구현 하나로 선언하지 않는다.

현재 저장 IPC/재시작, UI 기록 소비, v1/v2 복귀 시험은 이 목록의 일부 증거다.
독립 core 경계/배포 선택은 2026-11-02 A안으로 승인됐다. 원격 WIP 반영도 승인받아
d33b3c3 기반 UI와 검증 기록을 draft PR #3으로 공개했다. 독립 worker 기본 전환과
standalone 배포가 구현·검증됐다는 뜻은 아니다.
