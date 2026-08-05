# PoE2 AI Wiki — 프로젝트 구조 (Project Structure)

> **문서 상태**: v0.2 (2026-07-31) — 설계 루프 반영: `artifacts/builds/<id>/design.md` 추가 · `artifacts/anchors/` 신설 · `engine/constraints` 예정 (BLUEPRINT §10.0 / D26·D27·D30, 사용자 협의 2026-07-31). v0.1 (2026-07-28) 기반. BLUEPRINT §15-1 "프로젝트 구조" 결정의 상세.
> **관계**: [BLUEPRINT.md](BLUEPRINT.md)이 방향·결정(D1~D24)의 **단일 진실 소스**. 이 문서는 그 위의 **물리 구조 상세**다. 충돌 시 BLUEPRINT의 결정이 우선하되, 구조 표현은 이 문서를 따른다.
> **확정 시**: 미결(§9)이 모두 정리되면 BLUEPRINT를 v0.6으로 갱신하고 §15-1을 "확정"으로 이동한다.

---

## 0. 거버넌스 — 구조 변경 규칙 (최우선)

> ⛔ **프로젝트 구조(디렉터리 구성·모듈 경계·저장 위치·의존 방향)는 임의로 변경하지 않는다.**
> **모든 구조 변경은 반드시 사용자와 상호협의(합의) 후에만 진행한다.**

- 이는 프로토타입 실패의 핵심 교훈(BLUEPRINT §13, AD-7 "구조 먼저")에 대한 직접 대응이다.
- 적용 대상: 최상위 디렉터리 추가/삭제/이동, `src/pok/*` 모듈 경계 변경, 3계층(정본/산출물/파생) 저장 위치 변경, 의존 방향 규칙 변경, 패키지명 변경.
- Claude·Codex 모두 이 규칙을 따른다. 이 규칙은 루트 `AGENTS.md`(항상 로드)에도 요약되어 있다.
- 새 파일을 **기존 모듈 경계 안에** 추가하는 것은 구조 변경이 아니다(허용). 새 최상위 폴더·새 모듈·경계 이동은 구조 변경이다(합의 필요).

---

## 1. 설계 원칙 (구조를 강제하는 4개 축)

1. **지능 vs 결정성** (AD-3/D5) — `engine/`은 결정적 도구만. "무엇을 만들지" 판단은 `skills/` + 외부 에이전트.
2. **정본 vs 파생** (D12/AD-5) — git 정본(`knowledge/`)과 재생성 가능 파생물(`var/`)·재생성 불가 산출물(`artifacts/`)을 디렉터리째 분리.
3. **Python vs 비-Python** (AD-1/AD-2) — PoB(LuaJIT)는 `src/pok/pob/` + `external/pob/`에만 격리.
4. **의존 방향 단방향** — `mcp → engine → (kb·pob·live) → common`. 위로 되짚는 import 금지(import-linter로 강제).

---

## 2. 전체 디렉터리 구조

