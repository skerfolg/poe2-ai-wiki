# trade2 파라미터와 출처

이 파일은 검색 JSON을 구성할 때 읽는다. 옵션 목록 전체를 정본으로 복제하지 않는다.
현재 ID와 표기는 해당 호스트의 공개 카탈로그를 조회한다.

## 위치가 의미다

| 조건 | JSON 위치 | 예 |
| --- | --- | --- |
| 거래 상태 | `query.status.option` | `any`, `available`, `securable`, `onlineleague`, `online` |
| 이름 | `query.name` | 아이템 고유명 또는 `{option, discriminator}` |
| 베이스 | `query.type` | 베이스명 또는 `{option, discriminator}` |
| 부위 | `query.filters.type_filters.filters.category.option` | `armour.boots` |
| 희귀도 | `query.filters.type_filters.filters.rarity.option` | `rare` |
| 아이템 레벨·품질 | `query.filters.type_filters.filters.ilvl` / `quality` | `{min: 80}` |
| 방어도·회피·ES | `query.filters.equipment_filters.filters.ar` / `ev` / `es` | `{min: 300}` |
| DPS·공격 속도 | `query.filters.equipment_filters.filters.dps` / `aps` | `{min: 2}` |
| 요구 능력치 | `query.filters.req_filters.filters.str` / `dex` / `int` | `{max: 100}` |
| 타락·감정 | `query.filters.misc_filters.filters.corrupted` / `identified` | `{option: "false"}` |
| 젬 레벨 | `query.filters.misc_filters.filters.gem_level` | `{min: 20}` |
| 가격 | `query.filters.trade_filters.filters.price` | `{max: 5, option: "divine"}` |
| 등록 시간 | `query.filters.trade_filters.filters.indexed.option` | 카탈로그의 option ID |
| 같은 계정 매물 묶기 | `query.filters.trade_filters.filters.collapse.option` | `"true"` |
| 속성 | `query.stats[].filters[]` | `{id: "explicit.stat_3299347043", value: {min: 100}}` |
| 정렬 | `sort` | `{price: "asc"}` |

표 안의 짧은 객체는 설명용 표기다. 실제 파일에는 유효한 JSON을 쓴다.
필요 없는 필드는 생략한다. 0은 유효한 범위이므로 비어 있다고 지우지 않는다.
음수 범위도 의미가 있으므로 절댓값으로 바꾸지 않는다.

`filters` 응답의 `status_filters`는 UI의 분류다. 실제 본문에는
`query.filters.status_filters`가 아니라 **`query.status`**로 보낸다.
카탈로그의 `option.options`는 가능한 값 목록이고, 요청의 `option`에는 고른 값 하나만 넣는다.
카탈로그에서 `null`이 "Any"를 나타내면 조건 생략과 구별해 해석한다.

필터의 예/아니오는 문자열 `"true"`/`"false"`다. 반대로 조건의 `disabled`는 JSON boolean이다.
범위는 유한한 숫자로 쓰고 `min <= max`를 지킨다.

가격의 범위와 통화는 **같은 객체**에 둔다. 2026-10-05 공개 filters 응답에서
가격 option `null`의 표시는 `Exalted Orb Equivalent`였다. 통화를 생략한 가격 검색을
"아무 통화로 5 이하"라고 해석하면 안 된다. 지정된 예산은 통화 ID를 반드시 함께 보낸다.

## 그룹 논리

`query.stats`는 그룹의 배열이다. 그룹 하나로 평탄화하면 의미가 사라진다.

```json
{
  "type": "count",
  "value": {"min": 2},
  "filters": [
    {"id": "pseudo.pseudo_total_fire_resistance", "value": {"min": 30}},
    {"id": "pseudo.pseudo_total_cold_resistance", "value": {"min": 30}},
    {"id": "pseudo.pseudo_total_lightning_resistance", "value": {"min": 30}}
  ]
}
```

이 그룹은 합산 화염·냉기·번개 저항 중 30 이상인 것이 최소 둘이라는 조건이다.
별도 `and` 그룹에 필수 생명력·이동속도를 둘 수 있다.
`and`는 전부 충족, `count`의 `min:1`은 후보 중 최소 하나, `not`은 제외 조건에 사용한다.
`if` 같은 추가 그룹의 세부 동작을 확인하지 못했다면 사용자 원문을 보존하고 임의로
다른 논리로 번역하지 않는다. 그룹과 개별 조건에 있는 `disabled`도 보존한다.
가중합·음수 가중치 등 복잡한 원형 입력을 간편 AND 표현으로 축소하지 않는다.

예제의 속성 ID·문구는 2026-10-05 공개 stats에서 확인했다. 이것은 최신성을
영구 보장하는 목록이 아니므로 새 검색에서는 카탈로그를 사용한다.

