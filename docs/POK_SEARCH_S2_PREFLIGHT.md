# S2 준비 상태

2026-11-05. 아직 평가 동결/모델 실행 전이다.

## 확인한 실행 환경

- 최신 소스 MCP를 별도 프로세스의 FastMCP Client로 호출했다.
  저장 응답을 get_tool_result로 회수한 실제 loaded/source commit은 모두 dd6559f,
  source root는 `.local/pok-search-revision`이다. 연결된 기본 MCP9f016e3과 구분한다.
- 결과는 `artifacts/reviews/search-revision-s2/identity-fields.json`과 원본 참조에 보존.
  최초 server_info 반환은 대형 결과의 저장 안내였다. 이를 직접 identity 객체처럼 읽어
  출력한 null은 실제 identity 값이 아니며, 저장 결과 회수로 바로잡았다.
- PoB 핀은5d173cbf8c9cf394a975cbb813f19d0b6dc67ea6, LuaJIT 경로를 확인했다.
  작업 트리의 기존 snapshot 경로에 원래 고정 snapshot을 가리키는 junction을 생성했다.
  게임 데이터/PoB 원본은 수정하지 않았다. 실행 전 파일 해시 고정·검증은 아직 남는다.
- Codex CLI0.166.0의 실제 exe를 찾았다. 버전 조회만 했으며 모델 호출은0회다.
- 샌드박스에서 MCP의 임시 execution.json 작성이 권한 오류로 실패했다. 정상 권한
  재실행에서 조회가 완료됐다. 이 환경 실패를 제품/모델 품질 실패로 세지 않는다.
- get_tool_result의 limit2000은 지원 범위1–100을 벗어난 호출 오류였다.100으로
  수정해 같은 저장 결과를 회수했다. 제품 코드를 변경하지 않았다.

## 실행기 재사용 방향

기존 skills/build-generation/product_campaign.py의 run_trial은 입력/참조 SHA 검증,
trial별 저장 공간, 총시간 및 phase 시간, 실제 제출물 감사를 지원한다. 새 생성 솔버나
별도 실행기를 만들기 전에 이 경로를 단일 phase2700초로 구성한다.
두 정책 모두 동일 product 서버 전체 도구를 제공한다. raw-reference 제한군은 사용하지
않는다. 기존4개 참조 스킬/문서를 동일하게 제공하고 정책 안내만 명시적으로 다르게 한다.

## 신규 과제 후보 — 미확정

MCP에서 다음 사실을 조회했다. 전체 결과는 같은 preflight 디렉터리에 보존했다.

- T1 후보: 해골 방화범 기반 소환수와 정신력/생명력의 자원 배분. Skeletal Arsonist의
  정신력 점유와 Beidat's Will의 생명력 점유/정신력 공급을 확인했다. 추가 공급을 얻는
  단일 선택과 실제 소환수·방어 배분이 함께 달라지는지 볼 수 있는 후보이다.
- T2 후보: Falling Thunder의 Power Charge 소비에 따른 효과와 Melee/Projectile
  모드 차이를 확인했다. 무처치 대상의 공급·소비 반복과 소비에 덜 의존하는 대안을
  비교할 수 있는지 확인할 후보이다.

둘 다 새 컨셉 후보일 뿐 완성 참조·정답·평가 과제로 확정하지 않았다. T1 노드의
서술에는 과거 다른 Infernalist 빌드 사례가 포함돼 있다. 이를 ‘미공개 참조’라고
포장하지 않고 참가자에게 줄 재료와 기존 KB 노출 범위를 명시해야 한다.

## 아직 닫아야 할 사전 조건

1. 각 후보의 필요한 부품·제약·미모델링을 MCP로 확인하고, 실제 측정/최종 PoB
   생성 경로가 있는지 모델 호출 없이 확인한다. 입력/효과 단위가 잘못된 시험을 피한다.
2. 완성 조합이나 최종 우열을 제공하지 않는 동일 재료 팩을 구성한다.
3. 신규 과제 요구·채점 기준·정책 차이·실행 순서·model/effort/상한을 사전 고정한다.
4. 공개 원문과 실행 payload 해시, snapshot/코어 출처, 실패/중단 및 조건부 추가 실행
   판정을 manifest에 기록한다. 운영자/평가자의 정책 노출 한계를 밝힌다.
5. CLI 인증/지원 설정과 실제 MCP/native 왕복을 확인한다. 모델 capability 확인을
   빌미로 승인 밖 예비 모델 시험을 시작하지 않는다.

S2는 진행 중이다. 판단 평가4회와 조건부 발견4회의 승인 한도는 그대로 유지한다.