```
poe2-ai-wiki/
├── pyproject.toml                  # 단일 설치형 패키지 · Py3.12+ · ruff/mypy/pytest · import-linter (미생성)
├── .pre-commit-config.yaml         # (미생성)
├── .gitignore                      # artifacts/ · var/ · external/ 제외 (AGENTS.md는 negation으로 추적)
├── AGENTS.md                       # 루트 지침 지도(얇음, 항상 로드) — Codex 네이티브
├── CLAUDE.md                       # "@AGENTS.md" (Claude가 동일 내용 임포트)
├── README.md
├── docs/
│   ├── BLUEPRINT.md                # 단일 진실 소스 (방향·결정)
│   ├── PROJECT_STRUCTURE.md        # 이 문서 (구조 상세)
│   └── adr/                        # 개별 ADR 분화(선택)
│
├── src/pok/                       # ══ 코드 (단일 패키지 `pok` = Path of Knowledge) ══
│   ├── common/                    # 설정·크로스플랫폼 경로·로깅·타입·에러 (D21)
│   ├── i18n/                      # 한국어 우선 + 다국어 여지
│   ├── kb/                        # ★ 지식베이스 로직 = 판단 substrate (D9, §7)
│   │   ├── models/                #   엔티티 + 관계 데이터모델
│   │   ├── graph/                 #   관계 그래프 조회·순회
│   │   ├── ledger/                #   source ledger + 검증 라벨
│   │   ├── crafting/              #   제작규칙 = 합법성 근거 (RC4)
│   │   ├── ingest/                #   poe2db·poewiki·PoB → canonical 재작성 (패치 때만)
│   │   └── store.py               #   knowledge/ 정본 로드·검증 (예정)
│   ├── index/                    # 파생 검색 인덱스 빌더 (self-healing, §5)
│   ├── pob/                      # ★ PoB 오라클 = 유일 비-Python 경계 (AD-1/AD-2, §9)
│   ├── engine/                   # ★ 결정적 도구 상자 (지능 없음, AD-3)
│   │   ├── tree/                  #   트리 최적화 알고리즘 (Steiner + PoB실측, D23)
│   │   └── constraints/           #   설계 제약 검사기 — 포인트 예산·색상 장부·점유·자원 (D27, P4.5 구현 2026-07-31)
│   ├── live/                     # 라이브 데이터 fetch (→ var/live)
│   ├── cost/                     # 가격 추산 — 요청 시만 (D19)
│   ├── learning/                 # 피드백/인사이트 로직 — 큐레이션 게이트 (§10.4)
│   ├── artifacts/                # ★ 산출물 관리 (런타임↔정본 스테이징)
│   └── mcp/                      # ★ FastMCP 서버 (D6/AD-4)
│       └── tools/                 #   §11 도구 = engine/kb/pob 호출 얇은 어댑터
│
├── knowledge/                   # ══ ① 정본 (git 버전관리 = 단일 진실) ══
│   ├── game-data/                #   구조적 레코드 JSON/NDJSON
│   ├── wiki/                     #   서술 Markdown (자체 재작성, D10)
│   ├── crafting-rules/           #   제작규칙 데이터
│   ├── insights/                 #   verified 인사이트 (승격된 것만)
│   └── builds/                   #   reference Build 레코드 (승격된 것만)
│
├── artifacts/                   # ══ ② 산출물 (재생성 불가·계보 有) — gitignore ══
│   ├── builds/<build-id>/        #   manifest.json + design.md(설계 문서, D26·BUILD_DESIGN.md) + build.pob + tiers/ + validation.json
│   ├── anchors/<anchor-id>/      #   ★ 검증된 외부 앵커 빌드 (poe.ninja 등, D30) — 코드 원문 + 계보 manifest (사용자 협의 2026-07-31)
│   ├── sessions/<session-id>/    #   candidates/ + tree-search/ + choices.json
│   ├── feedback/{raw,candidates}/#   큐레이션 대기 (→ knowledge/insights 승격)
│   ├── live-snapshots/           #   산출물이 참조한 시세 스냅샷 (계보 고정)
│   └── ingest-raw/               #   ★ 원시 스냅샷 = 별도 데이터 repo의 clone (KB_INGEST KI-1)
│                                 #     poe2-ai-wiki-data (프라이빗·append-only) — 멀티 PC 동기화
│
├── var/                         # ══ ③ 파생/캐시 (재생성 가능·삭제 무해) — gitignore ══
│   ├── index.sqlite              #   knowledge/ 재인덱싱 (self-healing)
│   ├── pob-cache/                #   빌드해시 PoB 결과 캐시
│   └── live/                     #   라이브 시세 (TTL, 휘발)
│
├── external/pob/<snapshot>/     # PoB 스냅샷 독립 클론 (gitignore, 재현성 D4)
│
├── .claude/skills/<이름>/SKILL.md  # Claude 진입점 (frontmatter). **이 경로만 탐색된다**
│                                #   — skills/ 아래 두면 `/스킬명`이 뜨지 않는다
├── skills/                      # ══ 고수준 워크플로 (D6) — 생성 파이프라인 오케스트레이션 ══
│   ├── build-generation/AGENTS.md   # 지침 본문(정본) 한 벌. SKILL.md가 여기를 가리킨다
│   └── kb-ingest/AGENTS.md
│
├── tests/{unit, integration, eval}/   # eval = 반프록시 생성 품질 (PoB 실측, AD-8)
└── scripts/                     # PoB 셋업·버전검증, 인덱스 재생성 CLI
```

---

## 3. 3계층 데이터 모델 + 저장 위치

| 계층 | 최상위 | git | 삭제 시 | 내용 |
|---|---|---|---|---|
| **① 정본** | `knowledge/` | ✅ 추적 | 복구 불가 (git 보호) | KB 진실. 패치 때만 수정 |
| **② 산출물** | `artifacts/` | ❌ ignore | **정보 손실** | 빌드 산출물·세션·피드백·시세 스냅샷 |
| **③ 파생/캐시** | `var/`, `external/` | ❌ ignore | 무손실 (재생성) | index.sqlite·PoB 캐시·PoB 클론 |

