# UI 런타임 저장 경로 — 승인된 계약

상태: 2026-11-01 사용자가 선택 환경변수 경로 분리를 승인했다. 엔진 구현과 실제
MCP 재연결/검색 인덱스/PoB 캐시 검증을 완료했다. 전체 UI·번들 통합은 별도다.

## 승인 전 확인한 불일치

UI f6bc07b의 `src/main/index.ts`는 연결 시 `<userData>/engine`과
`<userData>/cache/pok`를 전달한다. `src/main/pok.ts`는 이를 `POK_DATA_HOME`과
`POK_CACHE_HOME` 환경변수로 만든다. 승인 전 PoK의 `common/paths.py`는 해당 변수를
읽지 않고 저장소의 artifacts/var를 사용한다. checkout과 읽기 전용 번들의 실제 연결에서
같은 저장 정책이 성립했다고 할 수 없다.

## 제안: 명시 설정에서만 쓰기 경로 분리

| 설정 | 의미 | 미지정 기본값 |
|---|---|---|
| POK_DATA_HOME | 실행 데이터의 상위 폴더. `artifacts_dir()`는 그 아래 artifacts를 반환 | 기존 `<project_root>/artifacts` |
| POK_CACHE_HOME | `var_dir()`가 반환할 캐시 폴더 자체 | 기존 `<project_root>/var` |

UI의 기존 인자를 적용하면 산출물은 `<userData>/engine/artifacts`, 캐시는
`<userData>/cache/pok`에 놓인다. KB/스키마/PoB는 계속 정본·리소스에서 읽으며
artifacts/var를 정본으로 사용하지 않는다. 새 최상위 소스 디렉터리나 별도 설계 DB를 만들지 않는다.

명시적인 함수 인자 `root=...`가 있으면 환경변수보다 우선해 기존 테스트·도구의
격리 루트 의미를 보존한다. 환경변수는 절대 경로만 받고 상대 경로는 오류로 보고한다.
지원하지 않는 변수나 읽기 전용 위치의 쓰기 실패를 다른 폴더로 조용히 폴백하지 않는다.
실제 적용된 리소스/산출물/캐시 경로를 server_info 진단에서 구분해 표시한다.

기존 artifacts를 자동 이동/삭제하지 않는다. 변수 미지정 CLI는 기존 경로를 그대로 쓴다.
이행이 필요하면 원본을 유지한 명시 작업으로 처리하며 UI의 v1→v2 workspace 이행과
엔진 산출물 경로 이동을 같은 동작으로 혼합하지 않는다.

## 검증 범위

- 미지정 기본 동작과 명시 root 우선, 상대 경로/권한 오류의 명확한 실패.
- 서로 다른 데이터/캐시 루트의 실제 MCP 기록·계산·재연결 격리.
- UI checkout과 번들 런타임의 실제 적용 경로, 앱 리소스에 쓰지 않는지.
- 기존 참조는 원래 저장소에 남고 자동으로 새 루트에서 존재한다고 가정하지 않는지.

경로/기존 server_info·무결성 관련28단위 통과. 실제 r6-storage-native-v2.xml에서는
새 stdio 서버3개로 같은 데이터 재연결의 기록 복구/cache hit와 별도 공간의 기록 미존재/
cache miss, 지정 캐시의 index.sqlite·PoB 캐시 생성을 확인했다. v1 테스트의 없는 cached
필드 가정은 실패 원본으로 보존하고 실제 meta.execution_inputs.cache 진단으로 보정했다.
R5의 기준/개선 동결 제품은 이 변경으로 수정하지 않았다.

별도 번들 리소스 루트·CLI 배포 형태는 추가 실제 감사 대상이다. 이 제안으로 전체
패키징과 R6/R7을 완료한 것으로 보지 않는다.