## 전송 계약

```text
GET  {host}/api/trade2/data/{stats|items|static|filters|leagues}
POST {host}/api/trade2/search/poe2/{league}
     body = {query: {...}, sort: {...}}
     response = {id, result: [listing IDs], total, inexact?}
GET  {host}/api/trade2/fetch/{comma-separated IDs}?query={search id}&realm=poe2
     response = {result: [listing or null, ...]}
```

realm은 search에서는 경로, fetch에서는 쿼리 변수다. 이 스킬은 `poe2`만 지원한다.
리그·검색 ID는 URL 인코딩하며, 서버 검색 ID는 불투명한 값으로 취급한다.
fetch 10개는 이 실행기의 호출당 상한이다. 서버의 최대 허용량이라고 단정하지 않는다.
상세의 `null`/누락은 사라진 매물일 수 있고 검색 당시의 total을 0으로 바꾸는 근거가 아니다.

준비용 URL은 overlay의 관측에 따라 다음 형태다.

```text
{host}/trade2/search/poe2/{league}/{base64url(gzip(query 객체만))}
```

POST 본문 전체나 `sort`를 압축하지 않는다. 실제 검색이 성공하면 반환받은 ID로 링크를 낸다.
검색 결과에서 `hideout_token`·whisper 등 거래 동작용 필드는 반환 대상에서 제외한다.

## 제한과 오류

[GGG 제한 헤더 문서](https://www.pathofexile.com/developer/docs#ratelimits)를 참고한다.
`X-Rate-Limit-Policy`로 정책을 구분하고 `X-Rate-Limit-Rules`가 열거한 각 규칙을 읽는다.
`X-Rate-Limit-{rule}`은 `최대횟수:기간초:초과제한초`, `...-State`는
`현재횟수:기간초:현재제한초`다. 모든 기간을 함께 적용한다. 상태가 없으면 사용량은 미상이다.
같은 정책을 보고한 엔드포인트는 상태를 공유한다. 수치를 고정 정책처럼 복사하지 않는다.
`Retry-After`가 있으면 그보다 이른 재시도를 하지 않는다. 제한에서 자동으로 재시도하지 않는다.

HTTP 오류·HTML 접근 확인 화면·JSON 스키마 변경을 매물 없음으로 처리하지 않는다.
이 경로들은 거래소 웹사이트의 계약을 사용한다. 공개 개발자 API 전체와 동일한 안정성이나
공식 지원을 주장하지 않는다.

## 참고·검증 범위

참고 저장소 `poe2-overlay`, 읽기 전용 조사:

- `.claude/skills/trade2-search/SKILL.md`: search → fetch 절차.
- `docs/research/trade2-api-2026-09-14.md` §2~4·§6·§8: 본문, 카탈로그, fetch, 제한.
- `src-tauri/src/market/trade2/query.rs`: query만 gzip/base64url로 접기, 빈 AND 그룹.
- `src-tauri/src/market/trade2/stats.rs`: 호스트별 카탈로그, 원문·ID 검색.

이 파일과 실행기는 형제 저장소가 없는 환경에서도 동작한다. 그 저장소의 WebSocket·이동
요청·원문 매물 샘플 저장은 가져오지 않았다.

2026-10-05 직접 확인한 것:

- 글로벌의 stats/items/static/filters/leagues와 카카오 stats: 무인증 GET 200, JSON 구조 확인.
- filters 상태 ID 5종: `available`=즉시구매+대면, `securable`=즉시구매,
  `onlineleague`=같은 리그 접속 중 대면, `online`=접속 중 대면, `any`=전체.
- 글로벌 Standard의 `Time-Lost Diamond`, 상태 any: 무인증 POST search 200,
  `id/result/total`과 검색 제한 헤더 확인. 인증이 항상 필요하다는 옛 가정은 적용하지 않는다.
- 포함된 희귀 신발 합산 조건 예제: 실행기에서 search → fetch 3건 성공,
  입력 본문 보존·상세 반환·거래 동작용 토큰 미반환 확인.
- 카카오 금단의 의식: 투사체 레벨 +2·ES 250 이상·전체 홈 2개 장갑의 무인증 검색과
  상세 10건 성공. `explicitMods`는 문자열뿐 아니라 `description/domain/hash/mods` 객체도
  반환하므로 두 형식을 보존한다. 분열·훼손 문구도 이 배열의 `domain`으로 구별될 수 있다.

계정·호스트·서버 상태에 따라 인증과 접근 여부는 달라질 수 있다. 로그인 검색이나
모든 파라미터 조합까지 검증했다는 뜻은 아니다.
