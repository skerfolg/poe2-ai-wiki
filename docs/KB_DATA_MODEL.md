# PoE2 AI Wiki — KB 데이터 모델 (KB Data Model)

> **문서 상태**: v0.2 (2026-08-03) — §9에 **쓰기 계약** 명문화(B-6, 정본 레코드 쓰기 단일 경로). v0.1 (2026-07-29) 확정 초안. BLUEPRINT §7(KB)·§5(증거 위계)·§17(실패 교훈)의 상세 스키마.
> **관계**: [BLUEPRINT.md](BLUEPRINT.md) = 방향·결정의 단일 진실 / [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) = 물리 구조 / **이 문서 = KB 레코드의 형태와 규칙**.
> **변경 규칙**: 스키마 변경은 `knowledge/schema/` 버전 갱신 + 이 문서 갱신을 동반한다. 모델의 *구조적* 변경(엔티티/관계 추가·삭제, 포맷 전략 변경)은 사용자 상호협의 후에만.

---

## 0. 이 세션에서 확정된 결정 (KD = KB Decision)

| # | 항목 | 결정 |
|---|---|---|
| KD-1 | 파일 배치 | **혼합**: 큐레이션 엔티티 = 개별 JSON 1파일 / 벌크 카탈로그 = 타입별 NDJSON 샤드 |
| KD-2 | 조건 표현 | **처음부터 완전 구조화** — 모든 condition에 `expr` 필수 (텍스트만 금지) |
| KD-3 | 스키마 위치 | **`knowledge/schema/` 에 정본 커밋** (JSON Schema) + 로드 시·CI 검증. 스키마 버전 = 인덱스 self-healing 트리거 |
| KD-4 | 성능 근거 | 검색 성능은 파일 배치와 무관(검색은 항상 `var/index.sqlite`). 배치는 재빌드·git 연산에만 영향 → 벌크=NDJSON으로 해소 |
| KD-5 | **정본 진입 자격** | KB는 **에이전트가 추론할 수 없는 것만** 담는다 (§6-1) — 텍스트로 유도 가능·파생·수집 대상·맥락 판단은 진입 불가. 추론 가능한 것을 담으면 사례집이 되고 에이전트가 생각하지 않는다 (사용자 확립 2026-08-04) |

---

## 1. ID 체계

```
<type-prefix>.<slug>
skill.spark · support.pierce · passive.heart-of-ice · ascendancy.stormweaver
item.astramentis · modifier.fire-damage-pct · content.pinnacle-boss · build.spark-stormweaver-ref
```

- 안정적·사람이 읽을 수 있는 **영문 슬러그**. 게임 내 리네임에도 id 불변(이름은 필드).
- 관계 참조·검색 히트·MCP 응답·에이전트 대화 모두 이 id 사용.
- 타입 접두사는 §2 엔티티와 1:1.

## 2. 엔티티 (BLUEPRINT §7, 12종)

`Skill · Support · Passive · Ascendancy · Item · Modifier · Event · Resource · Mechanic · Defence · Content · Build`

