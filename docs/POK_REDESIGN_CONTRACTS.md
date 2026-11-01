# R2 계약 명세 — 설계·실물·근거·소비자

2026-11-01. [R1 결론](POK_REDESIGN_R1_FINDINGS.md)에 따른 R2 계약/시험 명세다.
아래 의미·v1 기록/봉인 표현·API/호환 매핑을 R3 구현 기준으로 채택했다.
계약 확정은 구현 완료나 UI 호환의 인증이 아니다. [소유 후보 검토](POK_REDESIGN_RECORD_OPTIONS.md)와
[현재 형식 감사](POK_DESIGN_FORMAT_AUDIT.md)가 관측 근거다.

## 1. 소유와 기존 경계

호출자의 작업 공간이 현재 설계와 현재 실물을 소유하고 PoK는 명시적으로 받은 입력을
검사·변경·측정한다. 서버에 별도의 가변 현재 헤드/설계 DB를 추가하지 않는 B를 채택한다.
이는 기존 UI 작업 공간 소유/중복 가변 편집 금지 방향의 상세화이며 새 저장 경계는 없다.
UI는 현재 XML과 봉인된 설계 원문/참조를 함께 저장하고 CLI 에이전트는 반환된 체크포인트를
재개한다. 최신 파일 시간으로 현재 분기를 고르지 않는다. 다른 PC에서는 선택한 체크포인트
묶음을 전달하며, 계산 캐시가 없어도 기록/원본을 열 수 있어야 한다.

물리 모듈과 의존 방향은 유지한다. 아래는 기존 모듈 안의 구현 책임 후보이며 새 서비스나
최상위 디렉터리 추가 승인이 아니다. 경계 변경이 실제 필요해지면 구체적 안으로 협의한다.

| 기존 영역 | 책임 | 포함하지 않는 것 |
| --- | --- | --- |
| artifacts | 순수 설계 기록 형식·원문/체크포인트 I/O·안정적 문서 표현 | PoB 계산, 게임 의미 재판정, 전역 현재 헤드 |
| engine | 명시적 기록/구성 변경, 의존 변경 신고, 실제 근거 검증/결합 | 메커니즘 선택 솔버, 도구 순서 결정 |
| pob | 원본 XML/세트·모드 식별, 명시적 편집/복원/계산, 손실 범위 | 사용자 목적이나 앵커 중요도 판단 |
| mcp | 요청/버전/기한/진행·취소, 작은 결과와 상세 참조, 체크포인트 전달 | UI의 현재 문서 상태 소유 |
| skills+AI | 조건/공급자 분리, 다음 질문과 대안, 의미 검토·선택/기각 | 형식 검사 통과를 좋은 빌드 인증으로 부르기 |
| pok-ui | 현재 문서·설계+XML 원자적 적용/undo·검토·늦은 결과 거절 | 독립 게임 규칙/계산기, 서버와 별도의 같은 결정 편집 |

## 2. 서로 다른 식별자

| 식별 | 의미와 변경 조건 |
| --- | --- |
| design_id | 한 논리 설계의 안정적 ID. 날짜/파일 위치나 UI 숫자 revision과 다름 |
| design_revision | 기록 내용과 부모 참조의 강한 해시. 같은 부모에서 다른 변경은 분기 |
| artifact_id/build_id | 기존 날짜+slug 산출물 ID. 논리 설계 ID를 대신하지 않음 |
| ui_document_id/ui_revision | UI 문서와 적용 순서. undo도 새 현재 리비전을 만들고 옛 결과를 자동 부활시키지 않음 |
| xml_sha256 | 보존한 XML UTF-8 바이트의 SHA256. 줄바꿈·미지 필드·비활성 세트도 식별 |
| spec_sha256 | 해당 계산에 전달한 정규화 BuildSpec 입력의 SHA256. 원본 XML 해시와 다름 |
| selection | 계산에 사용한 장비/스킬/config/트리 세트와 주력/통계 모드의 명시적 선택 |
| measurement_ref | 실제 저장 결과·입력·도구/버전/원자료를 결박한 근거 참조 |

계산 입력과 표현 바이트의 동일성은 다르다. XML Notes만 바뀌어도 XML 바이트 해시는
달라질 수 있다. 그렇다고 이전 계산이 새 입력에서 실행됐다고 표시하지 않는다.
동일한 계산 입력을 재사용하는 경우에는 원래 측정과 재사용 사유·새 매핑을 함께 보존한다.

기존 derivation_context의 축별 설명/차이는 재사용한다. 잘린 SHA1 문맥 서명과 자기 축을
제외한 최적화 문맥을 전체 측정 입력의 SHA256으로 승격하지 않는다.
기존 tool_results의 payload/inputs/result/source 해시와 실제 payload를 검증 경로로 재사용한다.
이는 로컬 무결성/출처 검증이며 외부 공격자에 대한 서명 인증이라고 부르지 않는다.

## 3. 최소 설계 기록

초안은 PoB나 모든 앵커 없이 만들 수 있다. 기록 형식은 다음 독립 정보를 담는다.
형식 계약은 기존 artifacts 모듈의 `src/pok/artifacts/design_record.schema.json`에
`pok.design-record.v1`로 구체화했다. KB 엔티티 스키마가 아니므로 knowledge/schema에
섞지 않는다. 새 모듈/의존 방향/저장 위치를 추가하지 않았으며 BuildSpec에도 섞지 않는다.
MCP 노출·저장·행동 검증은 아직 구현 전이다.

| 정보 | 계약 |
| --- | --- |
| schema/version | 기록 해석 버전, 지원하지 않는 버전은 원본 보존 후 편집/최종 인증 중단 |
| 목표/고정 조건 | 사용자 목적, 예산/레벨/준비 장비/취향. 의미 변경은 사용자 결정 대상으로 노출 |
| 결정 | 안정적 ID, 역할, 공격/방어/자원/유틸 영역, 조건과 그 조건이 필요한 채택안/전략 범위 |
| 역할 | 사용자 고정 / 메커니즘 필수 조건 / 잠정 구현 / 성능 후보 |
| 현재 공급자 | 실제 아이템/노드/젬/행동 등. 필수 조건과 분리, 복수 공급·복수 조건 허용 |
| 채택 상태 | 후보·채택·기각·보류. 근거 신뢰도/검증 상태와 별개 |
| 의존·대체 | 다른 결정/공급자 참조, 대안과 기각 이유, 변경 때 재검토할 범위 |
| 비용 | 슬롯·포인트·자원·조작/준비/유지 비용. 모르는 값을0으로 채우지 않음 |
| 주장·근거 | 계산/게임 문구/사용자 관측/가설을 구분하고 각 참조의 범위·한계 보존 |
| 열린 질문 | 주장, 무엇을 관찰하면 판정되는가, AI 조사/사용자 취향/인게임 관측의 책임 |
| 실물 연결 | 선택한 XML/스펙·선택 세트·해시·소켓 획득 등 sidecar와 해당 리비전 |
| 원문/확장 | 기존 Markdown 원본 바이트/해시, 미분류 정보, 미지 확장 원문 보존 |

‘마나 지속 가능’과 ‘재생만으로 지속’은 같은 필요조건이 아니다. 후자를 선택할 수 있지만
선택한 전략의 범위와 교체 가능성을 적는다. 엔진은 문구의 논리적 필요성을 스키마만으로
인증하지 않는다. 의미 판단은 AI/사용자 책임이다.

중복 ID·모순된 입력 타입·해시 불일치는 명확히 진단한다. 빈 초안/미완성 참조는 탐색을
허용하되 누락을 신고한다. 의존 그래프의 순환은 공동 재검토 묶음일 수 있으므로
모든 순환을 무조건 불법으로 만들지 않는다. 변경 전파는 방문 집합을 써 종료해야 한다.
게임 상태의 순환 회로와 문서의 의존 참조를 같은 그래프로 오인하지 않는다.

### 3.1 v1 필드와 검사 범위

최상위는 format/design_id/revision/parents/goal/decisions/evidence/questions/material/
legacy_sources이며 mechanism_summary와 extensions를 추가로 쓸 수 있다.
role은 user_fixed/mechanism_required/provisional/power_candidate,
adoption은 candidate/adopted/rejected/deferred, belief/confidence는 호출자의 판단이다.
adopted와 hypothesis가 공존할 수 있다. 이를 엔진 검증 성공으로 승격하지 않는다.

revision은 자기 revision 필드만 뺀 JSON 전체를 키 정렬·공백 없는 구분자·UTF-8·비ASCII
이스케이프 없음·비유한 수 거절로 직렬화한 SHA256에 `sha256:`을 붙인다. 부모·확장·
실물/근거 참조도 범위에 든다. 원본 XML 바이트 해시나 기존 tool_results의 입력 해시와
이 알고리즘을 같은 것으로 부르지 않는다. 서로 다른 해시 계약은 버전과 범위를 명시한다.

합성 계약 예제9개는 `tests/unit/design_record_contract_fixtures.json`에 있다.
형식/리비전 벡터, 빈 초안, 신뢰도와 채택의 독립, 위조 verified 필드·측정 overrides 거절,
식별자 끝 개행·경로 이탈 거절, 기존 한글 artifact slug, 원문 바이트 해시와 근거 용도를40개 단위
검사로 확인했다. Ruff도 통과했다. 이는 전체 단위/통합 검사나 실제 근거 검증의 증거가 아니다.
없는 측정의 올바른 모양이 스키마에 통과하는 예도 의도적으로 포함한다. 실제 결과 조회,
참조 해소·사용자 결정·리비전 충돌·변경 영향·원자 저장/복구는 R3 행동 검사에서 확인해야 한다.

### 3.2 근거의 용도와 전달 표현

evidence.scope.usage는 current/comparison/historical/general로 구분한다. 측정은
general이 될 수 없고 원래 material_revision을 반드시 가진다. source.spec_sha256은
그 실제 입력을 가리킨다. 대안 비교가 현재 구성과 다르다는 이유로 저장된 측정 자체를
위조/무효로 처리하지 않는다. 반대로 comparison을 현재 빌드의 측정으로 사용하지 않는다.
실제 payload 검증과 현재 주장에 대한 적용 범위를 별도 반환하고, 이 관계 판정은 R3에서 구현한다.

봉인된 기록의 전송/저장은 record_json 문자열 또는 불변 checkpoint 참조를 사용한다.
UI가 JSON.parse한 객체는 표시용 투영이며 JSON.stringify해서 정본을 대체하지 않는다.
새 기록/리비전 생성은 코어가 수행하고 수정 요청은 봉인된 원본/참조와 명시적 변경을 제공한다.
초기 생성 입력과 달리 기존 리비전을 가진 객체를 임의 재직렬화한 값을 자동 정규화해
원래 기록이라고 인증하지 않는다. 미지원/손상 입력은 원문을 보존하고 편집 실패를 알린다.

합성 Python/Node(v24.13.0) 검사에서 원문 JSON 문자열의 저장 왕복과 SHA256 일치는
성공했다. 같은 값을 JavaScript 객체로 파싱하면 큰 정수9007199254740993이
9007199254740992로 바뀌며 재직렬화 바이트도 달라졌다. 원문과 결과는
`artifacts/reviews/redesign-r2-wire-contract/`에 있다. 이것은 실제 UI 구현/통합 검증이
아니며 R6에서 문서 저장·제안 적용·undo까지 같은 불변식을 검사해야 한다.

## 4. 갱신과 체크포인트

1. 호출자는 현재 기록과 expected design revision을 제공한다. 불일치하면 충돌을 반환하며
   오래된 변경을 새 기록에 조용히 재적용하지 않는다.
2. 변경은 명시적 patch/전체 후보를 만든다. 엔진은 공급자 선택이나 최적화 탐색을 자동 추가하지 않는다.
3. 이전 기록에서 사용자 고정이었던 내용의 변경/역할 완화는 명시적 사용자 결정 참조가 필요하다.
   PoK가 사용자 신원을 인증하지는 못하므로 호출자의 확인 주장과 UI/대화의 실제 승인을 구분한다.
4. 채택 공급자·실물·조건이 바뀌면 명시된 의존과 근거 범위를 재검토 대상으로 표시한다.
   ID만 맞는다는 이유로 근거를 새 리비전에서 검증됐다고 바꾸지 않는다.
5. 새 체크포인트는 불변 묶음으로 보존한다. 부분 쓰기나 다른 내용의 기존 ID 덮어쓰기는
   게시 성공이 아니다. 같은 내용의 재요청은 멱등성을 검증한다.
6. 현재 참조는 호출자가 유지한다. 두 부모를 임의 병합하거나 가장 늦은 파일을 현재로 고르지 않는다.

기존 artifacts/builds/<id>/ 안에서 design 기록·생성 Markdown·원본/실물·manifest를 보존하는
방향을 우선 검토한다. PoB 전 기록은 kind를 구분하고 가짜 XML/빈 공유코드를 만들지 않는다.
기존 record_build의 mkdir(exist_ok=True)/직접 쓰기만으로 불변·원자성을 보장했다고 하지 않는다.
게시 성공 전 파일 해시와 완성 manifest를 확인하는 구현/실패 fixture가 필요하다.

## 5. 근거와 판정

| 층 | 자동 검사/반환 | 넘지 않는 결론 |
| --- | --- | --- |
| 입력/왕복 | 실제 입력·XML·선택 세트·스키마·손실/보존 범위 | 계산 가능 → 인게임 가능 |
| 성립 조건 | 알려진 불법, 획득 미입증, 조건부/충돌, 미지원 분리 | 미수록 → 획득 불가, UNKNOWN → 합법 |
| 측정 | 실제 입력/통계·저장 결과/소스 해시, 미출력·미모델링 | 한 모드 DPS → 전체 회전 DPS |
| 탐색 | 실제 범위·고정 기반·예산·종료/실패·제외·기각/미지원 | 호출 도장 → 충분한 탐색/전역 최적 |
| 선택 | AI의 목적 적합성·이득/대가·남은 질문 | 정성 판단 → 엔진 품질 인증 |

계산 근거는 저장된 payload의 실제 입력·결과·도구/버전에 맞는지 검사한다. 호출자가 쓴
숫자나 서명 문자열만으로 재계산 없이 새 측정을 위조할 수 없어야 한다. 자료 문구를
조회한 사실은 해당 메커니즘이 인게임에서 검증됐다는 근거가 아니다. 사용자 관측도
관측 주체·조건·범위를 보존하며 단순 AI 주장과 구분한다.

근거의 원래 측정 입력 일치는 엄격하게 확인한다. 부분 근거 재사용은 명시된 구성 요소와
범위가 검증되는 경우만 허용하고, 재사용 이유·기존 참조를 남긴다. 입증하지 못한 부분은
‘새 입력에서 미측정/재검토’다. 사소한 변경마다 전부 확정 무효로 만드는 것과 구분한다.

현재 ready/purpose 필드는 즉시 삭제하지 않는다. v1의 기존 의미와 v2의 위 다섯 층을
명시적으로 매핑하고, 새 경로는 지원 capability를 확인해 사용한다. 오래된 optimizer
도장만 있는 거짓 완료와 실제 수동/다른 도구 근거가 있는 경로를 대조한다.
기본 계산·탐색은 설계 기록/추천 절차 없이 가능해야 한다. 최종 추천의 근거 부족과
계산 실패는 다른 결과이며, 탐색 산출물을 최종 인증으로 조용히 승격하지 않는다.