- **KB 정본 = 파일**(`knowledge/`, git). **인덱스 = SQLite**(`var/index.sqlite`, gitignore). 정본 데이터는 SQLite에 저장하지 않는다 — SQLite는 검색 속도용 인덱스일 뿐.
- ②와 ③의 차이: ③은 정본에서 결정적으로 **재생성 가능**(삭제 무해), ②는 런타임 산물이라 **재생성 불가**(삭제 시 정보 손실).
- **② 중 `ingest-raw/`는 로컬 전용이 아니라 별도 데이터 repo**([poe2-ai-wiki-data](https://github.com/skerfolg/poe2-ai-wiki-data))의 clone — 사용자가 여러 PC에서 작업하므로, 재생성 불가 데이터의 유일본이 특정 PC에 존재하면 안 된다는 원칙([KB_INGEST](KB_INGEST.md) KI-1). 추후 feedback·sessions 동기화도 같은 메커니즘으로 확장 가능.

---

## 4. 의존 방향 규칙

```
mcp ──▶ engine ──▶ kb ──▶ common
          │         ▲
          ├──▶ pob ─┘
          ├──▶ live
          ├──▶ cost
          ├──▶ learning
          └──▶ artifacts
```
- 상위 계층이 하위를 import한다. **하위가 상위를 import 금지**(특히 무엇도 `mcp`를 import하지 않음).
- 위반은 import-linter로 CI에서 실패시킨다(**도입 확정** — P0에서 설정, [ROADMAP](ROADMAP.md)).

---

## 5. 인덱스 self-healing 계약 (코드로 강제)

> 인덱스 재생성은 **지침이 아니라 코드의 성질**로 보장한다. 어떤 에이전트(Claude/Codex)도 "재빌드"를 기억할 필요가 없다.

`src/pok/index/`에 `ensure_index()`를 두고, **MCP 서버 기동 시 + 첫 검색 시** 호출(멱등):

```
ensure_index():
    if var/index.sqlite 없음:                          → 빌드    # PC 이동 · 삭제
    elif index.source_fingerprint ≠ knowledge/ 현재 해시:  → 재빌드  # KB 수정
    elif index.schema_version ≠ 현재 스키마/버전:        → 재빌드  # 버전업
    else:                                               → 사용
```

- 인덱스 빌드 시 **`knowledge/`의 git HEAD 커밋(또는 콘텐츠 해시) = `source_fingerprint`** 와 **`schema_version`** 을 인덱스 메타에 각인한다.
- 세 트리거(없음/KB수정/버전업)를 이 비교로 모두 감지한다.
- 보조로 **명시적 CLI**(`scripts/` 또는 `python -m pok.index build`)를 둬 CI/수동 재빌드를 지원한다.

---

## 6. 산출물 → 정본 승격 경로

②(`artifacts/`)는 런타임과 ①(`knowledge/`) 사이의 **스테이징 계층**이다. 검증되기 전엔 ②에 머물고, 검증되면 ①로 승격된다("학습이 KB를 직접 수정하지 않는다" §7을 물리적으로 보장).

```
artifacts/feedback/candidates  ──[큐레이션: 사람 승인 + 보조]──▶  knowledge/insights   (§10.4)
artifacts/builds/<id>          ──[승격: reference 가치 판단]────▶  knowledge/builds     (Build 엔티티)
```

- 승격 로직: `src/pok/artifacts/promote.py` + `src/pok/learning/curation.py`.
- 라이브 데이터: 현재 시세 = `var/live/`(휘발 캐시), 산출물이 근거로 삼은 시세 = `artifacts/live-snapshots/`(계보 고정).

---

## 7. 지침 거버넌스 (AGENTS.md / CLAUDE.md 적재적소 구조)

토큰 낭비 없이 Claude·Codex 양쪽이 결정을 계승하도록 **3층**으로 배치한다:

| 층 | 위치 | 로드 시점 | 크기 |
|---|---|---|---|
| ① 지도 | 루트 `AGENTS.md` (+`CLAUDE.md`=`@AGENTS.md`) | 항상 | 얇게 |
| ② 적재적소 | 디렉터리별 `AGENTS.md` (+`CLAUDE.md`=`@AGENTS.md`) | 그 폴더 작업 시 on-demand | 각 수 줄 |
| ③ 상세 | `docs/PROJECT_STRUCTURE.md`, `docs/BLUEPRINT.md` | 지도가 가리킬 때 | 전체 |

- **Claude는 `AGENTS.md`를 자동으로 읽지 않는다** — Claude의 네이티브 파일은 `CLAUDE.md`다. 그래서 각 디렉터리에 **`AGENTS.md`(실내용, Codex용) + `CLAUDE.md`(`@AGENTS.md` 임포트, Claude용)** 를 쌍으로 둔다. 수정은 `AGENTS.md` 한 곳만.
- **Codex**는 작업 위치 기준으로 nested `AGENTS.md`를 자동 병합한다.
- 원칙: **런타임 동작은 코드로 강제**(§5), 문서는 **확장 시 판단**을 안내할 뿐. 동작을 문서 준수에 의존시키지 않는다.

현재 `AGENTS.md`가 배치된 디렉터리: 루트 · `knowledge/` · `skills/` · `artifacts/`(데이터) · `src/pok/{kb,index,pob,engine,artifacts,mcp}`.

---

## 8. 확정 사항 (이 세션 합의)

- ✅ 3계층 데이터 분리(정본/산출물/파생)와 저장 위치 (§3)
- ✅ `artifacts/` 산출물 스토어 + 승격 경로 (§6)
- ✅ 엔진 = 결정적 도구 상자, 생성 판단은 skills/+에이전트 (§1)
- ✅ PoB 격리 = `src/pok/pob/` + `external/pob/` (§1)
- ✅ 인덱스 self-healing을 **코드로** 보장 (§5)
- ✅ 지침 거버넌스 3층 + AGENTS/CLAUDE 페어링 (§7)
- ✅ 구조 변경 = 사용자 상호협의 강제 (§0)
- ✅ 의존 방향 단방향 (§4)
- ✅ **패키지명 = `pok` (Path of Knowledge)** — PoB 작명 규칙 계승, 2026-07-29 확정
- ✅ **import-linter 도입** — 계층 위반은 CI 실패 (P0)
- ✅ 원시 스냅샷 = 별도 데이터 repo ([KB_INGEST](KB_INGEST.md) KI-1)
- ✅ **`artifacts/builds/<id>/design.md`(설계 문서, D26) + `artifacts/anchors/` 신설(외부 앵커 빌드, D30)** — §9 파킹이 아닌 확정, 근거: 사용자 협의 2026-07-31 (BLUEPRINT §10.0). `engine/constraints/`는 구현됨(D27, 2026-07-31 — 검사기 4종+KB 상수 인용)

## 9. 미결 사항 (파킹 — 해당 로드맵 단계에서 결정, [ROADMAP](ROADMAP.md) 참조)

1. ~~**인사이트 3계층**~~ → ✅ **확정** (2026-08-04, BLUEPRINT §15-3): `season → durable → canonical 레코드` 사다리. 계층은 인사이트 front matter의 `scope` 필드(폴더 분리 아님). 승격은 전부 사람 판정 — `set_scope`(1칸)·`promote_to_record`(2칸). 레코드로 올라가도 인사이트는 남는다(사실=레코드 / 규율=인사이트).
2. ~~**`build-id` 체계**~~ ✅ **타임스탬프+슬러그** (예: `20260730-spark-stormweaver`, 사용자 확정 2026-07-30). 사람이 읽고 대화에서 지칭하기 쉬운 쪽을 우선 — 내용 추적·중복 탐지는 manifest의 해시로 보완.
3. ~~**보존 정책**~~ → ✅ **확정** (2026-08-04): **자동 삭제 없음**. `artifacts/retention.py`가 보관물을 나열하고 **보호 사유**를 붙일 뿐이며, 지울지는 사람이 정한다("지우기 전에 후보를 전량 나열" 원칙). 보호 판정 = 인사이트의 `feedback_id` 참조 ∨ `state=promoted`. `delete()`는 사유를 강제하고 참조된 항목은 **거부**한다(계보 절단 방지). 근거: 용량은 문제가 아니다(실측 190KB) — 위험은 계보 절단과 폐기 설계의 재도출이다.
4. **`artifacts/` 중 builds·sessions·feedback의 멀티 PC 동기화** (데이터 repo 확장 여부) → P3에서

> 파킹 항목이 결정될 때마다 이 문서를 갱신한다.