- **Mechanic** *(2026-08-02 신설, 사용자 승인)* — 특정 엔티티에 귀속되지 않는 **게임 작동
  규칙·공식·한도**: 점유 효율 공식(`mechanic.reservation`), 전직 포인트 예산
  (`mechanic.ascendancy-points`), 보조 젬 슬롯 한도(`mechanic.support-gem-slots`) 등.
  Resource(생명력·마나·정신력 같은 실제 자원)와 구분 — v6 일반화(태스크 #35)에서
  Resource로 임시 수록했던 것을 분리했다.

각 엔티티의 타입별 `data` 필드 구조는 `knowledge/schema/<type>.schema.json`에 정의한다(공통 envelope는 `record.schema.json`).

### 2-0. Build — 시즌 메타를 8축으로 원자화 (#67, 사용자 승인 2026-08-11)

`Build`는 12종에 정의만 돼 있고 데이터가 0건이었다. 시즌별 메타를 쌓아 **신규 빌드
설계의 문법 기반**으로 쓴다. 스키마는 `knowledge/schema/build.schema.json`.

- **8축**: 공격 ①담체 ②스택 원천 ③**전달 장치**(스택→딜 다리) ④증폭 통(more/increased/gain
  분리) ⑤클리어 엔진 ⑥순환 고리 / 방어 ⑦EHP 형태·경감·회복·캡면역·**포기한 약점** /
  ⑧**공수 결합**(4종 enum).
- **KD-5 적합성**: 레코드 목록이 아니라 **「어느 축을 어떻게 엮었나」**만 담고 원자는 전부
  id 참조다. 조합 구조는 어느 레코드 문구로도 유도되지 않는다.
- **배치**: `knowledge/game-data/builds/<season>/<slug>.json` (KD-1 큐레이션).
  ⚠ `knowledge/builds/`가 **아니다** — 거기는 `promote.py`로 **승격된 것만** 들어오는
  자리이고, 무엇보다 `store.load()`가 `game-data/`만 스캔해 그 밖의 레코드는 **도구에
  보이지 않는다**(역방향 조회라는 목적 자체가 무산된다).
- **`uses` 관계**(어휘 14종째): 「빌드가 이 스킬·아이템을 쓴다」. 이게 있어야
  `related(skill.…)`로 **「이 스킬을 쓰는 메타 빌드는?」**이 역방향으로 나온다 —
  이 엔티티의 핵심 가치다. 실측: `related("skill.ghost-dance")` → 빌드 4건.
- **`COMMUNITY` 라벨**: 커뮤니티 가이드에서 **실플레이가 관찰된** 것. `IN_GAME`(우리가
  확인)과 `UNVERIFIED`(아무도 안 돌려본 추측) 사이의 빈 칸이었다. 사용자 인게임 확인 시
  `IN_GAME` 승격.

### 2-1. Skill·Support `data.pob` — PoB 구조화 사실 (#63 P1, 2026-08-11)

담체 판정·모드 선택은 **어느 레코드 문구에도 없고** PoB 데이터에만 있어, 엔진이
런타임에 gitignore된 파생물(`external/pob`)을 직독하는 결함이 있었다(철칙 2 위반).
`kb/ingest/skill_types.py`가 `Data/Skills/*.lua`를 수집해 레코드에 넣는다 —
스키마는 `knowledge/schema/pob-gate.schema.json`.

```jsonc
"data": { "pob": {
  "gem_id": "Metadata/Items/Gems/SkillGemMetaSpellTotem",  // 젬이면 — PoB 정본 id
  "effects": [                       // 메타 젬은 반쪽이 둘: 소환 스킬 + 보조 판정 스킬
    { "id": "SummonMetaTotemSpellTotemPlayer",             // grantedEffectId
      "types": ["Meta", "SummonsTotem", "..."],            // skillTypes (정렬)
      "stat_sets": ["Spell Totem"] },                      // 모드 라벨, 1번부터 순서대로 (#52)
    { "id": "SupportMetaTotemSpellTotemPlayer",
      "support": true,
      "require": ["Spell", "Totemable", "AND"],  // ⚠ 후위(RPN) 식 — 순서가 의미, 정렬 금지
      "exclude": ["Meta", "..."],
      "adds": ["UsedByTotem", "..."],            // 이 보조가 페이로드에 더하는 타입
      "ignore_minion_types": true }              // 요구 판정에서 소환수 타입 무시
  ]
} }
```

- 거짓 플래그·빈 배열은 **생략**한다(938건 지면 비용). `from_item`(아이템 부여라 젬
  소켓 불가)·`cannot_be_supported`·`support_gems_only`도 같은 규약.
- KD-5 적합성: 후위 식 평가·타입 축은 텍스트로 유도할 수 없다(주문 토템에 무엇이
  들어가는지는 어느 문구에도 없다 — #62 실증). 소비처는 `engine/hosting.py`·statSet 게이트.
- 출처: `sources[]`에 `{"src":"pob", "ref":"Data/Skills (…)", "pob":"<commit>"}` 필수.

## 3. 레코드 공통 envelope

```jsonc
{
  "id": "skill.spark",
  "type": "Skill",
  "name": { "ko": "스파크", "en": "Spark" },     // ko 우선, en 필수(소스 대조·중복 검출용)
  "tags": ["lightning", "projectile", "spell"],  // 게임 공식 태그만 (D11, poe2db 기준)
  "data": { /* 타입별 구조 필드 — <type>.schema.json */ },
  "conditions": [ /* §5 — 1급 필드 */ ],
  "relations": [ /* §4 — typed edges */ ],
  "facets": { /* 비공식 구조 필드 (D11): 용도·역할·티어 등. 태그와 절대 혼합 금지 */ },
  "verification": "GAME_DATA",                   // §6 라벨
  "sources": [ /* §7 — source ledger */ ],
  "notes": "짧은 큐레이터 노트 (선택)"
}
```

- **검증 라벨**: 레코드 단위 기본 + 필드 단위 오버라이드(`data._verification.<field>`), 미지정 필드는 레코드 라벨 상속.
- **서술 분리**: 위키 서술은 레코드에 넣지 않는다 → `knowledge/wiki/<type>/<slug>.md` (front-matter `id:`로 연결, 자체 재작성 D10).

## 4. 관계 — typed edge (RC2 대응)

```jsonc
"relations": [
  { "rel": "scales_with", "target": "modifier.lightning-damage-pct" },
  { "rel": "triggers", "target": "skill.shock-nova",
    "condition": { /* §5의 condition 객체, 인라인 */ } },
  { "rel": "conflicts_with", "target": "support.pierce", "note": "포크와 배타" }
]
```

- `rel`은 **닫힌 enum 13종**(BLUEPRINT §7): `triggers · enables · scales_with · consumes · recovers · converts · reserves · conflicts_with · mitigates · requires · replaces · overlaps · invalidated_by`. 자유 문자열 금지 — 시너지는 키워드가 아니라 기계적 관계 경로로만 판단(RC2).
- **정본에는 정방향만** 저장(소스 레코드 안). 역방향 조회("이 모드를 스케일하는 스킬들")는 **인덱스가 자동 생성** — 정본 중복·불일치 원천 차단.
- 엣지 선택 속성: `condition`(발동 조건) · `magnitude`(정량 근거) · `note`.
- enum 확장은 스키마 변경(§0 변경 규칙 적용).

## 5. 조건(condition) — 1급 필드, 완전 구조화 (KD-2, RC1 대응)

```jsonc
{
  "id": "cond.on-full-mana",
  "text": "마나가 가득 찼을 때",                       // 사람용 서술 — 항상 필수
  "expr": {                                          // 기계용 — KD-2에 따라 항상 필수
    "subject": "self.mana", "op": "==", "value": "max"
  },
  "satisfiable_by": ["passive.mind-over-matter"],     // 만족 수단 (id 참조, 없으면 [])
  "uptime": "conditional"                             // always | sustained | conditional | burst
}
```

### 5.1 조건 표현 언어 (expr)

```
expr      := predicate | { "all": [expr, …] } | { "any": [expr, …] } | { "not": expr }
predicate := { "subject": <vocab>, "op": <op>, "value": <scalar|enum> }
op        := "==" | "!=" | "<" | "<=" | ">" | ">=" | "has" | "in"
```

- **subject 어휘는 통제된 vocab**: `knowledge/schema/vocab/condition-subjects.json` 에 네임스페이스로 정의 —
  `self.*`(자원·상태: mana, life, es, spirit, rage, leeching, on-full-life…) · `enemy.*`(shocked, ignited, low-life…) · `event.*`(on-crit, on-kill, on-block…) · `gear.*`(장비 상태) · `env.*`(콘텐츠 상황).
- **어휘에 없는 조건 = 스키마(vocab) 확장으로 처리**(통제된 진화, §0 변경 규칙). 임의 문자열로 우회 금지.
- 생성 시 엔진은 `expr`·`satisfiable_by`·`uptime`으로 **만족 가능성을 검증**한다. 불가능 조건의 발동 가정(RC1의 핵심 실패)은 조립 단계에서 거부된다.
- ⚠️ **선행 과제**: vocab 초판 설계는 KB ingest 시작 전에 완료해야 한다(§9).

## 6. 검증 라벨 (BLUEPRINT §5)

`CONFIRMED_OFFICIAL · GAME_DATA · POB_CODE · IN_GAME · SUPPORTED_INFERENCE · UNVERIFIED · CONTRADICTED`

- 증거 위계: ① GGG 공식 → ② 게임데이터/poe2db → ③ PoB 코드 → ④ wiki → ⑤ 커뮤니티(단독 근거 ❌).
- `CONTRADICTED` 레코드는 검색에서 경고 플래그와 함께 노출(숨기지 않음 — 에이전트가 함정을 알아야 함).

## 6-1. 정본 진입 자격 (KD-5, 사용자 확립 2026-08-04)

> **KB는 에이전트가 추론할 수 없는 것만 담는다.** 추론 가능한 것을 담기 시작하면
> 사례집이 되고, 빌드마다 5~10건씩 쌓여 **끝이 없다**.

### 들어갈 자격 — "텍스트를 읽어도 알 수 없는 것"

- **함정 표기** — 텍스트와 실제가 다르다. *예: 룬 수호 결속 옵션은 드루이드 샤먼
  전용인데 다른 직업에도 텍스트가 보인다.*
- **인게임에서만 드러나는 상호작용** — 어떤 데이터에도 없다. *예: CoMD가 트리거한
  스킬은 다른 메타 젬의 에너지를 생성하지 않는다.*
- **실패에서만 얻어지는 차단 경로** — 시도해 봐야 안다. *예: 한 스킬에 여러 트리거를
  링크하면 비활성화된다.*
- 수집으로 들어온 **게임 데이터·상수·공식** (ingest의 몫)

### 들어가지 못하는 것 — 그리고 그건 어디로 가는가

| 성격 | 예 | 행선지 |
|---|---|---|
| 텍스트를 읽으면 아는 것 | "눈알 왕관 전이는 1:1" — 아이템 텍스트가 *적용된다*고 말한다 | **에이전트 추론** |
| 이미 있는 데이터의 조합(파생) | "순수 ES 장갑은 지능 101 요구" — 베이스 `requires`에서 계산된다 | **에이전트 추론** |
| 공개 데이터인데 수집이 안 된 것 | 출혈 스케일 규칙 · Monster Power 상수 | **ingest** |
| 특정 빌드 맥락의 판단 | "이 빌드는 그 장갑을 못 쓴다" | **에이전트 판단** |
| 조회가 불편해서 생긴 갭 | 어센던시 노드 열거가 안 된다 | **도구** |

### 왜 이 경계인가

셋을 혼동하면 각각이 망가진다:

- KB에 파생물을 넣으면 **원본과 어긋날 때 어느 쪽이 진실인지 알 수 없다**(철칙 2).
- 추론 가능한 것을 넣으면 에이전트가 **조회에만 의존하고 생각하지 않는다** — 그러면
  이 프로젝트는 능동 생성 도구가 아니라 *"주어진 정보 안에서 계산하는 계산기"*가 된다.
- 수집 가능한 것을 인사이트로 우회하면 **파이프라인이 고쳐지지 않는다**.

**AD-8("추측 금지, PoB로 측정")은 추론 금지가 아니다.** 효율·수치를 어림하지 말라는
것이지, 텍스트를 읽고 규칙을 유도하지 말라는 뜻이 아니다. 유도한 뒤 PoB로 검증하는
것이 정상 절차다.

### 승격 심사 시 물을 것

1. 이걸 **텍스트·수집 데이터에서 유도할 수 있는가?** → 그렇다면 진입 불가.
2. 이미 KB에 **원본이 있는가?** → 그렇다면 파생물이다.
3. **다음 빌드에서 재사용되는가?** → 이 빌드에서만 쓰이면 설계 문서에 남긴다.
4. 조회가 안 돼서 불편했을 뿐인가? → **도구 백로그**로 보낸다.

---

## 7. source ledger

```jsonc
"sources": [
  { "src": "poe2db",   "ref": "<url|데이터 경로>", "patch": "0.5.0" },
  { "src": "pob",      "ref": "<PoB 데이터 경로>", "patch": "0.5.0", "pob": "<commit>" },
  { "src": "poewiki",  "ref": "<url>",            "patch": "0.5.0", "note": "서술 재작성 근거" },
  { "src": "patchnote","ref": "<url>",            "patch": "0.5.0" }
]
```

- `src` enum: `poe2db · pob · poewiki · patchnote · community · in-game`.
- 충돌 우선순위(D8): 기본/카탈로그=poe2db · 파생계산=PoB · 서술=wiki.

## 8. 파일 배치 (KD-1: 혼합)

```
knowledge/
├── schema/                          # ★ 정본 스키마 (KD-3)
│   ├── record.schema.json           #   공통 envelope
│   ├── <type>.schema.json           #   타입별 data 구조 (skill, support, …)
│   ├── condition.schema.json        #   §5 조건 언어
│   └── vocab/
│       ├── condition-subjects.json  #   조건 subject 어휘 (통제)
│       ├── relations.json           #   관계 13종 enum
│       └── verification.json        #   라벨 enum
├── game-data/
│   ├── skills/<slug>.json           # ── 큐레이션 = 개별 JSON ──
│   ├── supports/<slug>.json
│   ├── ascendancies/<slug>.json
│   ├── uniques/<slug>.json          #   (Item 중 유니크)
│   ├── passives/<slug>.json         #   키스톤·노터블 (큐레이션 대상)
│   ├── mechanics/<slug>.json        #   작동 규칙·공식·한도 (Mechanic, 큐레이션)
│   ├── contents/<slug>.json
│   ├── modifiers/<shard>.ndjson     # ── 벌크 = NDJSON 샤드 ──
│   ├── base-items/<shard>.ndjson
│   └── passives-small/<shard>.ndjson  # 소형 패시브 노드
├── wiki/<type>/<slug>.md            # 서술 (front-matter id: 연결)
├── crafting-rules/*.json            # 모드풀·그룹배타·티어·ilvl (RC4 근거)
├── insights/                        # verified 인사이트 (승격만)
└── builds/<slug>.json               # reference Build 레코드 (승격만)
```

**혼합 기준**: *사람이 개별 리뷰·수정하는가?* — 예(수백 개 규모) → 개별 JSON / 아니오(기계 수집 수천~수만) → NDJSON. 경계가 애매한 신규 타입은 NDJSON으로 시작해 큐레이션 필요가 생기면 개별 파일로 승격(구조 변경 아님, 단 이 문서에 기록).

### 성능 근거 (KD-4, 질문에 대한 답 기록)

- **검색 속도·정확성은 파일 배치와 무관** — 검색은 항상 `var/index.sqlite`(FTS5)를 조회하며 정본 파일을 읽지 않는다(D12 분리의 목적).
- 배치가 영향 주는 것은 **인덱스 재빌드·ingest·git 연산**뿐. 수만 개별 파일은 Windows(주 플랫폼) 파일 I/O·git에서 불리 → 벌크를 NDJSON으로 해소. 큐레이션 개별 파일은 수백 규모라 오버헤드 무시 가능, 대신 diff/리뷰 품질 최상.

## 9. 정본 접근 계약 — 검증·쓰기 (KD-3)

### 9-1. 읽기·검증

- `kb/store.py`: 로드 시 스키마 검증(위반 = 로드 실패, 조용한 통과 금지).
- CI: `knowledge/` 전체 스키마 검증 (pre-commit + CI).
- `schema/`의 버전이 인덱스 `schema_version`과 연동 → 스키마 변경 시 인덱스 자동 재빌드(self-healing, PROJECT_STRUCTURE §5).

### 9-2. 쓰기 — **정본 레코드를 쓰는 경로는 `kb/store.py` 하나뿐** (B-6, 사용자 합의 2026-08-03)

쓰기 계약이 없던 시절엔 ingest 모듈들이 각자 `knowledge/`에 쓰면서 KD-1 배치 규칙
(개별 JSON이냐 NDJSON 샤드냐)을 매번 재추론했고, **한 곳만 빠뜨려도 샤드가 통째로
파괴**됐다(실측 2026-08-02 830건 · 2026-08-03 884건 손실). 배치 판단을 store에 가둔다.

배치 판별자는 `Record.in_shard`다 — `path`가 샤드일 때 **파일 전체**를 가리키므로,
레코드 하나를 그 경로에 덮어쓰면 샤드가 통째로 날아간다. 확장자 추론을 호출부마다
반복하는 대신 모델이 소유한다(AD-7 "구조적 결함은 구조에서").

| API | 용도 | 계약 |
|---|---|---|
| `write_shard(path, records, allow_delete=…)` | NDJSON 샤드 **전량** 재작성 | 기존에 있다가 빠진 레코드는 `allow_delete`에 id가 명시된 것만 삭제, 나머지는 **거부** |
| `write_record(path, record)` | 큐레이션 개별 JSON 1건 | 샤드 경로(`.ndjson`)를 넘기면 **거부** — 파일 전체가 한 줄로 덮이는 파괴 경로 차단 |
| `patch_records({id: data 패치})` | 후처리 필드 보강 | 레코드가 있는 파일을 자동으로 찾아 갱신 — **호출자는 배치 형태를 몰라도 된다**. 값이 `None`이면 키 삭제(재적용 멱등) |

모든 쓰기에 안전장치 3종이 강제된다: **① 쓰기 후 자동 재검증**(깨진 상태가 커밋으로
넘어가지 않는다) **② 근거 없는 레코드 감소 시 예외** **③ 원자적 쓰기**(중단돼도 기존
파일이 반토막 나지 않는다). 삭제 근거는 호출자가 원장(`knowledge/ingest/exclusions.json`)
에서 가져온다 — "데이터를 지우기 전에 후보를 나열해 사람이 판단한다"(사용자 확립 원칙).

**범위**: 정본 *레코드*에 한한다. 증거 manifest·제외 원장·수집 원문(wikitext) 같은
부속 파일은 레코드가 아니므로 각 모듈이 직접 쓴다.

## 10. 언블록 체인 & 선행 과제

```
이 문서 → ① condition vocab 초판 설계 (ingest 전 필수, KD-2의 대가)
        → ② <type>.schema.json 작성 (record envelope부터)
        → ③ ingest(poe2db 파서) 목표 포맷 확정
        → ④ index 설계 (FTS5 칼럼·태그 테이블·역방향 엣지 생성)
        → ⑤ search_kb/get_entry 응답 포맷 (D14 2단계)
```

미결(로드맵에서 배치): condition vocab 초판의 범위(초기 몇 개 네임스페이스로 시작할지) · 벌크 샤드 분할 기준(파일당 크기) · Event/Resource/Defence 등 저빈도 엔티티의 스키마 상세.