## 6. XML·획득 근거와 옛 문서

원본 XML을 실물 표현의 정본으로 보존한다. 계산용 복원 스펙을 전체 문서의 무손실
대체물로 쓰지 않는다. 비활성 세트·미지 태그/속성·아이템 문구·리터럴 공백은 명시적
변경 대상 밖에서 보존한다. 지원하지 않는 편집은 신고하며 첫 세트로 조용히 폴백하지 않는다.

계산은 선택한 장비/스킬/config/트리·무기 세트·주력·통계 모드를 식별한다. 모호하면
가능한 선택을 반환하고 입력 결정을 요구한다. 전체 XML 보존과 특정 계산 투영의 손실은
별도다. item.socket_sources 등 획득 sidecar는 동일한 구성/아이템에 결박해야 하며
홈 수만 보고 exceptional을 발명하지 않는다. 근거가 없으면 미입증을 신고한다(#206).

기존 parse_design과 Markdown 원본은 보존한다. confirmed를 사용자 고정으로 자동 변환하지
않고 미지 문단/표/주석도 버리지 않는다. 추출/분류가 불확실하면 원문과 미분류 기록을 남긴다.
design.md는 새 기록의 안정적 파생 표현으로 만들되 기존 원문 자체를 덮어쓰지 않는다.
같은 기록/렌더 버전은 같은 UTF-8/LF 바이트를 내야 하고, 변하는 시간값은 재현성을 깨지 않게 분리한다.

## 7. UI와 호환

UI BuildDocument의 XML/originalXml/revision/undo를 유지하며 설계와 sidecar를 함께 연결한다.
제안은 base UI revision·design revision·material hash에 결박한다. 적용과 undo는 설계와
XML을 한 동작으로 처리하고 계산 결과는 원래 입력의 결과로만 표시한다. 늦은 응답이
현재 문서와 맞지 않으면 보존은 하되 최신 수치로 붙이지 않는다.

구버전 UI/엔진에는 capability/schema 지원 여부를 먼저 표시한다. 기존 XML만 있는 문서는
계속 열고 편집하며 설계 부재를 임의 확정 기록으로 채우지 않는다. 지원하지 않는 새
기록은 원본 보존/읽기 제한으로 처리하고 조용히 지우지 않는다. 개발 checkout과 번들
런타임의 실제 코드/PoB/KB/스키마 식별을 구분한다.

## 8. 실행 수명과 결과 전달

요청은 소유자·실제 입력·절대 기한을 식별한다. 진행 메시지가 무한히 기한을 늘리지 않는다.
긴 탐색의 중단은 완료/부분/기한 초과/취소 요청/취소 확인/실패를 구분한다. 네이티브
작업이 살아 있는데 cancelled라고 보고하지 않는다. 확인되지 않은 하위 실행은 신고한다.
현재 spec/원본/다른 요청을 손상시키지 않고 소유한 작업만 정리한다.

채팅 취소와 MCP/PoB 작업 취소를 같은 것으로 전제하지 않는다. UI/CLI 연결이 끊긴 경우와
계산기 실패를 구분하고, 재연결/재개 때 실제 종료 상태를 확인한다. 부분 결과와 원본을
보존하며 자동으로 최선의 중간안을 최종 추천으로 고르지 않는다.

작은 요약은 실패·한계·입력/결과 ID를 포함하고 상세는 기존 해시/페이지 참조로 회수한다.
페이지·원문·정규화된 표시·입력 해시를 혼동하지 않는다. 도구별 탐색 범위와 기본 예산은
R3/R4 구현 전에 기준 비용과 함께 고정하며 클라이언트 상한 안에서 종료해야 한다.

## 9. 계약 fixture와 구현 순서

| 예 | 기대 결과 | 구현/소비자 |
| --- | --- | --- |
| PoB 없는 초기 목표 | 미완성 기록 생성/보존·렌더 가능, 가짜 계산 없음 | artifacts/engine/MCP |
| 필수 조건의 공급자 교체 | 조건 ID 유지, 영향받은 결정/근거 재검토 | engine·AI |
| 고정 장비 변경/역할 완화 | 사용자 결정 필요 표시, 조용한 적용 없음 | engine·UI/대화 |
| 형식은 맞지만 의미가 잘못된 필요조건 | 형식 검증과 의미 판단의 범위를 구분 | AI·사용자 |
| 동일 부모의 두 변경 | 두 분기 보존, 임의 최신 선택/자동 병합 없음 | checkpoint·UI |
| 한 필드만 달라진 실제 계산 입력 | 원래 측정 참조는 보존, 새 입력 측정으로 위장 불가 | engine/tool_results |
| 수동 변경+실제 비교 근거 | optimizer 호출 도장 없이 유효 범위 인정 | 추천 v2 |
| 도장은 있으나 입력/결과 불일치 | 거짓 완료 차단/정확한 누락 신고 | 추천 v2 |
| XML unknown/비활성 세트 | 변경 밖 바이트/의미 보존, 선택한 투영만 계산 | pob·UI |
| exceptional 근거 있는 spec→PoB→복원 | sidecar 연결 또는 근거 미입증, 무조건 불법/합법 금지 | #206·UI |
| 과거 design.md confirmed/미지 문단 | 원본 보존, 역할 자동 확정 없음 | legacy import/render |
| 부분 저장/기존 ID 충돌 | 완성 게시 아님, 기존 산출물 불변 | artifacts |
| 늦은 계산/제안·undo | 설계와 XML의 원자성, stale 결과가 현재로 붙지 않음 | UI |
| 기한/취소 후 재계산 | 소유 작업 종료 상태 확인·원본 불변·새 요청 격리 | MCP/PoB |
| #203~#205 양성·음성 대조 | 내장/외부 트리거, 제외/미수록, 행동/공급 필요 조건 구분 | 진단 |

작은 구현 묶음은 (1) 기록/리비전/렌더·체크포인트, (2) 실제 입력 근거·변경 영향,
(3) XML/선택·획득 손실과 진단, (4) 실행 수명/비용, (5) 대체 근거/스킬·탐색 계약,
(6) UI 소비/원자 적용 순으로 의존을 정리한다. R3/R4/R6의 실제 범위는 ROADMAP과 함께 관리한다.
R3 튜닝 전에 R5의 새 보류 과제 두 개·평가 기준·기준판 재실행 경로를 고정한다.
이 fixture 목록과 문서만으로 구현/검증 완료를 보고하지 않는다.

기준판 보존: `artifacts/reviews/redesign-r2-baseline/baseline-source.zip`에 동결 소스/
KB/입력921파일을 보존하고 압축 해제 바이트의 해시를 검사했다. ZIP SHA256은
ad1f6fb3ba8c83ace50c57b917e117b1231b2e4f3870affc2ea60676b7dea4df다.
원자료/PoB25,087파일과 실행 환경은 manifest의 고정 참조이며 ZIP 단독 설치본이 아니다.
기준판은 `artifacts/reviews/redesign-r5-baseline-checkout`의 별도 worktree
`codex/pok-r1-replay`에 복원했다.921파일의 바이트를 대조하고 새 stdio MCP가 실제 그
소스에서 부팅하는 것을 확인했다. 알려진 R1 입력의 DPS45,052.68404/생명력2394/ES5085를
재현했다. 이 사전 검증은 새 보류 과제나 모델 생성 실행이 아니다.
원자료/PoB는 명시한 junction으로 같은 고정 입력을 참조한다. OS 읽기 전용 보장으로
오인하지 않으며 R5 실행기는 허용된 외부 루트 매핑과 전체 해시를 따로 검사해야 한다.

R5 새 과제는 [고정 프로토콜](POK_REDESIGN_HELDOUT_PROTOCOL.md)에 따라 R3 튜닝 전에
동결했다. H1은 새 Stormweaver Spark 초안→준비 반지의 사용자 고정 변경/재투자,
H2는 새 Witchhunter 석궁 상태 회로와 생명력/방어도/회피다. 전직은 Passive의 전직
필터로, 일반판 Dream Fragments는 정확한 Item ID와 실제 기준판 적법 검사로 확인했다.
첫 Ascendancy 타입 조회0건은 다른 타입 진단을 따라 교정했고 실패 원본을 보존했다.
이는 이름/입력 확인이며 빌드 해답·성능을 생성하거나 평가한 것이 아니다.

`artifacts/reviews/redesign-r5-heldout-inputs/frozen-inputs.json`의 manifest SHA256은
0149922a039a5584a618a3f1d8855f758540cdf61d601e9c546a9af241b3b6f0이며9파일을 재검사했다.
각 과제·제품판2회로8시험이고 H1의 후속 메시지/반지는 첫 단계 종료 전에 노출하지 않는다.
native 문맥 재개/같은 시험의 근거 접근 장난감 사전 검증, 개선판 동결, 실제 노출 정책·
격리/절대 기한/종료 확인은 아직 남아 있어 R5 본 실행은 시작하지 않았다.

## 10. 공개 API와 구버전 대응

새 참조는 `pok.design-ref.v1`의 artifact_id/revision/sha256/manifest_sha256이다.
sha256은 봉인 JSON 바이트, manifest_sha256은 파일 목록과 작업 출처 메타데이터까지 결박한다.
기록 JSON 해시만으로 승인 주장/부모 변경 메타데이터 무결성을 대신하지 않는다. 파일명은 코어가 정한
design-record.json이며 임의 절대 경로를 받지 않는다. ID는 기존 산출물 공간의 ID이고
revision은 논리 기록, sha256은 실제 보존 JSON 바이트를 식별한다.
기존 리비전이 있는 입력은 record_json 또는 record_ref 중 하나만 제공한다.

| 새 API | 입력/의미 | 기본 반환 |
| --- | --- | --- |
| create_design_record | 목표, 선택적 논리 ID. PoB/전체 앵커 불필요 | 봉인 기록·불변 체크포인트 참조·자동 검사/문서 참조 |
| update_design_record | 봉인 원문/참조, expected_revision, 명시적 changes, 결정별 caller-reported user_decisions | 변경/재검토 ID·진단·새 부모/리비전/체크포인트 |
| read_design_record | 명시적 record_ref | 원문 JSON·원문/실물/문서 참조, 현재 검사 범위 |
| inspect_design_record | 봉인 원문/참조 | 형식/참조·실제 근거·현재 적용 범위·미해결/재검토를 구분한 진단 |
| list_design_records | 선택적 design_id/제한 | 명시적 체크포인트/분기 목록. 최신 시간을 현재로 선택하지 않음 |
| import_design_document | 기존 Markdown 원문/검증된 blob 참조 | 원문 보존과 미분류 추출, 임의 사용자 고정 변환 없음 |

갱신 op는 upsert_decision/evidence/question, remove_decision/evidence/question,
set_goal/material/mechanism_summary, append_legacy_source, merge_extensions다.
upsert는 지정하지 않은 필드/중첩 객체를 보존하고 배열은 명시적으로 교체한다.
새 결정의 빠진 기계 기본값은 candidate/unknown/low와 빈 목록이며 역할·영역·조건/범위를
엔진이 대신 선택하지 않는다. 해법 탐색·게임 의미 판단·네이티브 계산을 자동 추가하지 않는다.
무변경은 새 부모/리비전을 만들지 않는다. 같은 부모의 서로 다른 갱신은 분기다.

create/update는 저장 성공 전에 검사와 안정적 문서 생성을 수행한다. 별도 inspect/render
호출을 잊었다는 이유로 변경 영향 신고가 사라지지 않게 한다. 실제 근거 검증 미구현/미실행은
not_checked로 반환한다. 구조적으로 정상이라는 이유로 verified/추천 준비를 만들지 않는다.
형식·참조 검사만 완료된 중간 구현은 완전 capability를 광고하지 않는다.

server_info의 capabilities는 design_records.protocol/schema/transport,
assessment_versions, material_binding, request_lifetime의 지원 범위를 명시한다.
키 부재는 구버전/미지원이며 버전 추정으로 호출하지 않는다. 구현·회귀·실제 MCP 왕복을
확인한 기능만 광고하고 실제 코드/KB/PoB 식별과 별개로 보존한다.

| 현행 계약 | 이행/호환 의미 |
| --- | --- |
| compute_pob(build_spec, stats) | 기존 입력/기본 계산 유지. 추천/설계 기록을 필수로 만들지 않음. 추가 design_ref를 사용할 때만 결합 진단을 함께 반환 |
| assemble_pob(..., purpose="exploration") | 현행 기본값 유지. 새 판정은 assessment_version=2로 명시 선택하고 미지원 엔진에서 보내지 않음 |
| v1 recommendation_ready/optimization_readiness | 기존 의미/경로를 보존하고 legacy임을 명시. 새 판정과 동일하다고 부르지 않음 |
| v2 추천 판정 | 입력/성립/측정/탐색/AI 선택을 분리. 실제 수동/다른 도구 근거도 허용하고 호출 도장만으로 완료하지 않음 |
| v2 명시적 장비 | 이미 제공한 문구를 숨은 자동 희귀 탐색으로 바꾸지 않음. 불완전/선언형·미계산·불법/미입증은 구분해 신고 |
| 기존 list_builds | 새 design-only 체크포인트로 구형 소비자를 채우지 않음. 새 목록은 list_design_records에서 구분 |
| 기존 parse_design_doc | 관대한 추출 계약 유지. 새 import의 원문/미지 정보 보존과 동일시하지 않음 |

기본 생성 경로의 v2 전환은 스킬/현대 소비자가 명시적으로 선택하는 방식으로 한다.
그전에 v1 API 필드를 삭제하거나 기본 purpose를 바꾸지 않는다. 추천 판정은 실제 범위에
대한 사실 확인이며 좋은 빌드/전역 최적해의 인증이 아니다. AI 선택 이유는 별도 주장이다.

## 11. UI 파일/저장 이행의 구체 조건

현행 JSON 가져오기는 XML로 새 문서를 만들며 다른 필드를 버린다. 따라서 설계가 포함된
새 내보내기를 schemaVersion=1로 위장하지 않는다. 새 v2 편집 문서는 v1 앱이 명확히
거절하고, 새 앱은 v1 XML/PoB/편집 문서를 계속 지원한다. record_json은 원문 문자열이다.
설계 ID/리비전은 새 UI 문서 ID/숫자 리비전으로 덮어쓰지 않는다.

현행 StateStore는 workspace.v1.json의 미지원 형식을 오류로 보고 옛 백업을 복구할 수
있으므로 같은 파일에 v2를 쓰지 않는다. 같은 데이터 폴더의 workspace.v2.json으로
명시적 이행하며 v1 원본/백업을 유지한다. v2가 이미 있으면 오래된 v1을 자동 현재로
승격하지 않는다. 미지원 미래 버전과 손상 복구도 구분하고 원문을 보존한다.
이는 기존 storage 모듈/데이터 폴더 안의 버전 이행이며 새 독립 저장 서비스가 아니다.

작업 공간은 봉인 기록을 리비전별로 보존하고 현재 문서/PoB 없는 채팅은 명시적 참조를
갖는다. 같은 기록의 파싱 객체를 별도 가변 정본으로 저장하지 않는다. 빌드와 연결된
채팅은 문서의 현재 참조를 사용하고 독립 현재 참조를 따로 편집하지 않는다.
초기 설계를 저장하려고 가짜 PoB를 만들지 않는다. 생성 제안·적용·undo는 설계 참조와
XML을 함께 처리한다. 오프라인 직접 XML 편집은 허용하되 기존 설계 결합을 stale로 표시한다.
R6은 파일 버전/미지 기록·숫자 원문·늦은 결과·원자적 적용을 실제 앱에서 검증한다.

## 12. 비용 목표와 R3 현재 범위

공개 계산/최적화/기본 생성 경로를 변경하기 전 다음 초기 목표를 고정한다.
순수 기록 커널 프로토타입의 정확성 검사는 이미 수행했으며 이 목표가 그 이전의 성능
측정 결과라는 주장은 하지 않는다. 처음 성능 측정/튜닝과 공개 경로 연결은 이후다.

- 같은 호스트에서100결정/500근거·1MiB 이하 기록의 파싱/봉인·구조 변경 전파·렌더를
  7회 측정한다. 따뜻한 실행 중앙값1초 이내를 초기 목표로 두고 콜드/전체 시간을 별도로
  공개한다. 실제 근거 파일/KB/PoB 읽기·계산은 별도 비용이며 숨겨 합산하지 않는다.
- 기본 변경 요약은 UTF-8 논리 JSON8KiB 이내를 목표로 하며 큰 상세 진단은 총건수/참조와
  함께 보존한다. 작은 응답을 위해 누락/미해결을 성공으로 바꾸지 않는다.
- 명시적 변경+계산에는 의무 optimizer/전체 조립을 끼워 넣지 않는다. 네이티브 계산
  정확성과 원본/근거 보존이 우선이며 루아 계산 자체의 일정 배수 가속을 미리 약속하지 않는다.
- 네이티브 단일 계산 기본 절대 상한180초, 선택 탐색 기본300초/최대1200초를 목표 계약으로
  둔다. 호출자의 더 짧은 남은 기한을 우선하며 진행으로 연장하지 않는다. 완료 못 한 범위는
  부분/미측정으로 반환한다. 실제 소유 작업 종료/복구를 확인하기 전 취소 성공으로 표시하지 않는다.

현재 R3 순수 커널은 `artifacts/design_record.py`와 `engine/design_records.py`에 있다.
봉인 JSON/중복·변조 거절, 부모/분기·충돌, 사용자 고정 변경, 부분 갱신 보존, 의존 전파·
순환 신고·질문 재개방, 안정적 문서 표현을83개 계약/행동 단위 검사로 확인했다.
Ruff·엄격 mypy와 의존 방향 검사(158파일/434의존, 위반0)도 통과했다.
이83건만으로 실제 근거 payload/실물/KB 검증, 디스크 I/O, MCP·UI·실행 수명 전체를
구현했다고 하지 않는다. 후속 디스크 검증은 아래와 구분한다. 실제 근거/게임 성립은 not_checked다.

condition.scope.decision_ids는 선택한 조건의 문맥 의존이며 depends_on과 함께 변경을
전파한다. evidence.scope.decision_ids는 근거의 대상 결정이다. 결정의 evidence_ids와
양쪽에 같은 연결을 수동 복사해야만 전파되는 구조로 만들지 않는다. 실제 근거의 유효성과
현재 구성 적용 여부는 이 구조적 전파와 별도 검사다.

## 13. 불변 저장·연결 검증의 현재 구현

기존 artifacts/store.py에 불변 byte bundle 게시/읽기를 추가하고 engine/design_checkpoints.py가
봉인 원문·안정적 문서·구조 검사·작업 출처를 조합한다. 기존 artifacts/builds 안에 저장하며
현재 헤드/새 DB는 만들지 않는다. 파일 해시와 바이트 수·전체 manifest 해시를 읽을 때 검증한다.
문서와 검사 결과가 같은 기록 리비전에 대응하는지도 별도로 확인한다.

새 쓰기와 구형 record_build/record_anchor는 같은 ID의 배타적 claim을 사용한다.
완성된 비어 있지 않은 staging 디렉터리를 한 번 게시하며 기존 ID의 다른 내용·부분 폴더를
덮어쓰거나 조용히 수선하지 않는다. claim 파일만 보고 작업이 살아 있다고 판단하지 않는다.
알 수 없는 claim은 보존하고 새 ID 채번은 이를 피한다. OS 전원 장애 전체의 영속성이나
관리자가 임의 변경한 호스트에 대한 인증을 보장한다는 뜻은 아니다.

read는 역사적 stored_assessment와 현재의 실제 근거 검증을 구분한다. 현재 저장 보고는
structural_only/not_checked다. update는 부모를 보존하며 무변경이면 같은 참조를 반환한다.
legacy import는 BOM/CRLF·미지 문단/주석의 원문 바이트를 보존하고 confirmed를 user_fixed로
자동 변환하지 않는다. 미지원 인코딩도 opaque로 보존하며 대체 문자로 원문을 고치지 않는다.
기존 목록은 design-only 체크포인트와 미게시 staging을 빌드로 노출하지 않는다.

관련148개 회귀 중147통과/v6 실물 문서 부재1skip, 오류/실패0을
`artifacts/reviews/redesign-r3-checkpoint-junit.xml`에 보존했다. Ruff와 엄격 mypy도 통과했다.
별도 실제 Windows junction 검사에서 읽기·새 쓰기·구형 쓰기 모두 거절됐고 밖의 원본은
불변이었다(`artifacts/reviews/redesign-r3-junction-probe/result.json`). 이는 해당 junction 경로의 검증이며 모든 플랫폼의
별칭 유형을 전부 검증했다는 뜻은 아니다. 실제 근거·실물 연결, MCP 노출/작은 응답,
#203~#206 전체 수정, 네이티브 취소/기한·복구, UI/배포 검증은 계속 미완료다.

## 14. 실제 참조/입력 범위 검사의 현재 구현

engine/design_evidence.py는 기존 tool_results의 payload/manifest 검증을 재사용한다.
compute_pob의 실제 build_spec과 evaluate_delta의 base/이름별 variant를 결과 JSON pointer에
대응시킨다. 요청/메타데이터 경로나 여러 variant 전체를 단일 측정으로 바꾸어 부르지 않는다.
선택한 입력의 정규화 SHA256, 현재 스펙과의 일치, 원래 material revision을 각각 확인한다.
가져온 저장 통계/다른 도구/오류 객체를 새로운 PoB 측정으로 인정하지 않는다.

measurement의 current와 comparison/historical은 다르게 처리한다. 유효한 대안의 관측을
현재와 다르다는 이유로 삭제하지 않고, 그 관측을 현재 입력 수치로 재명명하는 것도 막는다.
같은 스펙이라도 다른 실물 맵핑은 원래 근거를 유지한 채 mapping review로 신고한다.
source compatibility는 호스트가 준 명시적 필드만 대조하고 부재/불일치를 별도 반환한다.
입력 해시 일치를 같은 엔진/버전의 증거로 삼지 않는다. 실제 값 미출력/null·실패·잘린 노드/
장비·소켓/요구치 등 관측 한계도 정합성 검증과 구분한다.

catalog는 실제 get_entry/get_insight 코어 조회의 ID·전체 기록 해시·선택 필드·선언 patch
범위를 대조한다. 조회 장애/부재는 확인된 게임 데이터 갭/불법으로 바꾸지 않는다.
해당 문구의 무결성이 확인돼도 조합 메커니즘이 인게임 검증됐다고 자동 판정하지 않는다.
과거 catalog 원문 snapshot 발급/휴대 경로와 기타 계산 도구의 실제 입력 근거 확장은 남아 있다.

실물 blob은 원문 바이트 SHA256과 계산 스펙의 논리 입력 해시를 분리한다. 획득 sidecar가
없다는 이유로 별도로 검증된 숫자 투영까지 지우지 않는다. provider binding은 현재 스펙의
실제 JSON pointer 값에 대조하고, 동일 값의 다른 material 맵핑과 변경/미지원 표현을 구분한다.
XML↔스펙의 의미적 동등성, XML binding, 게임 성립 검사는 아직 not_checked/미지원이다.
이 코드가 모든 도구/모델/과거 근거 형식을 이미 검증한다고 하지 않는다.

MCP 등록기의 literal_arguments는 설계 변경/근거 메타데이터 안의 참조를 입력 매크로로
펼치지 않도록 한다. 실제 build_spec 참조 확장은 기존대로 유지하고 실제 저장 입력도
각 의미에 맞게 기록한다. 새 설계 도구 등록 때 이 정책을 명시해야 한다. 모르는 인수 이름은
등록 오류로 거절하며 기존 도구의 기본 입력/출력 계약은 유지한다.

실제 FastMCP 전송 경계와 기록/근거/저장 관련 회귀200건 중199통과/v6 실물 문서 부재1skip,
오류/실패0을 `artifacts/reviews/redesign-r3-evidence-wire-junit-v2.xml`에 보존했다.
Ruff·엄격 mypy·의존 검사(160파일/444의존, 위반0)도 통과했다. 저장소 합성 fixture는
검사기 동작의 증거이며 실제 PoB 실행/게임 효과를 검증한 빌드 표본이 아니다.
새 공개 API, 작은 계산의 영수증 자동 발급, 체크포인트 자동 실제 근거 검사, 실제 source
fingerprint/실물 선택/수명·UI 연결은 아직 진행 대상이다. capability는 이를 완료하기 전
완전 지원으로 광고하지 않는다.

### 14.1 공개 서비스와 크기 독립 측정 참조

생성·조회·갱신 MCP는 불변 checkpoint를 읽고 현재 실제 근거를 자동 검사한다.
과거 저장 assessment는 구조 검사로 유지하며 current_assessment와 구분한다.
생성/조회/갱신 실제 FastMCP 및 충돌/no-op 보존 서비스 검사2건이 통과했다.
inspect/list/import 공개 API와 실제 host source fingerprint 연결은 아직 남아 있다.

MCP compute_pob/evaluate_delta는 작은 결과에도 measurement_ref를 자동 발급한다.
저장 payload는 참조를 붙이기 전 논리 결과와 실제 해석된 입력을 보존한다.
작은 결과는 기존 값에 참조를 추가하고, 큰 결과는 bounded notice에 참조를 추가한다.
직접 Python 호출 반환은 그대로다. 실패 반환의 참조도 성공 증명으로 취급하지 않으며
근거 검사기가 실제 stats/입력/선택 경로를 별도로 확인한다. evaluate_delta는 근거로
사용할 때 base 또는 특정 variant의 하위 경로를 선택해야 한다.
현재 source의 loaded_commit은 dirty 코드/KB/PoB의 완전한 버전 결박이 아니다.
이 한계는 참조가 발급됐다는 이유로 해소됐다고 보고하지 않는다.
회귀 증거: artifacts/reviews/redesign-r3-receipts-v1.xml.

### 14.2 계산 전후 출처 관측

측정 MCP는 실제 코드163파일·스크립트13파일·KB692파일의 콘텐츠 해시와
manifest의 PoB 고정값을 계산 전후에 관측해 저장 source.source_observation에 붙인다.
파일 이름/바이트 길이로 경계를 구분해 해시하며, 같은 크기/수정시각의 내용 변경도 감지한다.
누락/읽기 실패는 unavailable, 변화는 changed, 동일 관측은 stable_observation이다.
외부 경로로 해석되는 파일은 무조건 정상 해시로 받아들이지 않는다.

이것은 메모리에 로드된 Python/KB, PoB 데몬, 캐시가 실제 사용한 실행 정체성을
증명하지 않는다. execution_identity=not_verified_disk_observation_only를 명시한다.
PoB 고정값과 실제 checkout/실행 바이너리/로드된 데이터의 일치 검증은 아직 남았다.
현 작업트리 실제 관측은 첫1.898초/다음1.742초였으며, 계산당 전후 합계 약3.64초의
추가 비용을 확인했다. 성능 최적화 시 내용 변경 감지의 의미를 약화시키지 않는다.
관련29검사는 artifacts/reviews/redesign-r3-source-observation-v1.xml에 보존했다.

### 14.3 원문 가져오기와 검사 API

inspect_design_record는 체크포인트 무결성 확인 뒤 현재 근거 검사만 반환한다.
import_design_document는 document_text의 UTF-8 바이트 또는 기존 artifact의
artifact_id/name/sha256로 검증한 원문 바이트 중 정확히 하나를 받아 불변 보존한다.
임의 파일 경로는 받지 않는다. BOM/CRLF/알 수 없는 내용도 원문 blob으로 보존하며
legacy confirmed 문구를 사용자 고정 결정으로 승격하지 않는다. 가져온 기록은
현재 근거를 자동 검사한다. 이 두 API는 등록됐으나 실제 stdio 전체 프로브는 남아 있다.
공개 목록 API도 아직 남아 있다. 서비스·체크포인트·출처 관련25검사가
artifacts/reviews/redesign-r3-import-service-v1.xml에서 통과했다.

### 14.4 목록·capability·실제 stdio 연결

list_design_records는 기존 artifacts/builds에서 불변 설계 checkpoint만 발견하고
전체 저장 바이트/렌더/리비전 연결을 검증해 참조를 반환한다. 특정 design_id로
거를 수 있으나 최신/현재 head를 임의 선택하지 않는다. 목록은 현재 근거 검사 완료를
뜻하지 않는다. 저장 손상은 diagnostics로 분리한다. offset/limit는 일치한 기록 수가
아니라 artifact 디렉터리 항목 수에 적용돼 빈 페이지여도 next_offset을 따라야 한다.
한 페이지100항목 이하이며 hidden staging/lock는 제외하고 symbolic alias는 거절한다.
서비스·저장 관련63검사에서 실패/오류/skip 없이 통과했다.

server_info.capabilities는 실제 지원한 설계 API/format/schema 조회와 계산 영수증을
광고한다. 게임 성립/XML 동등성/실행 정체성 미검증을 함께 명시한다.
get_design_record_schema는 runtime schema 원본을 반환하며 큰 경우 기존 결과
참조/페이지 경로를 사용한다. 새로운 schema 파일 위치나 저장 경계는 만들지 않는다.

새 Python stdio 프로세스에서 도구 목록과 실제 create/read/update/inspect/list/import,
capability/schema 조회, 큰 schema의 공식 페이지 복원, stale revision 거절,
분기2개/과거 원본/큰 정수9007199254740993 보존을13호출로 확인했다.
증거: artifacts/reviews/redesign-r3-public-stdio-v3/receipt.json 및 요청/응답 원본.
v1은 여섯 API8호출 통과, v2는 스키마도 작은 응답일 것이라는 프로브 가정이 틀려
중단됐다. v2를 삭제하지 않고 v3에서 공식 페이징으로 회수해 통과했다.
서버 식별·설계 서비스·출처 관측 관련18검사도 통과했다.
실제 PoB 계산/게임 효과나 R3 전체 완료를 이 프로브로 주장하지 않는다.

### 14.5 승인 제외 젬의 자동 진단 (#204)

계산 결과 투영과 PoB 스펙 복원은 gem_availability를 자동 반환한다. 이는 별도의
catalog 승인 원장 진단이며 계산 성공/아이템 적법성/복원 faithful과 혼합하지 않는다.
PoB의 native/game ID를 카탈로그 이름으로 해석한 뒤 원장 slug/표시명과 대조한다.
표시명으로 알려진 다른 native ID를 덮어쓰거나 미수록을 제외라고 추정하지 않는다.
출처는 원장 바이트 해시와 항목 JSON pointer로 결박하며 패치·승인·사유와 젬 위치,
활성 여부를 함께 기록한다. matches_kb_patch는 ingest manifest의 고정 패치를 뜻한다.
다른 패치/승인 부재/조회 장애/native 미해석은 별도 상태이며 계산을 막지 않는다.
실제 Shock Siphon은 고정0.5.4b의 승인2026-08-04 원장 항목에 연결됐다.
이후 실제 시즌의 획득 가능성이나 인게임 효과를 이 기록으로 증명하지 않는다.
관련71검사 후 계산/복원 경로 포함8검사, 승인 타입/원장 경로 보강7검사가 통과했다.
증거는 artifacts/reviews/redesign-r3-204 및 redesign-r3-204-unit-v1/v2/v3.xml이다.

### 14.6 행동 시나리오와 효과 공급의 분리 (#205)

conditionMoving과 conditionStationary는 행동/정지 시간으로 정한 측정 시나리오다.
기존 ConfigVerdict.status=neutral을 유지하되 행동 시나리오 label/reason과
AssumptionReport.behaviour_scenarios로 효과 공급과 구분한다. 조립 결과 assumptions의
behaviour_scenarios/notes에 자동으로 남긴다. 꺼진 값은 활성 시나리오로 세지 않는다.
이동 중 공격 가능성이나 항상 해당 행동을 한다는 보증은 아니다.
저주/출혈 등 실제 효과의 공급 술어, 요구만 하는 문구의 거절은 유지하며 모든 behaviour
축을 일괄 면제하지 않는다. 행동/꺼짐만 있으면 공급 문구를 불필요하게 로드하지 않는다.
기존 가정/유지 비용 포함30검사와 실제 MCP 조립 관문17검사가 통과했다.
후자는 native 계산/게시 및 비관련 KB 경계를 대체했으므로 실제 게임 성립 증명이 아니다.
증거는 artifacts/reviews/redesign-r3-205-unit-v1.xml 및 redesign-r3-205-mcp-v3.xml이다.

### 14.7 복원 범위와 명시 획득 sidecar (#206 부분 구현)

restore_pob_spec의 기존 faithful/damage_comparable 값은 그대로 유지하되
faithful_scope=pob_calculation_projection_only와 restore_fidelity를 반환한다.
계산 투영, socket_metadata, 재구성하지 않은 기타 설계 근거, 원문 보존을 분리한다.
추가 홈의 선언이 없으면 socket_acquisition의 acquisition_unproven과 구조적 진단을
자동 반환한다. 일반 홈만 있는 항목에 추가 경로를 만들어 붙이지 않는다.

original_xml은 복원한 데이터로 재생성한 XML이 아니라 공유코드에서 해독한 원문이며
비활성·미지 구간도 보존한다. source_xml_sha256, 메타데이터 적용 전의
restored_projection_revision, 적용 후 effective_spec_revision을 구분한다.
이것은 실제 PoB/게임 의미 동등성 인증이 아니다.

create_socket_sidecar(build_code, expected_projection_revision, socket_sources_by_slot)는
명시 선언만 불변 artifacts/builds 묶음에 원문 XML과 함께 저장한다. 새 DB/저장 경계를
만들지 않는다. 반환 sidecar_ref는 artifact_id/name/sha256의 byte 참조다.
restore_pob_spec의 socket_sidecar_ref 인수는 모든 바이트/원문 XML/투영/아이템 문구
결박을 확인한 후 전부 적용한다. 어떤 행이라도 틀리면 하나도 적용하지 않는다.
성공한 참조는 결과에도 반환하며 실제 드롭 증명으로 주장하지 않는다.
구형 빌드 목록은 설계 checkpoint처럼 sidecar 전용 묶음을 재개할 빌드로 취급하지 않는다.
server_info는 이 형식/도구/결박 범위와 선언 보존이라는 한계를 광고한다.

관련92검사가 통과했다. 참조 전달·구형 목록·서버 관련23검사 중22통과/v6 실물 문서 부재1skip.
원 #206의 B-03을 새 stdio26호출로 복원·기록·다시 복원해 미입증5부위와 같은 원본
선언 연결 후 소켓 검사 통과를 확인했다. 원본 PoB/원문 XML은 변경하지 않았다.
새 native 산술은 실행하지 않았다. 증거는 redesign-r3-206-fidelity-v2.xml,
redesign-r3-206-propagation-v3.xml, redesign-r3-206-stdio-v1/receipt.json이다.
자동 출고·설계 material 검사 후속은14.8을 따르며 UI 저장/undo/export 휴대·재적용은 남아 있고,
이 부분 구현을 #206 전체나 R3/R6 완료로 취급하지 않는다.

### 14.8 자동 출고와 설계 material의 획득 근거 연결

assemble은 명시 socket_sources가 있으면 최종 saved_spec을 렌더해 내보낸 아이템
문구와 대조하고 sidecar를 기존 빌드 묶음에 자동 저장한다. 대리 모델링 문구도 렌더된
실물을 기준으로 대조한다. 선언이 없으면 경로를 만들지 않으며, 불일치/해석 실패는
not_bound로 신고한다. manifest/validation/AssembledBuild/MCP에 상태·해시·참조를
보존한다. 파일은 canonical JSON 한 줄이므로 기존 Windows 텍스트 저장에서도
참조가 가리키는 실제 바이트와 해시가 같다.

알려진 sidecar를 material.metadata에 연결하면 기본 근거 검사기가 원문 XML·복원
투영·실제 스펙 리비전·현재 슬롯의 선언을 대조한다. 바이트 검증과 선언 연결 검증은
별도다. checks.socket_metadata_binding이 verified_declared_binding이어도 실제
드롭, 전체 XML/스펙·선택의 의미 동등성을 인증하지 않는다. 다른 XML/스펙이나 선언이면
재검토 진단을 붙이되 독립적으로 검증된 계산 스펙을 지우지 않는다.

자동 출고25검사 후 결박/기존 회귀77검사와 MCP 전달1검사가 통과했다.
material fixture의 필수 media_type 누락으로 실패한 v2와 보완 후 통과한 v3를 보존했다.
증거: artifacts/reviews/redesign-r3-206-export-v1.xml,
redesign-r3-206-material-v3.xml, redesign-r3-206-mcp-forward-v1.xml.
스냅샷 공개 도구는14.9를 따르며 실제 XML 선택·UI 보존/휴대/재적용과 전체 #206 완료는 아직 남아 있다.

### 14.9 구성 스냅샷 공개 도구

capture_design_material은 build_spec 및/또는 원문 XML 입력을 받는다. build_code와
xml_text는 둘 중 하나만 받는다. metadata_ref는 검증된 artifact_id/name/sha256
참조이며 media_type이 이미 있어도 허용한다. 스펙의 미지 필드와 큰 정수를 보존하고
원문 XML·metadata 바이트를 기존 artifacts/builds 불변 묶음에 복사한다.
blob 해시/media_type/전체 material 리비전은 도구가 생성하고 형태 검사를 게시 전에 한다.
반환 material을 update_design_record의 set_material 값으로 그대로 넘길 수 있다.
현재 head를 자동 갱신하거나 세트를 임의 선택하지 않는다.

검사는 입력 스냅샷과 현재 근거 연결을 다루며 빌드 성립/전체 XML·스펙/selection 의미
동등성을 인증하지 않는다. 출력 claim과 selection_verification=not_checked를 명시한다.
알려진 socket sidecar는 기존 바인딩 검사가 자동으로 수행된다. 원본 메타데이터 참조는
묶음 manifest에도 남고, 스냅샷만으로 구형 빌드 재개 목록에 새 후보를 만들지 않는다.
실제 build_spec 결과 참조는 MCP 경계에서 해석하며 metadata_ref/selection은 리터럴로 받는다.

관련59검사 통과 뒤 실제 MCP 스펙 참조/설계 연결을 포함한11검사를 재확인했다.
새 stdio 서버에서 실제 B-03의 복원·원본 근거 복사·스냅샷·설계 갱신·현재 검사까지
17호출 통과했다. native 계산/게임 효과를 검증한 것은 아니다.
증거: artifacts/reviews/redesign-r3-material-capture-v1/v2.xml,
redesign-r3-material-stdio-v1/receipt.json. 실제 XML 선택과 UI 보존/휴대/재적용은 남아 있다.

### 14.10 저장 활성 세트와 명시 선택 (#207)

pob.selection은 장비/스킬/config 세트를 숫자 ID, 트리 spec을1기반 순번으로 해석한다.
기본값/없는 활성 ID·트리 범위 초과의 대체는 notes로 남기며 모호한 ID를 정상으로 인증하지
않는다. 선택된 ItemSet의 무기 세트를 사용한다. 복원/요약이 같은 선택기를 공유하고
결과에 실제 선택을 반환한다. 요약 items는 여전히 전체 저장 아이템 목록임을 명시한다.
숫자 config는 유한 소수를 유지하며 비유한 수를 거절한다.

restore_pob_spec과 create_socket_sidecar의 selection 인수는 item_set/skill_set/
config_set/tree_spec(문자열), weapon_set(1/2)을 지원한다. 없는 명시 선택은 대체하지
않는다. 원문 XML을 수정하지 않으며 selection_resolved로 실제 선택을 반환한다.
새 sidecar는 이 벡터를 결박하고, 구형 v1의 생략된 selection은 원문의 기본 활성 선택으로
해석한다. 같은 XML/스펙 값이 다른 세트에 있어도 선택이 다르면 근거를 재사용하지 않는다.
설계 material 검사도 선언한 selection을 전달한다.

관련68검사와 큰 숫자 ID 경계1검사가 통과했다. 새 stdio4호출로 요약·기본 복원·다른
명시 세트 복원·없는 명시 선택 거절과 소수 값/원문 보존을 확인했다. native 산술은
실행하지 않았다. 증거: artifacts/reviews/redesign-r3-xml-selection-v3.xml,
redesign-r3-selection-id-bound-v1.xml, redesign-r3-selection-stdio-v1/receipt.json.
주력 그룹/젬 모드 override, 원문 보존 XML 수정, 전체 의미 동등성/실제 native·UI 편집은
남아 있으며 capability는 이 미지원/미검증 범위를 명시한다.

### 14.11 주력 XML 그룹 선택

selection.main_group은 원본 XML Skill 목록의1기반 순번이다. 복원에서 빠진 그룹의
뒤라면 기존 remap으로 BuildSpec.main_socket_group에 연결한다. 명시한 그룹 자체가
복원에서 빠지거나 순번이 없으면 대체 선택을 하지 않고 오류를 반환한다.
JSON의 정수 값1.0은1로 정규화하며 bool/비정수/범위 밖 값은 거절한다.
동일한 기본 주력을 명시한 것만으로 소켓 sidecar가 다른 선택이라고 오인되지 않게
원문 기본값으로 생략 필드를 비교한다. 지원 capability/도구 설명에도 main_group을 반영했다.

관련58검사와 JSON 순번 경계1검사, 새 stdio3호출로 원본 그룹3→복원 그룹2의 연결과
빠진 명시 그룹 거절·원문 보존을 확인했다. native 산술은 실행하지 않았다.
증거: artifacts/reviews/redesign-r3-main-group-v1.xml,
redesign-r3-main-pointer-json-v1.xml, redesign-r3-main-group-stdio-v1/receipt.json.
main_active_skill/젬 모드는 여전히 미지원이다. mainActiveSkill은 활성 효과 목록의 순번이며
젬 슬롯이 아니다. #208은 이 둘을 혼동한 기존 경고의 코어 재현이다. native 실제 선택
관측과 원문 보존 수정·전체 의미 동등성 검증은 남아 있다.

### 14.12 Native 선택 관측과 진단 (#208 코어 수정)

공통 scripts/pob_selection.lua는 MAIN 환경의 실제 displaySkillList/mainSkill과
srcInstance↔gemList 객체 대응을 읽는다. 활성 효과 순번(active_index), native 젬 슬롯
(gem_index), 효과 ID/이름, 실제 모드와 statSet 연결 여부, native 모드 목록과 Meta 타입을
구분한다. 현재 activeSkillList에 없는 오래된 객체를 관측된 효과로 쓰지 않는다.
결측/기본 공격은 null/구분 상태로 반환하며 첫 젬/모드를 만들어 채우지 않는다.

단발/상주 모두 POK_META.nativeSelection 형식 pok.native-selection.v1을 반환한다.
공통 observer는 읽기 전용이다. cache protocol6이 이전 결과를 무효화한다.
MCP/조립의 무결성 검사는 더 이상 활성 효과 순번을 젬 슬롯으로 해석하지 않는다.
실제 선택이 Meta거나 요청 순번과 다르면 신고하며 주력 부재/빈 메타 검사는 유지한다.
관측이 없으면 추정으로 해당 젬을 유죄 판정하지 않는다. selection_observation 요약과
meta.nativeSelection 원문은 관측 정보이며 게임 성립/전체 XML 동등성 인증이 아니다.
server_info는 관측 형식/필드/캐시 protocol과 이 범위를 표시한다.

LuaJIT 단위/프로토콜29검사 및 진단/조립/계산 관련91검사 통과. 기능 경계 확인으로
실제 PoB 단발·상주/TREE·순번 보정4건, Meta/주문 진단 양음성2건,
내장 복수 효과/비활성 젬2건을 실행해 통과했다. native8건은 PR 전 전량 통합이나
배포 런타임 검증을 대신하지 않는다. 증거는 redesign-r3-native-selection-v1.xml,
redesign-r3-native-selection-diagnostics-v2.xml, redesign-r3-native-selection-real-v1.xml,
redesign-r3-native-selection-meta-real-v2.xml, redesign-r3-native-selection-extra-real-v3.xml이다.
명시 main_active_skill/모드 선택, 값 경계 및 원문 보존 수정과 전체 R3 완료는 남아 있다.

### 14.13 R3 중간 전체 단위 회귀

공통 native 선택/진단 변경 뒤 전체 단위2297건 중2295통과/2skip, 실패·오류0을
379.332초에 확인했다. skip은 보존되지 않은 v6 실물 문서를 요구하는2검사다.
이는 실제 파일 링크 권한 문제가 아니다. 이전 R3 일부 보고의1skip 원인을 파일
심볼릭 링크로 적은 것은 원본 JUnit을 다시 대조해 v6 실물 문서 부재로 정정했다.
실제 junction 검사 결과는 별도 증거로 유지한다.

증거: artifacts/reviews/redesign-r3-unit-full-v1.xml. 이 결과는 해당 시점의 전체 단위
회귀이며 이후 코드 변경의 통과나 PR 전 전량 native·배포/GUI 검증을 대신하지 않는다.
실제 native 선택 기능 경계8건의 결과와 전체 단위 결과를 합쳐 게임 성립이나 생성 품질
개선 효과가 입증됐다고 보고하지 않는다. R3 잔여와 R4~R7은 계속 진행 대상이다.

### 14.14 효과별 MAIN/CALCS 표현과 숫자 재내보내기

GemSpec의 stat_set_indices/stat_set_calcs_indices는 효과 ID→정수 모드의 별도 지시다.
None과 빈 맵은 다르다. 기존 stat_set_index는 주 효과 MAIN/기본 CALCS 지시를 유지한다.
MAIN 맵은 CALCS에 전파되지 않고, 기존 단일 지시의 CALCS 선택도 지우지 않는다.
명시 CALCS 맵(빈 맵 포함)이 우선한다. 주 효과의 단일 지시와 MAIN 맵이 충돌하면 오류다.
그룹 main_active_skill_calcs도 별도 보존한다. 별칭은 canonical ID로 주 효과를 찾는다.

복원은 다중 효과/환경 차이를 잃지 않고, compact 단일 표현이 동등한 경우 기존 형태를
유지한다. 보조 효과 하나의 값을 주 효과로 차용하지 않는다. 현재 PoB가 무시하는 구형
statSetIndex 속성을 유효한 자식 지시로 되살리지 않고 그 사실을 가정 안내에 남긴다.
숫자 config는 BuildSpec/재내보내기에서도 float로 유지하고 비유한 값은 거절한다.
원문 XML/미지 부분은 기존 원문 필드에 보존한다. 전체 문서 수정 경로는 아직 남았다.

관련79검사 뒤 최종 효과 모드15검사 및 공통 출처/준비도/조립/계산212검사 통과.
숫자 왕복27검사도 통과했다. native MAIN2/CALCS1 보존/구형 속성 비활성2경로와
실제 Frostbolt 별칭의 모드2 전달1경로를 확인했다. 최초 별칭 fixture 오류는 보존했고
해당 경로 재실행이 통과했다. CALCS 탭 실제 계산·GUI/모드의 게임 성립은 미검증이다.
증거: redesign-r3-config-export-v1.xml, redesign-r3-effect-mode-v2/v4.xml,
redesign-r3-effect-mode-callers-v4.xml, redesign-r3-effect-mode-native-v1/v2.xml.
이 후속 변경을 이전 전체 단위2295 결과로 검증됐다고 하지 않는다. 명시 선택 API·원문
보존 수정·전체 R3 및 R4~R7은 계속 미완료다.

### 14.15 원문 보존 XML 속성 편집

pob.document는 UTF-8 byte 위치를 기준으로 지정한 속성 토큰만 교체한다.
전체 문서를 재직렬화하지 않으며 BOM/CRLF·주석·CDATA·미지 속성·비활성 구간을
편집 범위 밖에서 그대로 보존한다. 표준 XML 해석 attributes와 원문 raw_attributes를
구분하고 expected_raw_value로 비교한다. 숫자 entity나 속성 공백 정규화를 실제 원문과
혼동하지 않는다. 새 값은 PoB가 읽는 이름 entity만 사용하고 literal 개행을 유지한다.

read/inspect/edit_pob_document는 검증된 XML blob 참조를 받는다. inspection의 path는
주석/텍스트를 제외한 element 자식의0기반 경로다. 편집은 path/tag/attribute/
expected_raw_value/value를 명시하고 문서 리비전을 대조한다. 여러 속성 변경은 전부
확인한 뒤 같은 artifacts/builds 저장소에 불변 자식/작업 원장을 한 번 게시한다.
충돌/잘못된 대상은 아무것도 게시하지 않으며 no-op은 기존 참조를 재사용한다.
부모는 보존하고 스펙·소켓 근거를 새 문서에 자동 전용하지 않는다. DTD 문서 편집은
지원하지 않고 raw 읽기는 원문을 반환한다. 이 도구는 구조 편집이며 native/게임 검증이 아니다.

기본 편집11검사와 서비스/MCP/스냅샷26검사, 새 stdio6호출을 통과했다.
증거: artifacts/reviews/redesign-r3-xml-document-v1.xml,
redesign-r3-xml-document-service-v3.xml, redesign-r3-document-stdio-v1/receipt.json.
실제 효과/모드 의미 연결, 자식 mode 지시 삽입, 편집 후 native 재측정·근거/설계 재결박,
전체 XML 동등성과 UI 적용은 남아 있다. 현재 전체 단위2295 결과는 이 후속 이전 결과다.

### 14.16 식별한 자식 지시의 추가/갱신

edit_pob_document의 op=upsert_child_attribute는 부모 path/tag와 직접 자식의
child_tag/identity_attribute/identity_value를 명시한다. 일치 자식이 하나면 원문 속성
토큰을 대조해 갱신하고, 없으며 expected_raw_value=null이면 자식을 덧붙인다.
중복 식별자는 임의로 고르지 않는다. 빈 self-closing 부모만 필요한 닫힘 형식으로 바꾸며
다른 형제·주석·CDATA·비활성 부분을 재직렬화하지 않는다. 여러 변경은 한 자식 문서로
게시하고 실패하면 어느 단계도 게시하지 않는다. 기존 set_attribute 입력은 그대로 받는다.

기본/서비스22검사와 새 op의 실제 MCP 전달1검사 통과. 실제 PoB에 mode 자식이 없는
Spark 문서를 계산한 뒤, 원문 보존 삽입으로 MAIN 모드2 지시를 넣어 실제 선택이1→2로
바뀌고 stat_set_resolved=true임을 확인했다. CALCS 지시는 만들지 않았다.
증거: artifacts/reviews/redesign-r3-xml-child-service-v2.xml,
redesign-r3-xml-child-mcp-v3.xml, redesign-r3-xml-child-native-v1.xml.
이것은 선택 API의 native 관측 결박/값 범위 검증이나 게임의 모드 공급/유지 가능성,
전체 문서 동등성·편집 후 설계/근거 재결박을 완료했다는 뜻은 아니다.

### 14.17 원문 XML 계산과 문서 관측 결박

compute_pob_document는 검증된 XML blob을 그대로 run_xml로 계산한다. BuildSpec으로
재구성하거나 암묵적으로 다른 세트를 선택하지 않는다. 응답 stats 필터와 관계없이
전체 native stats/meta 및 정확한 입력 XML을 같은 불변 묶음에 보존한다.
응답 measured_xml_ref는 실제 계산 입력 복사본이며 document_measurement_ref는
format=pok.document-measurement-ref.v1, artifact_id/sha256/manifest_sha256로 구성된다.
큰/작은 MCP 응답 모두 별도의 measurement_ref(tool result)도 받으며 둘은 다른 참조다.

read_pob_document_measurement는 묶음 전체 해시·종류·결과 바이트·XML 리비전과 실제
input.xml 바이트를 대조한다. 같은 바이트를 다른 스냅샷에 복사해도 같은 subject지만,
주석만 바뀌어도 다른 XML에 과거 관측을 전용하지 않는다. 과거/부모 결과는 남긴다.
실행 코드/KB/PoB의 실제 로드 정체성은 아직 not_verified이며 이 참조로 인증하지 않는다.
native_timeout_s는 native subprocess만 제한한다. 전체 요청 수명/절대 기한은 아직
미구현임을 반환한다. 관측/숫자 존재가 게임 성립을 뜻하지 않는다.

관련37검사 및 MCP 참조 분리/전체 결과 보존9검사 통과. 실제 PoB에서 원문 측정→모드
편집→재측정을 실행해 이전 관측의 새 문서 적용 거절과 각 문서의 결과 재독해1건 통과.
증거: artifacts/reviews/redesign-r3-document-measurement-v1.xml,
redesign-r3-document-measurement-mcp-v2.xml, redesign-r3-document-measurement-native-v1.xml.
현재 design-record measurement source의 XML 표현 연결은 아직 미구현이다. 이 새 참조를
기존 spec_sha256 근거로 위장하지 않는다. 효과/모드 범위·의미 검증, 설계/근거 재결박,
실행 정체성·전체 수명·UI 적용과 R3 전체 완료는 남아 있다.

### 14.18 관측 범위로 검증한 효과/모드 선택과 재측정

select_pob_document_effect는 XML ref/리비전·그 문서의 측정 ref·native active_index와
선택적 stat_set_index를 받는다. 정확한 문서 결박을 먼저 검증하고, 현재 매핑된 주력
그룹의 native 효과/모드 목록에서만 선택한다. 효과 순번을 젬 슬롯으로 바꾸어 추정하지
않으며 native gem_index와 원문 젬 ID 대응을 확인한다. ID는 canonical 형태로 비교한다.

원문의 주력 그룹 순번과 native 그룹 좌표가 다르거나 item-generated 그룹,
기본 선택 대체·누락·중복 효과/모드·불명확한 젬 대응이면 편집 전에 거절한다.
직접 대응되는 현재 주력 그룹만 지원하는 범위이며 복잡한 재인덱싱을 해결했다고 하지 않는다.
변경은 MAIN의 mainActiveSkill과 해당 효과 StatSetIndex에만 한정하고 CALCS는 보존한다.

후보를 불변 문서로 만들고 다시 native 계산해 그룹/효과/젬·모드와 모드 label/해석 상태를
대조한다. 일치하면 status=native_selection_matched, 불일치는 native_selection_mismatch,
계산 실패는 measurement_failed다. 실패/불일치에도 후보와 보고를 보존한다.
보고 format=pok.document-selection.v1은 원 관측·계획·후보·재측정 ref를 결박한다.
서버의 현재 문서 head를 적용하지 않는다. matched는 선택 대조의 결과이며
실행 정체성/게임 성립/전체 빌드 준비도 인증이 아니다. native 시간 제한만 적용한다.

관련21검사와 MCP 포함 선택8검사 통과. 실제 PoB에서 보조 뒤 Spark의 모드1→2와
젬1개의 내장 Wind Dancer 효과1→2 선택을 각각 재측정해 일치를 확인했다(native2건).
증거: artifacts/reviews/redesign-r3-document-selection-v1.xml,
redesign-r3-document-selection-mcp-v2.xml, redesign-r3-document-selection-native-v1.xml.
XML 측정의 설계 근거 형식·편집 후 설계/획득 근거 재결박·실행 정체성/전체 수명·UI 적용과
R3 전체 완료는 아직 남아 있다. 이전 전체 단위 결과는 후속 코드의 현재 전량 검증이 아니다.

### XML 측정 근거 연결 추가 검증 — 2026-11-01

설계 기록의 measurement source에 `representation=pob_xml` 분기를 추가했다.
기존 spec 근거 형식은 유지하며 XML 근거에 spec 해시를 혼합하지 않는다.
불변 측정 묶음의 manifest·input.xml·measurement.json을 검증하고, 현재 material의
XML 해시와 선언한 선택 및 native 관측을 대조한다. 같은 XML이어도 material 리비전이
바뀌면 명시적인 재연결이 필요하다. 비교·과거 근거는 원래 material 리비전을 보존한다.
이 검증은 게임 성립이나 실행 중인 코드/KB의 정체성을 인증하지 않는다.
이전 절의 XML 근거 형식 미구현 표기는 이 범위에서 대체된다.

`design_service.link_document_measurement`는 원본 checkpoint를 보존하며 새 근거를
연결한다. 오래된 설계 리비전, 다른 XML, 선택 불일치, 부적합한 측정 경로는 현재 근거로
연결하지 않는다. 비교·과거 연결에는 원래 material 리비전을 명시해야 한다.
MCP `attach_pob_document_measurement`로 공개했다. UI 채택은 미완료다.

증거: `artifacts/reviews/redesign-r3-xml-evidence-v1.xml` 관련88검사 통과,
`redesign-r3-xml-evidence-native-v1.xml` 실제 PoB1검사 통과,
`xml-link-helper-v2.xml` 연결 도우미 포함9검사 통과. Ruff 및 서비스 mypy 통과.
첫 도우미 검사 시도는 Windows 임시 디렉터리 ACL로 실패했고 새 경로에서 재검사했다.
현재 전체 단위/통합 검사 완료를 의미하지 않으며 R3는 진행 중이다.

후속 MCP 검증: `xml-link-mcp-v1.xml` 19검사 통과. FastMCP Client로 등록된
도구를 호출해 현재 XML 근거 연결과 오래된 expected_revision 거절을 확인했고,
기존 설계 서비스 회귀 검사를 함께 실행했다. 서버 Ruff/mypy도 통과했다.

### XML 공급자 연결 — 2026-11-01

`pob_xml` provider binding을 구현했다. `inspect_pob_document`의 각 노드는
`provider_binding_pointer`와 `provider_binding_value_sha256`를 제공한다.
포인터는 `/nodes/root` 또는 `/nodes/1.0.2`처럼 루트 아래 element-only 경로를 사용한다.
필터/페이지 순번이 아니며 주석과 텍스트는 경로 번호에 포함하지 않는다.
값 해시는 해당 노드 전체의 정확한 UTF-8 원문 문자열을 canonical JSON으로 해시한 값이다.
따옴표·공백·주석 변경도 내용 변경으로 감지하는 보수적 연결이다.
원문 노드 내용이 바뀌거나 경로가 사라지면 needs_review를 반환한다.
동일 값의 다른 material에서는 same_value_revalidated_at_new_material로 구분한다.

이 연결은 그 노드가 활성 세트의 실제 공급자인지, 인게임 효과가 성립하는지 인증하지 않는다.
노드 이동을 의미적으로 추적하지 않으며 새 위치를 추측하거나 연결을 자동 변경하지 않는다.
기존 set_material 갱신은 의존 결정을 재검토 상태로 표시한다. 원문 내용 대조가 성공해도
그 재검토를 자동 해제하지 않는다. 이전 XML binding 미지원 표기는 이 범위에서 대체된다.

증거: `artifacts/reviews/xml-provider-binding-v2.xml` 74검사 통과.
Unicode/CDATA/주석 원문, 잘못된/누락된 포인터, 원문 변경/유지와 material 변경,
기존 spec 연결·XML 편집 회귀를 검사했다. 관련3모듈 mypy와 Ruff 통과.
전체 R3 또는 현재 전량 단위/통합 검사가 완료된 것은 아니다.

### 편집 후 소켓 선언 재결박 — 2026-11-01

`rebind_socket_sidecar` 엔진/MCP 경로를 추가했다. 원본 XML 참조와 기존 sidecar의
전체 바인딩을 먼저 검증하고, 새 XML에서 명시된 selected projection 리비전을 확인한다.
기존 선언의 모든 슬롯에서 정규화한 아이템 문구가 같아야 새 불변 sidecar를 게시한다.
설정/주석 변경은 아이템 문구가 같다면 재결박할 수 있다. 슬롯 소실·아이템 변경·
잘못된 원본·오래된 목표 projection은 새 sidecar를 발행하기 전에 거절한다.
바뀐 아이템에는 create_socket_sidecar로 새 선언을 명시해야 한다.

새 묶음은 원본 XML/sidecar와 목표 XML 참조를 rebinding provenance로 보존한다.
이전 묶음은 수정하지 않고, 설계 material이나 UI의 현재 참조도 자동 변경하지 않는다.
획득 경로는 여전히 호출자 선언이며 실제 드롭/거래 이력의 증명이 아니다.
아이템 비교는 기존 복원기의 줄바꿈/바깥 공백 정규화 범위이며 실물 동일성 인증이 아니다.
다른 선언 필드 전체를 복사하는 도구가 아니라 소켓 획득 선언만 재결박한다.

증거: `artifacts/reviews/socket-rebinding-mcp-v2.xml` 18검사 통과.
기존 복원/소켓 획득 규칙 회귀, 설정/주석 편집, 슬롯/아이템 변경, stale projection,
잘못된 원본의 게시 전 거절과 실제 FastMCP 호출을 검사했다. 관련3모듈 mypy/Ruff 통과.
UI의 원자적 적용/undo와 전체 실행 수명·실행 정체성은 아직 완료하지 않았다.

### PoB 데몬 명령 기한과 복구 — 2026-11-01

PobDaemon은 command_timeout_s(기본180초)를 잠금 대기부터 명령 완료까지 적용한다.
중첩된 start/compute는 바깥 명령의 더 이른 절대 기한을 공유하며 출력 메시지가
기한을 연장하지 않는다. transaction의 잠금 대기도 제한하지만 여러 명령으로 구성된
전체 transaction이나 전체 MCP 요청의 기한을 구현한 것은 아니다.

잠금 대기 만료는 not_owned로 보고하고 실행 중인 다른 소유자의 프로세스를 종료하지 않는다.
응답/완료 기한 만료는 소유한 직접 자식에 kill/wait를 적용하고 direct_child_confirmed와
unconfirmed를 구분한다. 종료 미확인 시 자식 참조를 보존하고 loaded_spec을 무효화하며
재사용을 막는다. 확인된 종료 뒤 다음 명령은 새 프로세스를 시작한다.
PobCommandTimeout의 phase/termination 및 오류 문자열에 이 차이를 보존한다.
출력은 요청한 한 줄씩 별도 읽기 스레드로 받아 메인 명령의 블로킹 대기를 제한하며,
완료된 바깥 명령은 유휴 읽기 스레드를 정리한다.

증거: pob-command-deadline-v3.xml 관련29단위 통과, native-v1 선택/기동9검사 통과.
명령 완료 시점의 기한 검사/읽기 정리 보강 뒤 native-v2에서 실제 종료→새 기동→Spark
계산1검사를 재확인했다(모두 artifacts/reviews/ 아래 동일 접두).
최초 단위 v1 실패는 transaction을 빌려 쓰는 테스트 Probe의 새 timeout 필드 누락이었고
해당 fixture를 교정해 재검사했다. daemon/server mypy와 관련 Ruff 통과.

이 결과는 전체 요청 소유 ID/기한·MCP 취소 전파·다른 프로세스의 복구·하위 프로세스
트리 종료·단발 runner의 파이프 정리까지 입증하지 않는다. 그 경로와 실행 정체성은
R3 잔여 작업이며 native_command_lifetime capability에도 미구현 범위를 명시한다.

### 단발 PoB 시간 초과 출력 정리 — 2026-11-01

runner는 stdout/stderr를 임시 일반 파일로 받는다. 시간 초과에서 subprocess.run이
직접 자식을 종료/대기한 후, 하위 프로세스가 물려받은 출력 파이프의 EOF를 기다리는
Windows 경로를 제거했다. 읽기는 fstat으로 고정한 파일 크기만큼만 수행하고 UTF-8로
해석한다. 시간 초과의 부분 stdout/stderr는 TimeoutExpired에 보존한다.
실패 시 요청별 임시 XML을 정리하고 계산 캐시는 발행하지 않는다.
전체 프로세스 트리의 종료를 확인했다는 뜻은 아니며 예외 note에도 그 범위를 명시한다.

증거: `artifacts/reviews/pob-driver-timeout-v1.xml` 16검사 통과.
실제 하위 프로세스의 출력 핸들 유지, 부분 출력 보존, UTF-8 성공/오류,
기존 동일 XML 동시 실행과 데몬 명령 기한 회귀를 포함한다. 테스트 하위 프로세스의
자연 종료도 확인했다. `pob-driver-timeout-native-v1.xml` 실제 PoB2검사 통과.
runner mypy 및 관련 Ruff 통과. 전체 MCP 요청 기한/취소 전파와 실행 정체성은 남아 있다.

### 요청 컨텍스트와 native 전달 코어 — 2026-11-01

common.execution.ExecutionScope는 요청 ID/소유자·입력 리비전 선언·불변 monotonic 기한을
유지한다. 중첩 컨텍스트가 다른 요청으로 교체되어 기한을 새로 시작하지 못한다.
취소 요청·기한 초과와 worker_finished를 구분하며 등록 자원이 active/unconfirmed이면
finish도 termination_unconfirmed로 보고한다. 자원 종료 미확인 핸들은 scope가 보존한다.
스냅샷의 confirmation_scope는 registered_resources_only이며 전체 OS 프로세스 감사나
호출자 인증이 아니다. 지금은 내부 코어이며 MCP 공개 요청 수명 계약 완료로 광고하지 않는다.

ExecutionStopped는 일반 Exception fallback이 중단을 삼키지 않도록 별도 제어 흐름이다.
데몬 잠금 대기/응답 읽기와 단발 runner의 wait를 짧은 간격으로 확인하고 실제 소유 자식의
kill/wait 뒤 상태를 보고한다. runner는 scope가 있을 때 Popen으로 명시적으로 소유하며
scope가 없는 기존 직접 호출 경로는 subprocess.run을 유지한다. 중단된 요청의 부분
stdout/stderr는 제어 예외 details에 보존하며 timeout이나 취소를 정상 산술 결과로 바꾸지 않는다.
데몬 명령을 정상 반환해 소유권을 놓는 것과 프로세스 자체의 종료를 구분한다.

증거: request-scope-native-v3.xml 관련30단위 통과. 실제 테스트 자식에 대한 취소/기한,
다른 요청 격리, 종료 미확인 핸들 보존, fallback 예외와의 구분, 기존 동시성 회귀 포함.
Windows에서 시작 기한이 첫 출력보다 먼저 끝날 수 있어 deadline 시 빈 부분 출력과
출력 준비 후 취소를 분리해 검사했다(v2 실패 원본 보존).
request-scope-native-pob-v1.xml 실제 PoB 단발 실행과 데몬을 한 scope에서 수행하고
등록 자원 정상 해제1검사 통과. 관련3모듈 mypy/Ruff 통과.

잔여: MCP 전송 경계에서 scope 생성/조회/취소/예외 변환, 전체 도구 예산과 상태 영속화,
늦은 게시/재연결·서버 재시작 복구, 모든 하위 프로세스와 다른 네이티브 경로 적용.
특히 이 내부 제어 예외를 전송 경계에서 변환하기 전에는 일반 MCP 응답으로 내보내지 않는다.
R3 전체·실행 정체성·R4~R7의 완료 증거로 사용하지 않는다.

### MCP 실행 감독·상태 회수 — 2026-11-01

MCP의 일반 도구 호출은 RequestManager가 ExecutionScope로 감독한다. 직접 Python API의
반환 계약은 유지한다. 요청의 `_meta.pok_execution`에는 선택적으로 `request_id`(32자리
소문자 hex)와 `timeout_s`를 제공한다. 기본/최대 도구 실행 예산은600초이며 클라이언트는
더 짧게 지정할 수 있다. 메타데이터/인자 지문 확인 뒤 감독을 시작하고, 스레드 대기와
실제 도구·반환 처리는 같은 절대 기한을 사용한다. 정리 확인 유예는 최대5초다.
진행 알림은 이 기한을 늘리지 않는다. 클라이언트의 총 시간제한에는 이 유예와 전송 여유를
포함해야 하며 현재 서버가 임의 클라이언트의 미공개 시간제한을 알아내는 것은 아니다.

응답 `_meta.pok_execution`은 format/server_instance/request_id의 실행 참조다.
성공 content·structuredContent·data는 보존하고 기존 fastmcp 메타데이터도 유지한다.
메타데이터 공간을 wire 예산에 미리 남긴다. `get_execution_status`, `cancel_execution`,
`read_execution_result`는 감독 중인 요청과 독립적으로 호출할 수 있다. 취소 요청은 실제
worker_finished/등록 자원 상태와 구분한다. 늦은 워커 반환은 완료 결과로 회수하지 않는다.
완료한 wire 결과는 같은 서버 프로세스의 보관 범위 안에서 다시 읽을 수 있다.

참조는 새 서버 인스턴스에서 거절한다. 기록 부재/정리는 완료 증거가 아니다.
완료 기록 기본1024개를 보관하며 실행 중/종료 미확인 자원은 정리하지 않는다.
정리된 ID도 같은 프로세스에서 재사용하지 않아 이전 참조가 새 요청으로 바뀌지 않는다.
ID tombstone은 프로세스 수명 동안 보존한다. 이것은 영속 작업 저널/신원 인증이 아니다.
서버 재시작 복구, 모든 native 경로/프로세스 트리, 임의 Python 작업의 강제 선점은 남아 있다.
비협조적 워커가 살아 있으면 기한 초과 의도와 worker_finished=false를 그대로 보고한다.

실제 설치 SDK에서는 클라이언트 로컬 태스크 취소가 notifications/cancelled를 자동으로
보내지 않았다. 명시 MCP 취소 통지와 cancel_execution은 별도 경로로 검증했다.
로컬 대기 취소만으로 서버 취소를 주장하지 않는다. AnyIO 워커 컨텍스트를 유지하여
기존 assemble_pob 진행 보고(anyio.from_thread.run)가 작동하는 것도 검사한다.

증거: request-transport-v3.xml 관련64검사 통과. AnyIO 워커 컨텍스트와 진행 보고를
보강한 뒤 request-transport-v4.xml 관련41검사 통과. request-transport-native-v2.xml은
실제 MCP에서 PoB 자식 시작 관측→취소→자식 종료 확인→다음 Spark 계산1검사를 통과했다.
관련3모듈 mypy/Ruff 통과. 첫 v1 실패는 로컬 대기 취소의 잘못된 전제와 추가 메타데이터를
구분하지 않은 기존 동일성 검사였으며 원본을 보존했다. 현재 전체 단위 재검사는 진행 중이고
이 좁은 결과를 전체 R3/배포 검사 통과로 사용하지 않는다.

### 실행 식별 후속 감사 — 캐시 키의 범위 (2026-11-01)

전체 단위 검사 중 구현 소스를 바꾸지 않고 별도 프로세스/격리 fixture에서
실제 runner._cache_path를 호출했다. XML·PoB commit·protocol6을 고정한 채 fixture의
pob_driver.lua 내용을 A→B로 바꾸자 SHA-256은 달라졌지만 캐시 이름은 동일했다.
증거: `artifacts/reviews/redesign-r3-cache-identity-audit/result.json`.
현재 키는 protocol/commit/XML에 의존하며 드라이버 내용 자체를 식별하지 않는다.
수동 protocol 증가 규칙과 실제 실행 내용 식별은 별개다. 실제 PoB 계산을 하지 않은
키 함수 실험이므로 잘못된 DPS가 발생했다거나 과거 실험 결과가 틀렸다고 주장하지 않는다.
실제 소스/실행기/캐시 식별을 연결하기 전에는 기존 캐시가 현재 실행 내용을 입증하지 못한다.

이 감사에서 runtime/KB/PoB 원본과 동결 입력은 수정하지 않았다. 현재 전체 단위 검사에서
실패1건이 관측되어 완료 결과/원인 확인이 우선이며, 다음 실행 식별 구현은 그 뒤에 진행한다.

### 전체 단위 체크포인트와 두 회귀 교정 — 2026-11-01

`redesign-r3-unit-full-v2.xml`:2412개 중2408통과/2skip/2실패(400.066초).
두 skip은 tests.unit.test_design.test_v6_실문서_추출 및
 tests.unit.test_mcp_constraints.test_parse_design_doc_v6의 로컬 v6 문서 부재다.
실패는 새 native 통합 시험의 환경 가드 표기와 server_info의 응답 크기 회귀였다.

native 시험에는 실제 skipif 환경 가드를 적용했다. LuaJIT 경로를 의도적으로 부재로
지정한 `request-native-missing-runtime-guard-v1.xml`에서1건 skip/실패0으로 확인했다.
이 검사는 native 계산 성공이 아니라 CI의 런타임 부재 처리 검증이다.

server_info의 식별/전체 도구 인자 지문은 inline으로 유지하고 capabilities는 요약했다.
상세는 capabilities.details_tool이 가리키는 get_server_capabilities로 손실 없이 조회한다.
기존 full capability의 세부 필드는 이 도구에서 읽으며 응답이 크기 때문에 저장 참조로
바뀌어 identity 필드가 사라지는 회귀를 막는다. 실제 두 복사 wire 크기를 검사하고 실행
참조 메타데이터를 위한512바이트 여유도 확인한다. 상세 기능 조회는 cold KB 로드를 요구하지 않는다.

수정 후 `request-full-unit-regression-fixes-v1.xml` 환경 가드·실제 server_info/상세 기능·
요청 감독13검사 통과. 관련 Ruff/server mypy 통과. 전체 실패 원본은 보존한다.
현재 전체 단위를 수정 후 다시 전량 실행했다고 주장하지 않으며 이 교정의 범위와 구분한다.
후속 실행/캐시 식별 구현 및 PR 직전 전량 검증은 여전히 남아 있다.

### 캐시 내용 식별과 무효화 — 2026-11-01

PoB cache v2는 XML/protocol/commit뿐 아니라 실행 중인 Python 어댑터 code object,
Lua 어댑터 파일·PoB 비시각 소스·번들 runtime·실행기 파일의 실제 내용 관측에 결박된다.
파일 크기/mtime이 같아도 바이트가 다르면 새 키를 사용한다. 캐시 envelope는 키와 실행
관측 SHA 및 result SHA를 검사하여 다른 입력의 파일 복사나 JSON 내 수치 손상을 거절한다.
기존 캐시 파일은 삭제하지 않고 새 형식/키로 전환한다.

캐시 미스의 계산 전후 관측이 다르면 게시하지 않는다. 계산 후 관측 실패는 알려진 내용
변경으로 단정하지 않고 unverified_after_calculation과 원래 diagnostics로 보존한다.
초기 관측 불가/어댑터 코드 식별 불가는 캐시를 끄며 그것만으로 native 산술 실패를 만들지 않는다.
meta.execution_inputs와 get_server_capabilities.calculator_cache에 범위를 명시한다.

이것은 point-in-time 내용 관측이며 native가 실제로 로드한 모든 모듈의 증명이 아니다.
시각 자산과 번들 밖 시스템 라이브러리는 범위 밖이고 loaded_native_modules는 not_verified다.
PoB pin을 실제 파일 내용의 대용으로 쓰지는 않지만 전체 KB/Python 메모리·장수명 데몬의
로드 정체성 및 영속 실행 복구까지 완료한 것은 아니다. 초기 키 감사의 동일 키 재현은
변경 전 증거로 보존하며 새로운 내용 결박을 소급 적용하지 않는다.

증거: pob-cache-content-binding-v2.xml 관련59검사 통과. 후속 관측 불가 구분과 identity
inline 회귀를 포함한 v3.xml 관련22검사 통과. pob-cache-content-native-v1.xml 실제 PoB4검사,
최종 v2.xml 실제 캐시 재사용→격리한 Lua 주석 변경→재계산1검사 통과.
원본 PoB/원본 Lua는 수정하지 않고 테스트 복사본만 변경했다. 최초 캐시 파일도 불변 확인.
관련3모듈 mypy/Ruff 및 통합 환경 가드 통과. 현재 전량 단위/통합 통과를 뜻하지 않는다.

비용은 단일 호스트 관측(native-v2/test_actual_cache_reuse_and_lu0/native-timings.json):
새 계산3.891초, 캐시 적중0.981초, 내용 변경 후 재계산3.670초.
관측 대상은 Lua어댑터12파일/65,135바이트, 비시각 PoB소스1116파일/48,731,944바이트,
runtime40파일/21,822,487바이트와 실행기294,912바이트였다. 개선 전후 제품 성능/품질
우위의 증거가 아니며 파일 해시 비용을 숨기지 않고 후속 비교에 남긴다.

### 메모리에 로드된 코드·KB의 분리 관측 — 2026-11-01

observe_loaded_execution은 디스크 소스 대신 실제 Python function code object와 이미
캐시된 KB Store의 raw records/subjects 내용을 관측한다. 함수 wrapper와 함수 closure,
클래스 메서드/속성 접근자의 코드를 포함한다. loaded_snapshot_identity는 load를 호출하거나
현재 디스크를 재검증하지 않는다. 파일만 수정하면 기존 메모리 식별은 유지되고, 코드 객체
교체나 Store.raw 변경은 새 식별을 낸다. KB snapshot_id는 실제 객체와 내용 해시를 구분한다.

측정 receipt의 source.loaded_execution_observation.before/after에 자동 보존한다.
기존 source_observation은 디스크 관측으로 유지하여 새 파일 해시를 오래된 메모리 객체의
해시로 대신 쓰지 않는다. 모듈 지연 로딩으로 inventory가 늘 수도 있으므로 해시 차이를
곧바로 게임 불성립이나 잘못된 계산으로 판정하지 않는다.

원시 marshal 직렬화를 사용한 첫 반복 관측이 같은 코드에서 불안정한 해시를 냈다.
loaded-execution-observation-v1.xml의 실패와 별도 재현을 보존하고, 공통 code_identity로
bytecode/정규화한 상수·코드 메타데이터를 해시하도록 교정했다. PoB 캐시의 Python 코드
식별도 이 안정적인 함수를 공유한다. 참조 수/실행 warm-up과 frozenset 순서에 대한 회귀도
검사한다. 이전 캐시 관측을 새 알고리즘의 검증으로 소급하지 않는다.

범위는 관측한 코드 객체·이미 캐시된 KB 내용이다. 일반 mutable globals/defaults,
함수가 아닌 closure 상태·서드파티·실제 native 프로세스 로드 모듈 전체는 not_verified다.
관측할 수 없는 코드 상수는 incomplete_code_inventory와 diagnostics를 남긴다.
전체 실행 인증이나 게임 성립 인증으로 승격하지 않는다.

증거: loaded-execution-observation-v3.xml 관련44검사 통과.
loaded-execution-native-v1.xml 실제 PoB MCP 계산의 저장 receipt에서 디스크/메모리 관측
분리1검사 통과. loaded-execution-cache-native-v1.xml 새 안정 코드 해시의 실제 캐시
재사용/격리 Lua 변경 무효화1검사 통과. 관련6모듈 mypy/Ruff 및 통합 가드 통과.
현재 전체 단위/통합 재검증이나 R3 전체 완료를 뜻하지 않는다.

비용: artifacts/reviews/loaded-execution-memory-timing/result.json의 명시 KB 로드 probe에서
19,758레코드의 메모리 관측1.131초/1.157초, Python/KB 해시 모두 안정적이었다.
별도 명시 로드28.903초는 관측 API가 강제로 유발한 비용이 아니다. KB 미로드 상태의
코드 inventory 관측은 약0.060초였다. 단일 호스트 관측이며 품질/제품 개선 효과의 증거가 아니다.
다음은 장수명 native 데몬의 시작 시 관측/현재 파일 관측 분리와 잔여 실행 복구다.

### 데몬 시작 관측과 현재 파일 분리 — 2026-11-01

PobDaemon은 시작 전후의 내용 관측을 프로세스 PID/generation에 결박해 보존한다.
compute/TREE/POWER의 meta.daemon_execution은 그 시작 관측을 복사해 반환하며 현재 파일
관측으로 덮어쓰지 않는다. 외부에서 반환 객체를 수정해도 내부 시작 관측은 바뀌지 않는다.
종료 후 last_startup은 과거 증거로만 제공하고 새 시작은 새 generation/관측을 만든다.
종료된 프로세스가 남아 있으면 확인/정리 후 새로 시작하여 옛 응답 프레임을 재사용하지 않는다.

inspect_pob_runtime은 기존 공유 데몬만 조회하고 프로세스나 KB를 새로 시작하지 않는다.
초기화/명령 소유자가 잠금을 보유하면 대기 대신 busy를 반환한다. observe_current=True로
명시한 경우에만 전체 현재 파일 관측과 current_matches_startup 비교를 수행한다.
기본 계산마다 큰 파일 트리를 다시 읽지 않는다. scope=shared_daemon_only이며 독립 데몬
전체를 열거하거나 native에 실제 로드된 모든 모듈을 증명하는 도구는 아니다.
process_state와 시작 입력 관측을 구분하고 loaded_native_modules=not_verified를 유지한다.
상세 capability는 get_server_capabilities.daemon_startup_observation에서 읽는다.

선택한 driver 경로와 LUA_PATH도 관측에 포함했다. 같은 디렉터리에 다른 driver가 있어도
선택 경로만 바꾸면 기존 단발 캐시를 재사용하지 않는다. 실행기 경로는 절대 경로로 실행한다.
시작 관측 단계에서 기한이 끝나면 자식을 만들지 않고 no_process로 보고할 수 있으며,
이미 만든 자식의 직접 종료 확인과 구분한다. 기존 native 짧은 기한 검사를 이 구분에 맞췄다.

증거: daemon-startup-identity-v2.xml 관련30검사 통과. 비차단 공유 조회·실제 MCP 조회와
identity inline 후속 daemon-startup-mcp-v3.xml 관련20검사 통과.
daemon-startup-native-v1.xml 실제 PoB11검사 통과: 격리 Lua 복사본 변경 뒤 옛 시작 관측
보존·TREE 계산·종료/재시작 갱신, 기존 선택/기한 복구 경로를 포함한다. 원본 PoB/Lua는
수정하지 않았다. 관련5모듈 mypy/Ruff 통과. 전체 단위/통합 재실행 완료는 아니다.

영속 요청 저널/서버 재시작 복구·전체 프로세스 트리·추가 native 경로의 수명 적용 및
실제 로드 모듈 전체 인증은 남아 있다. R3 전체 또는 R4~R7 완료로 보고하지 않는다.

### 소유 프로세스 트리 기반 — 2026-11-01 (PoB 연결 전)

common.owned_process에 실제 Popen과 소유 containment를 묶는 기반을 추가했다.
Windows는 CREATE_SUSPENDED로 만든 초기 스레드를 Job Object에 배정한 뒤 재개한다.
Job에는 kill-on-close만 설정하고 breakaway 허용 플래그를 두지 않는다.
종료 요청 후 직접 자식 wait와 Job의 active process count=0을 확인한 경우에만
windows_job scope의 confirmed를 반환한다. 동시 정리·재시도는 같은 소유 잠금으로 직렬화한다.
Job 배정 실패는 정지 상태 자식을 정리하고 결과를 예외 owned_cleanup에 보존한다.
종료 미확인은 owned_process 핸들을 예외에 남겨 호출자가 유지할 수 있게 한다.

API 의미는 Microsoft의 [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects),
[정지 스레드 생성](https://learn.microsoft.com/en-us/windows/win32/procthread/suspending-thread-execution),
[Thread Walking](https://learn.microsoft.com/en-us/windows/win32/toolhelp/thread-walking)을 확인했다.
검증은 참고 문헌만이 아니라 실제 프로세스/커널 Job 정보로 수행했다.

증거: artifacts/reviews/owned-process-containment-v3.xml 실제 Windows5검사 통과.
Root 종료/재시도, 같은 소유 작업 동시 정리, 자식·손자 PID의 실제 Job 구성원 확인,
다른 Job 구성원과의 분리/다른 작업 지속, 배정 실패 시 사용자 코드 미실행,
소유 프로세스 강제 종료 뒤 열린 자식 핸들의 종료 신호를 확인했다.
관련 Ruff/mypy 통과. 프로세스/PID 임의 열거 후 일괄 종료하는 경로를 쓰지 않는다.

POSIX는 새 session/process group scope이며 의도적 group escape를 막지 않는다.
Leader가 이미 reap됐는데 group이 남아 있으면 ID 재사용 위험 때문에 다른 그룹을
자동 종료하지 않고 unconfirmed로 남긴다. 현재 이 POSIX 분기는 실제 OS에서 검증하지 않았다.
또한 Windows 생성 중 parent가 종료되는 극소 spawn/assign 구간과 시스템 서비스가
별도로 만든 작업 등까지 완전한 OS 작업 추적을 보장하는 것은 아니다.

아직 기존 PoB runner/daemon에 연결하지 않았으므로 현재 제품 경로의 트리 종료 완료를
광고하지 않는다. 다음은 해당 경로 연결·자원 ledger/미확인 핸들 보존·실제 PoB 회귀다.
영속 요청 저널/서버 재시작 복구와 R3 전체 및 R4~R7은 여전히 남아 있다.

### 소유 containment의 PoB 연결 — 2026-11-01

runner의 scope 유무 양 경로를 _run_owned_driver로 통합하고 daemon도 spawn_owned를 쓴다.
취소/명령 기한/정상 반환 후 직접 자식만이 아니라 등록 Job/group 정리 결과를 확인한다.
미확인 handle은 scope가 보존하고 resource.details에 정리 status/scope/reason을 복사한다.
종료 확인 사실을 generic finally의 released가 덮어쓰지 못하며 외부 snapshot 수정도 원장을
바꾸지 않는다. 프레임 완료 전 EOF와 I/O 오류는 소유 프로세스를 정리하고 재사용하지 않는다.
완성 프레임의 도메인 POK_ERR는 기존처럼 다음 정상 명령을 쓸 수 있어 구분한다.

spawn 배정/재개 전에 취소될 수도 있으므로 이 경우에도 생성된 자식과 실제 정리 결과를
기록한다. spawn 실패의 정리 확인/미확인을 전체 작업의 계산 실패·인게임 불성립과 혼동하지 않는다.
POSIX group은 escape 방지/이미 reap된 leader 식별 한계가 있어 windows_job과 같은 보장으로
표시하지 않는다. capability에는 적용 경로 runner/daemon과 미적용 경로를 명시한다.

증거: pob-owned-containment-v4.xml 관련50검사 통과. 실제 PoB MCP 취소의 자원 정리 확인·
후속 계산/문서 근거·캐시 재사용/변경·데몬 재시작4검사(native-v1.xml) 통과.
pob-owned-daemon-timeout-native-v3.xml은 살아 있는 실제 데몬의 명령 기한 초과→Job 정리
확인→terminated 자원 사실 보존→새 프로세스 Spark 계산1검사를 통과했다.
초기 추가 시험(v2)은 XML 생성이 요청30초를 넘어서 전체 요청 기한이 먼저 끝났으며,
그때도 소유 작업 정리는 확인됐다. 명령 기한 검사는 XML 준비를 분리해 다시 수행했다.
초기 단위 v1은 cold 시작 전 출력 가정과 새 spawn 주입 지점이 원인이었고 실패 원본을 보존했다.
출력 시험은 실제 ready 신호 이후를 확인하며 실제 프로세스/containment를 대체하지 않았다.
관련 mypy/Ruff 및 통합 환경 가드 통과. 현재 전체 단위/통합을 다시 완료한 것은 아니다.

남은 native 호출은 item_editor/roundtrip/parse_gaps/item_parse_gaps다. 이 호출들은 아직
새 수명 경로로 옮기지 않았으며, 영속 요청 저널·서버 재시작 복구·POSIX 실제 검증과
R3 종합 감사도 남아 있다. 코드/메모리 관측 범위 밖의 완전한 실행 인증을 주장하지 않는다.

### 남은 native 호출 통합과 입력 소유권 — 2026-11-01

run_native_capture는 소유 프로세스 실행/기한/취소와 일반 파일 출력 수집을 공유한다.
runner뿐 아니라 item_editor, roundtrip, parse_gaps, item_parse_gaps도 이 경계를 사용한다.
UTF-8 해석과 시간 초과/취소의 부분 stdout/stderr 보존은 유지한다. 선택 실행기를 절대
경로로 실행하고 새 캡처 helper의 실제 코드 객체도 캐시 내용 식별에 포함한다.

왕복/트리/아이템 파싱의 공유 임시 파일을 호출별 UUID 파일로 바꿨다. 동시 호출은 같은
입력/베이스여도 다른 파일을 사용하고 자기 파일만 삭제한다. 아이템 편집 취소는 임시
디렉터리를 정리하기 전에 입력과 부분 output JSON을 ExecutionStopped.details에 보존한다.
기존 timeout의 부분 판정 처리와 성공/비호환 분류를 취소 성공으로 바꾸지 않는다.

규율은 test_pob_native_boundary AST 검사로 고정한다. PoB 어댑터의 직접 subprocess
spawn과 별칭/직접 import를 검사하여 공통 소유 실행 경계를 우회하지 못하게 한다.
기존 인코딩 검사와 별개로 소유권/기한이 빠진 새 경로의 재유입을 감지한다.

증거: native-capture-paths-v2.xml 관련61검사 통과. 마지막 경계/아이템/요청/식별 후속
native-capture-boundary-v3.xml 27검사 통과. native-capture-paths-native-v1.xml 실제 PoB의
왕복 변환·아이템 더블클릭 검사·트리 파싱 덤프·아이템 문구 파싱4경로 모두 완료했고
각 요청의 소유 자원 details.status=confirmed를 확인했다. 원본 PoB/KB는 변경하지 않았다.
처음 v1의 두 실패는 새 왕복 fixture에서 API 이름을 roundtrip_items로 잘못 쓴 것이었고
실제 roundtrip API로 고쳐 재검사했다. 관련6모듈 mypy/Ruff 및 통합 환경 가드 통과.

현재 전량 단위 redesign-r3-unit-full-v3.xml 검사를 시작했으며 종료 결과는 아직 미확인이다.
PR 직전 전량 통합, 영속 요청 저널/서버 재시작 복구, POSIX 실제 검증과 R3 종합 감사는 남아 있다.

### 영속 실행 복구의 구현 계약 정리 — 2026-11-01 (구현 전)

현재 프로세스 내 RequestManager를 보완할 영속 기록은 기존 artifacts/builds 불변 저장을
재사용한다. 새 최상위 저장소/DB나 빌드의 별도 mutable head를 만들지 않는다.
서버 instance/request ID로 구분한 시작/종료 체크포인트를 별개 kind=execution-checkpoint로
보존하고, 기존 빌드 목록은 이 kind를 이어받을 빌드로 노출하지 않아야 한다.
시작 기록은 명시 입력 JSON/입력 지문·소유자·기한을, 종료 기록은 시작 참조·실제 종료/자원
상태·오류/부분 증거·반환 wire JSON을 묶는다. 원래 design JSON 문자열은 재직렬화하지 않는다.

회수는 명시 recover 경로로 수행한다. 현재 서버의 live 취소와 과거 기록 회수는 다르다.
완료 체크포인트는 전체 manifest/파일 해시와 시작 기록 연결을 검증한 뒤 회수한다.
시작만 있으면 nonterminal/unknown으로 남기고 서버 변경만으로 실패/취소/완료로 바꾸지 않는다.
예전 서버가 별도 프로세스에서 살아 있을 수도 있으므로 과거 PID나 잠금 파일로 자동 종료하지 않는다.
미확인 자원이나 늦은 반환은 완료 추천으로 회수하지 않는다. 재실행은 새 요청으로 명시하며
과거 결과 회수 자체가 현재 XML/설계 적용이나 자동 재개를 뜻하지 않는다.

저장 실패는 실제 작업 상태와 별도로 표시해야 한다. 시작 저장이 실패한 요청을 몰래
미기록 상태로 실행하지 않으며, 종료 게시가 실패해도 원래 입력/시작 증거를 덮어쓰지 않는다.
새 kind는 저장/목록/해시/부분 쓰기·충돌 시험과 실제 MCP 재기동 회수로 검증할 대상이다.
현재는 저장 API/영향 경로를 점검한 계약 정리이며 구현/재기동 검증 완료가 아니다.

영속 저장 primitive 사전 실험: execution-checkpoint-storage-probe-v2/result.json에서
기존 불변 store로 요청 bytes가 정확히 보존되고 manifest 검증을 통과하는 것을 확인했다.
내부 design JSON의 지수 표기/큰 정수 문자열도 그대로 유지했다. 동시에 현재 legacy
list_builds가 이 새 kind를 빌드로 노출하는 것을 재현했다. 영속 저널 구현 시 목록 필터와
회귀 시험을 함께 추가해야 한다. 이 격리 실험은 RequestManager 영속 복구 구현의 증거가 아니다.
첫 비승격 실험은 Windows 임시 디렉터리 ACL로 실패했고 새 격리 경로에서 재검증했다.
구현 소스/동결 입력은 변경하지 않았다.

### 전량 단위 v3 종료와 영속 저널 기반 — 2026-11-01

redesign-r3-unit-full-v3.xml:2450개 중2448통과/2skip/실패0(479.919초).
skip은 기존 로컬 v6 설계 문서 fixture 부재이며 테스트 실패를 skip으로 바꾼 것이 아니다.
이 체크포인트는 아래 저널 구현을 시작하기 전 버전이다.

execution_journal은 기존 불변 artifacts/builds에 시작/종료를 별개 artifact로 저장한다.
요청/결과 JSON bytes는 원문으로 보존하고 실행/단계 ID·manifest/파일 SHA·시작 참조·입력
해시·worker_finished/자원 상태를 기록 읽기에서도 검증한다. 종료 미확인 자원은 completed/
cancelled로 게시할 수 없다. 시작만 있으면 nonterminal_checkpoint와 worker_finished=unknown을
반환하고 PID 제어/자동 재실행을 수행하지 않는다. 완료 결과와 미확인 부분 결과의 eligible을
구분하며 원래 JSON 문자열의 지수 표기/큰 정수·unknown 필드도 보존한다.

open_immutable_build는 명시된 로컬 artifact ID의 manifest를 발견한 뒤 전체 묶음을 검증한다.
호출자가 보관한 원래 manifest SHA와 일치한다고 주장하는 API는 아니며, 원래 SHA가 있으면
기존 read_immutable_build를 쓴다. 종료→시작 참조 연결은 원래 저장된 SHA로 다시 검증한다.
execution-checkpoint kind는 기존 빌드 목록에서 제외했다.

증거: execution-journal-v2.xml 관련53개 중52통과/기존 v6문서1skip.
실제 파일 저장/회수·멱등 재게시·원문 JSON·비종료/부분 상태·활성 자원 거짓 완료 거절,
결과 변조/잘못된 시작 연결·누락 참조·빌드 목록 분리를 검사했다. 관련3모듈 mypy/Ruff 통과.
아직 RequestManager/MCP에 연결하거나 실제 서버 재기동으로 회수한 것은 아니다.
다음은 그 연결과 시작 저장 실패/종료 게시 실패·재기동 회귀다. R3 전체·배포 검증은 남아 있다.

### RequestManager/MCP 영속 연결과 실제 재기동 — 2026-11-01

Production RequestManager는 persist=True이며 일반 MCP 도구의 시작 전에 명시 입력 JSON과
scope 상태를 불변 체크포인트로 저장한다. 저장 실패는 실제 operation을 호출하지 않는다.
작업/자원 정리 종료 후 별도 종료 체크포인트를 게시하고 결과는 실행 참조 메타데이터를
포함한 CallToolResult JSON으로 보존한다. 직접 Python API의 임의 객체는 serializer 없이
자동 영속화하지 않으며 명시 입력/encoder가 필요하다.

종료 게시 실패는 이미 끝난 작업을 미완료 계산으로 꾸미지 않는다. 실제 live state/result를
유지하면서 persistence.error를 남기고 응답은 durable checkpoint 실패를 알린다. 시작 증거는
덮어쓰지 않는다. 서버 재기동 뒤 terminal이 없으면 그 작업이 끝났는지 추정하지 않는다.
get_execution_status/read_execution_result는 현재 서버 live 상태, recover_execution은
예전 서버를 포함한 저장 증거 회수다. recover는 자동 replay/현재 빌드 채택/PID 종료를 하지 않는다.
상세 capability와 inline summary에 recovery_tool을 추가했다.

증거: execution-persistence-v1.xml 관리자 교체/시작 저장 실패/종료 게시 실패 및 기존
감독21검사 통과. execution-persistence-mcp-v2.xml 기존 응답/식별/설계 서비스 포함57검사 통과.
execution-recovery-native-v3.xml 실제 stdio 서버 재기동 뒤 정확한 wire 결과 회수/작업 미재실행,
실행 도중 os._exit로 서버 종료 뒤 시작 기록만 회수하고 unknown 보존, 실제 PoB 취소 기록의
새 관리자 회수3검사 통과. 과거 서버 참조로 현재 서버 cancel을 시도하면 거절되는 것도 확인했다.
관련 Ruff/mypy 및 통합 가드 통과. 이 후속을 이전 전량 단위2450개 실행에 소급하지 않는다.

이는 저장한 증거의 무결성/회수 계약이다. 파일시스템 전원 손실 내구성 전체나 과거 프로세스
실제 생존 상태를 인증하지 않는다. POSIX 실제 검증·R3 종합 감사/비용/원문 편집 범위 등
전체 요구 대조와 전량 통합, UI/R4~R7은 아직 남아 있다.

### R3 감사에서 보강한 XML 잎 텍스트 — 2026-11-01

속성 편집만으로는 Item 본문의 장비 원문을 바꿀 수 없는 누락을 확인해 set_text를 추가했다.
inspect_pob_document는 leaf의 raw_text를 제공하고 명시 expected_raw_value와 대조한다.
태그/속성/주석/다른 데이터는 편집 span 밖에서 그대로 유지한다. 단일 CDATA 표현과 ]]>를
안전하게 처리하고, mixed element/comment/PI를 조용히 삭제하지 않고 거절한다.
속성+텍스트를 같은 원자 batch에 넣을 수 있고 중간 충돌이면 새 문서를 게시하지 않는다.

증거: pob-leaf-text-edit-v2.xml 관련56검사 통과.
pob-bundle-text-edit-native-v1.xml 실제 장비 원문·연결 패시브·젬 변경1검사 통과.
Life 변화·실제 노드 할당·원본 XML bytes 보존과 원본 재계산 복구를 확인했다.
관련 mypy/Ruff와 통합 가드 통과. measure_document의 낡은 deadline 표시도 실제 bound
request scope 여부와 native-only 직접 호출로 구분했다.
현재 감사 표는 POK_R3_AUDIT.md이며 남은 비용/예산/플랫폼/전량 검증을 명시한다.

### R3 고정 비용 목표 실측과 교정 — 2026-11-01

계약 §12의100결정/500근거·1MiB 이하·7회·따뜻한 중앙값1초 목표를 고정 입력으로 측정했다.
입력185300바이트/SHA7fdbbbbd9875cd07d58f2481d1bb302fc8c6951f4eac55713b1d16fb7a6538ed.
파싱→봉인→공급자 변경/100개 의존 전파→렌더를 포함한다. v1 중앙값1.373초는 목표 미달이었다.
프로파일에서 반복 schema 검증이 지배적이어서 성공한 정확한 내용/스키마 조합을 최대128개
재사용했다. mutable record나 제공 revision을 캐시 정본으로 삼지 않으며 validator 교체와
스키마/내용 변경을 구분하고 revision 무결성 검사는 독립적으로 수행한다.
같은 입력 v2는 최초0.631초, 따뜻한7회 중앙값0.139초로1초 목표를 충족했다.
artifacts/reviews/r3-fixed-cost-benchmark-v1/ 및 v2/result.json과 v2/source-manifest.json에 보존했다.
첫 스크립트의 보고서 직렬화에서 tuple 변환 오류가 있었고 측정 알고리즘/입력은 유지한 채
보고 변환만 고쳐 다시 측정했다. 최초 미달/프로파일을 삭제하지 않았다.

실제 MCP 기본 응답은 처음761바이트였지만 stored notice뿐이라 변경/재검토 정보를 숨겼다.
change_summary와 상세 참조를 보존하도록 교정한 v2 응답은1883바이트로8KiB 목표를 충족했고
changed1/review100/diagnostics0 및 game_feasibility=not_checked를 유지했다.
상세443227바이트는 해시 참조로 손실 없이 회수했다. 실제 저장/근거 검사/저널을 포함한
MCP 호출1.025초는 순수 커널 시간과 별도로 기록했다. 자료는 r3-summary-cost-benchmark-v1/
및 v2/result.json이다. 일반 빌드 품질이나 R5 개선 효과의 증거로 쓰지 않는다.
검증: design-validation-memo-v1.xml 관련118검사, r3-cost-summary-regression-v1.xml 관련119검사,
후속 v2.xml 13검사 통과. 변조/중복/사용자 고정·실제 요약/상세 보존을 확인했고 Ruff/mypy 통과.
R3 남은 예산/플랫폼/전량 검증은 아직 완료하지 않았다.

### 예산 프로필과 실제 POSIX helper 검증 — 2026-11-01

계약 §12에 맞춰 MCP 단일 계산(compute_pob/compute_pob_document)의 기본/최대180초,
선택 탐색5도구의 기본300초·최대1200초, 나머지 generic600초 프로필을 구분했다.
명시한 time_budget_s와 caller metadata timeout_s가 함께 있으면 더 짧은 값을 사용한다.
None으로 내부 상한을 해제해도 outer request 기본 기한은 남는다. optimize_tree의 기존
기본600초도300초로 맞췄다. capability는 generic 기본과 도구별 profiles를 구분한다.
execution-budget-profiles-v1.xml 관련26검사 통과: 실제 MCP에서1200초 탐색 허용,
단일 계산181초는 operation 실행 전 거절, 짧은 caller 기한 및 NaN/무한/잘못된 값 거절.

기존 WSL Ubuntu를 읽기 전용 확인한 뒤 Python3.12.3에서 실제 POSIX helper를 실행했다.
원래 소스/OS 패키지를 설치하거나 바꾸지 않았다. posix-owned-containment-v2/result.json:
자식/손자 모두 root PGID 소속 확인→group 정리 confirmed(0.00136초)→/proc에서 두 자식 부재,
다른 소유자의 process는 계속 살아 있음을 확인했다. 마지막 다른 소유자도 확인 정리했다.
이는 실제 Linux 검증이며 macOS 또는 Linux PoB 계산 검증이 아니다. 기존 한계인 deliberate
process-group escape는 막지 않으며, source v1 실험은 인용 오류로 프로그램 실행 전 실패해 보존했다.
최초 WSL 조회의 sandbox 접근 제한은 승인된 읽기 경로로 재확인했고 실제 배포판 Ubuntu가 있었다.

최근 변경 후 전체 단위 redesign-r3-unit-full-v4.xml을 시작했다. 아직 종료 결과는 미확인이다.
macOS 실제/CI·PR 직전 전체 통합과 R3 출구 재감사는 남아 있다.

### macOS CI 경로 사전 감사 — 2026-11-01 (구현 변경 전)

기존 CI는 Windows/macOS에서 pytest tests를 실행하지만 catalog용 PoB 일부 파일만 받고
HeadlessWrapper/LuaJIT는 의도적으로 준비하지 않는다. 따라서 native 테스트의 수집/skip은
확인하되 새 계산·소유 작업·재시작 경로의 실제 macOS 실행 증거는 아니다.
pob-smoke workflow는 두 OS의 LuaJIT/전체 PoB를 준비하지만 기존 pob_smoke.lua만 실행한다.
이 역시 새 Python adapter/실행 복구 테스트 전체를 대신하지 않는다.

다음 전량 단위 종료 뒤 native CI에 실제 adapter/수명/복구 테스트를 연결해야 한다.
현재는 로컬 Windows native와 WSL Linux helper 증거만 있으며 macOS 실제 검증을 완료로
보고하지 않는다. 원격 실행은 검사할 소스가 브랜치에 게시된 뒤 그 commit으로 확인해야 한다.

### 전량 단위 v4와 native CI 보강 — 2026-11-01

redesign-r3-unit-full-v4.xml:2486개 중2484통과/기존 문서 fixture2skip/실패0(524.030초).
이후 발견한 테스트 assert 서식1건을 교정했고 ruff check 전체·428파일 format check,
mypy175소스 및 import-linter175파일/514의존·계약 kept/0 broken을 확인했다.

pob-smoke workflow가 Python3.12/dev 의존성과 canonical external/pob/<pin> 전체 clone을
준비하고 tests/integration 및 test_owned_process를 Windows/macOS에서 실행하도록 보강했다.
Windows는 MSYS2 LuaJIT 경로를 POK_LUAJIT로 전달한다. 캐시는 OS/새 경로 namespace로
분리하고 JUnit을 항상 보존한다. 기존 Lua spike만으로 새 adapter 통과를 주장하지 않는다.
관련 native-ci-coverage-v1.xml 10검사·YAML 구조 파싱·pin/기존 CI 검사 통과.
아직 변경 소스의 원격 commit/CI 실행 결과는 없으며 macOS 통과로 표시하지 않는다.

현재 로컬 전체 통합 redesign-r3-integration-full-v1.xml을 시작했다. 아직 종료 결과는
미확인이고 검사 중 구현을 유지한다. 통합 결과와 원격 native matrix를 확인한 뒤 R3
출구를 다시 대조하며 R4~R7 전체 완료를 미리 선언하지 않는다.

R5 동결 참조 보강: 개선 제품7875ea2는 r5-improved-freeze-v2/manifest.json의1292파일/공통
KB697/외부25087 검증과 source.zip SHA3054a475e15e5f397a828c16f37fa4fb726d4b0d1c8c50be82da5a143d1dd1be로 고정했다.
KB4파일은 기준판과 동일한 실제 바이트를 위한 검증된 줄바꿈 overlay로 명시한다.
원래 heldout manifest0149922a...는 자기 manifest_sha256 필드를 제외한 canonical JSON
해시이며 원문 파일 해시4742edb5...와 구분한다.9개 원문 해시/바이너리를 모두 재확인했다.
제품/공통 수집기 버전을 분리하고 후자는 캠페인 시행 전에 추가 고정한다. 본 모델 평가는 미실행이다.
