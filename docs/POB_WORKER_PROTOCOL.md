# 독립 PoB worker — 초기 실행 계약

사용자가 승인한 A안의 구현 계약이다. 코어 소유는 `src/pok/pob`, 클라이언트는 UI main이다.
명시 경로 development와 파일 검증 bundle 프로필을 제공한다. Windows 번들 자체 초기화는
검증했으며 UI producer/consumer 연결과 배포 검증은 미완료다.

## 실행과 책임

`python -m pok.pob.worker`는 `--adapter-root`, `--pob-root`, `--pob-commit`,
`--luajit`, `--cache-home`을 받는다. 전부 명시적으로 전달하며 KB 조회나 프로젝트 표식
탐색으로 자산을 보충하지 않는다. 원래 `run_xml`/`PobDaemon`의 기본 경로는 유지한다.
worker는 XML을 BuildSpec으로 복원하지 않고 실제 PoB에 그대로 전달한다.

표준입출력은 한 줄당 UTF-8 JSON 하나다. 로그는 stderr를 사용한다. `hello`는 통신이
설정됐다는 뜻이며 Native PoB 초기화·배포 준비 완료를 의미하지 않는다.
클라이언트가 `initialize` 응답을 확인한 뒤 계산을 요청한다.

## 요청과 응답

요청: `{id, method, params?, timeout_ms?}`. ID는 세션 안에서 유일한 문자열이다.
ID 중복은 진행 중 응답과 혼동되지 않도록 채널 오류로 처리한다. 세션 요청 예산은8192이며
클라이언트는 필요한 시점에 정상 종료·새 인스턴스로 교체한다.

| method | params | 범위 |
| --- | --- | --- |
| initialize | 없음 | Native PoB 시작·입력 관측·개발 identity |
| runtime_info | 없음 | 초기화된 identity, 게임 성립/배포 인증 아님 |
| compute_xml | xml, stats?, expected_xml_revision? | 정확한 XML 계산·실제 입력 SHA·native meta |
| export_catalog | 없음 | KB 없이 실제 PoB 데이터에서 schemaVersion 2 카탈로그 생성 |
| render_item | kind, id, mods?, rolls?, variants?, quality? | 카탈로그 ID를 실제 PoB 아이템 원문으로 렌더 |
| build_native_item | spec_text | PoB 명세→실제 원문, 획득 적법성 검사 아님 |
| cancel | request_id | 현재 worker가 소유한 해당 요청만 취소 |
| shutdown | 없음 | 소유 Native daemon 종료·실제 정리 확인 |

응답은 `{id, ok, result? 또는 error?, execution?}`다. 초기화 기본 예산30초,
계산 기본/최대180초다. 진행 알림으로 기한을 연장하지 않는다. 계산은 한 번에 한 개이며
취소·종료는 입력 루프에서 계속 처리한다. 취소 요청 수락과 실제 정리 확인은 별개다.
`ExecutionScope`와 기존 Native 소유 실행을 재사용하며 정리 범위는 worker 소유 daemon이다.

입력 프레임은16MiB, XML은8MiB다. XML의 UTF-8 SHA와 expected revision이 다르면
계산하지 않는다. unknown 필드·비활성 세트·개행을 원문에서 제거하지 않는다.
비유한수는 JSON null과 `wire_normalizations`의 원래 값/경로로 보고하며0으로 대체하지 않는다.
소유자 stdin EOF는 진행 요청의 취소·Native 종료로 처리한다. 요청 후 즉시 EOF를 보내는
배치 실행 프로토콜이 아니다.

## identity와 제한

`pok.pob-worker-identity.v1`은 상대 파일명·실제 파일 바이트·런타임 구성요소를 사용한다.
프로세스별 원래 실행 관측은 별도 유지한다. 기존 관측 SHA는 컴파일된 코드의 파일명과
행 번호·실행 경로를 포함하므로 번들 이동 전후의 콘텐츠 ID처럼 재사용하지 않는다.
기존 UI `RuntimeIdentity.apiVersion=1`의 KB 필드를 빈 해시로 꾸며 채우지 않는다.

development의 PoB commit은 호출자 선언이며 upstream 출처 인증이 아니다. 실제 입력
바이트 관측과 PoB 계산 성공은 패키징 검증·게임 성립·좋은 빌드의 증거가 아니다.
외부 시스템 라이브러리·로드된 Native 모듈 전체는 검증 범위 밖이다.

`render_item`과 `export_catalog`는 실제 Native 검증을 통과했다. 복수 유니크 변형 편집은
원문 편집으로 명시적으로 돌려보낸다. `bundled_runtime`은 manifest를 검증한 실행에서만 true다.

## Windows 번들

`python -m pok.pob.worker_pack`은 새 출력 폴더에 Python 표준 라이브러리·PoB·LuaJIT·
기존 common/pob 코드와 Lua 어댑터를 복사한다. KB·MCP·site-packages는 포함하지 않는다.
실제 번들 Python으로 초기화 후 상대 경로·파일 크기·SHA-256 전체 목록을 봉인하고 다시
실행한다. `--allow-dirty`는 개발 검증용이며 배포 완료 표시가 아니다. macOS 패키징은 미구현이다.

worker 실행은 `--bundle-manifest <path> --cache-home <path>`를 사용한다. 선언된 Python
이외의 인터프리터, 추가/누락/변경 파일, 경로 이탈을 거부한다. 파일 읽기 오류는 검증 실패이며
해당 파일을 생략하거나 빈 해시로 대체하지 않는다. 전체 bundle identity와 기존 실행 관측은
별개로 보존한다.

2026-11-02 Windows 개발 번들 v2 자체 초기화·봉인 재실행은 성공했다. UI Node 자식
프로세스에서는 같은 번들의 `pob/src/Export/Bases/amulet.txt` 읽기가 EBADF로 실패했다.
직접 실행한 번들 Python은 같은 파일을 읽었다. 읽기 방식을 read-all로 바꾸어도 UI 실패가
남아 있으므로 읽기 크기나 Node 자체를 확정 원인으로 보지 않는다. 보안 설정 변경이나
검증 우회는 하지 않았다. 이 결과는 UI 연결·계산 성공으로 집계하지 않는다.


## 검증 범위와 제품 연결 상태 — 2026-11-02

| 범위 | 확인한 결과 | 남은 범위 |
| --- | --- | --- |
| 명시 자산 경로 | 기존 기본값 보존·별도 자산 Native2검사 통과 | 전체 Native156검사 통과 |
| KB 없는 worker | 실제 Native 계산·EOF·취소·카탈로그/아이템 렌더 검사 통과 | UI 전체 동선 |
| Windows 개발 번들 | 번들 Python·봉인 manifest·다른 경로 복사 후 실제 초기화 성공 | 최종 소스의 배포 패키지·클린 환경 |
| UI 연결 수명 | Node 자식 기반 전송·revision·동시 연결·정리 미확인·시작 기한 검사8개 통과 | 실제 Electron/번들 연결 |
| UI 카탈로그 | 별도 schemaVersion2 identity consumer 구현 | 실제13945항목·직업8개 소비 통과, main 연결 미완료 |
| PoK 선택 연결 | 독립 worker 코드는 KB/MCP에 의존하지 않음 | UI 기존 main의 계산 경로·선택 PoK 분리 미완료 |
| macOS 번들 | 코어의 기존 macOS 경로는 유지 | 새 standalone packager 미구현·미검증 |

실제 v2 번들을 복사한 위치에서 콘텐츠 identity가
`9a641abdd9d0b3f83b2dc6c5e7b317b7ae2e580b65abb0df0886b1327f49d14a`로
유지됐다. Python과 PoB가 실제 초기화된 결과이며 UI 성공으로 세지 않는다.
별도 시작 시간 측정은 hello40.875초·initialize50.000초·정리0.656초였다. 전체 Native
검사가 함께 실행 중인 현재 호스트의 값이며 격리된 성능 벤치마크가 아니다. 기존 UI
hello30초는 이 조건에서 부족하므로 UI 시작 전체에180초의 단일 절대 기한을 적용하고
initialize는 남은 시간과120초 중 작은 값을 사용한다. 정리 기한은 별도다.

Node 직접 읽기와 Node의 Python 자식 모두 원본/번들의 동일 txt 파일에서 EBADF를 냈지만
lua와 라이선스 md 파일은 읽었다. 직접 실행한 Python은 같은 txt를 읽었다. 이 차이는
환경 진단 근거이며 보안 제품·Node·Python 중 특정 원인을 확정한 결과가 아니다.
검증 목록에서 txt를 제거하거나 시스템 보안 설정을 변경하지 않았다.


## 선택 PoK 연결의 별도 식별

`server_info`의 `pob_runtime_declaration`은 `pok.pob-runtime-declaration.v1`이며
설정된 PoB commit만 선언한다. `claim=configured_pin_not_observed_execution`을 함께
반환한다. snapshot_available는 HeadlessWrapper 파일 표식의 존재이며 Native 준비 완료를
뜻하지 않는다. 별도 PoK/KB 연결의 대상 버전을 대조할 때 사용하며 worker identity나
실제 측정값의 출처 해시를 대신하지 않는다. pin을 읽지 못하면 unavailable/null이다.
`include_kb_diagnostics=False`는 KB 진단을 null로 생략하며 누락을0으로 표시하지 않는다.

UI의 agent 연결 프로필은 이 선언·Git 프로세스 식별(기존 약식 commit 허용)·서버 instance·
설계 조회 API를 확인한다. 기존 desktop 계산 별칭이 없는 최신 엔진도 선택 지식/설계
연결로 사용할 수 있다. 각 호출 전에 세션/소스 선언을 다시 확인한다. 수동 계산은 독립
worker만 사용하므로 선택 PoK 미연결/불일치가 수동 계산을 막지 않는다. PoK의 측정값을
수동 worker의 동일한 측정으로 인증하는 계약은 아니다.
