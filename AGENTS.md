# PoE2 AI Wiki — 에이전트 지침 (지도)

PoE2 지식 **엔진** + Claude/Codex용 **MCP 도구·스킬**. 웹서비스 아님.
**단일 진실 소스**: [docs/BLUEPRINT.md](docs/BLUEPRINT.md)(방향·결정) · [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md)(구조).

## KB 질의는 MCP 도구로 (파일 탐색 금지)

**PoE2 게임 지식 질문("~에 좋은 노드/모드/아이템은?")은 `pok` MCP 도구로 답한다:**
`search_kb`(키워드는 게임 용어로 — 예: "생명력 증가" type=Passive) → `get_entry`(fields 선별) → `related`(관계 순회).
`knowledge/` NDJSON·`external/pob`를 Grep/Read로 뒤지지 말 것 — 16,000+ 레코드를 파일로 탐색하면
수 분·수천 토큰이 들지만 search_kb는 1콜이다 (실측 2026-07-30: 파일 탐색 7분 vs 도구 1초).
파일 직접 접근은 ingest 개발·검증 작업에만.

**트리거 빌드의 발동률은 `compute_trigger_rate`로.** PoB `CalcTriggers.lua`에 메타 젬
에너지 모델이 없어 오라클이 못 잰다 — 손계산하지 말 것. 단 대상 Power는 **예상치**이고
(poe2db는 등급별 범위만 준다) Power 기반이 아닌 젬은 계산하지 않고 사유를 낸다.

**"잔여 자원에 무엇이 들어가나"는 `find_by_value`로.** `search_kb`는 텍스트만 매칭해
`reservation`·`cost` 같은 **수치 필드에 닿지 못한다**. 점유 검사기가 "정신력 40 남았다"까지
내고도 후보를 물을 경로가 없어 세션이 멈췄다 — 예: `find_by_value("reservation.at_max_level",
type="Skill", maximum=40)`
(점유 쌍은 크기 순이 아니라 **레벨 순**이다 — 점유는 레벨이 오를수록 줄어든다. 최고
레벨 값이 `at_max_level`이고, `min`/`max`는 크기 순 경계다.).

**"무엇이 어떤 형태로 있나"는 `describe_kb`·`describe_type`으로.** 레코드를 찾는 게 아니라
필드 충전율·값 분포를 훑는 질문에는 `search_kb`가 답하지 못하고, `schema/*.schema.json`은
**정의**라서 실제 채워진 정도와 다르다. 도구 경로가 없어 파일 탐색으로 도피한 사례가 4회
반복됐다(B-11). 예: Skill의 `category`는 12.5%만 채워져 있어 그것으로 거르면 대부분을 놓친다.

**"스태킹/「X당 Y」 사슬"은 `scan_supply_edges`·`trace_chains`로 (#91).** "고점 스태킹
빌드 찾아줘" 류 요구에서 `search_kb`로 'stacking'을 치면 0건이고(은어는 효과 문구에
없다), "per Strength"를 축별로 손검색하면 담체·배타를 놓친다 — 실측 2026-08-19:
수동 조사가 파일 탐색으로 도피했고 구변형 접사에 한 번 오판했다. `scan_supply_edges`가
축별 공급·보상 엣지 전수(슬롯·전직 잠금·대가 포함)를, `trace_chains(from_axis=)`가
다단 사슬(힘→생명→래스피스 류)·순환 후보·공존 진단을 낸다. 판정은 사용자 몫.

**"이 상태를 만들면 무엇으로 이어지나"는 `scan_state_edges`·`trace_mechanism_chains`로 (#92).**
`scan_supply_edges`(스탯→스탯)의 자매로 **상태→상태 전이**를 다룬다 — 동결·주입·잔류물·
룬 수호·콤보·봉인·균열·지면 효과가 축이다. `scan_synergies`는 **쌍만** 내고
`discover_mechanics`는 문구에 키워드가 없으면 못 찾아, 다단 연쇄(예: `Snap`이 원소
상태이상을 먹고 주입을 만들어 주입 페이오프로 잇는 사슬)는 어느 도구로도 안 나왔다.
⚠ 반환의 `unproduced_axes`(생산자 0인 축)는 "그 축은 못 쓴다"가 아니라 **수집·어휘 갭
후보**다. 두 층을 함께 보려면 **`trace_cross_chains`**(#95) — 마디마다 층 꼬리표가
붙고, 페이오프는 두 층 합산이다(한 층만 보면 과소평가: `power_charge` 2건 vs 60건).

**「크다」고 말하기 전에 `scan_scalers`로 분해한다 (#97).** 「X당 Y」 문구를 그냥
나열하면 **담체 개수를 배율 크기로 착각한다** — 실측 2026-08-22에 같은 오독이 **세 번
연속** 났다(per Power 17종을 "광맥"으로 · 위세 담체 93종을 "연쇄"로 · 워크라이 카운트를
배율로). 실제로는 대부분 상한 있는 **횟수**거나 메타 젬 **에너지 게이지**였고, 최고
후보는 id가 `...unused`(담체 없음)였다. `scan_scalers`가 네 축으로 가른다 —
`payoff_kind`(more=곱 / increased=희석 / counter·resource=게이지 / **reach=페이오프 아님**) ·
`cap`(상한 위로는 투자해도 0) · `attribution`(**`player`면 공허의 형상·토템·소환수에서
발동 안 함** — 인게임 실측) · `obtainable`(`unused`·`carrier_unknown` 자동 배제).

**`search_kb`가 0건이면 결과에 진단(`empty`/`why`)이 함께 온다 — 그것부터 읽는다.**
빈 결과가 곧 "KB에 없다"는 아니다. 실측 2026-08-05: 빈 결과 9건이 전부 질의 방식 문제였다
(효과 문구 한글 미수록 · `type` 오해 — 룬은 `Item`이 아니라 `Modifier` · 다단어 AND 과협소).
**효과 문구의 한글 보유율은 타입마다 다르다**: Passive 99.6%지만 Skill 0.2%·Support 0%이므로
스킬·보조를 효과로 찾을 땐 영어 표기를 쓴다.

## 철칙 (항상 적용)

1. ⛔ **구조 임의 변경 금지** — 디렉터리 구성·모듈 경계·저장 위치·의존 방향 변경은 **반드시 사용자와 상호협의 후에만**. (기존 모듈 안에 파일 추가는 허용, 새 최상위 폴더·경계 이동은 합의 필요.)
2. **정본 vs 파생** — `knowledge/`=git 정본(진실). `var/`·`artifacts/`·`external/`=gitignore. 파생을 진실로 취급 금지.
3. **엔진=결정적** — `src/pok/engine/`엔 빌드 솔버·생성 판단을 넣지 않는다. 판단은 `skills/`+에이전트.
4. **측정값 ≠ 실현 가능성** — PoB는 계산기이지 검증기가 아니다. 값이 나온다는 것이
   그 구성을 인게임에서 만들 수 있다는 뜻이 아니다(노드 해금 조건·어센던시 진입·
   config 가정의 근거를 PoB는 검사하지 않는다). 게이트가 막지 않았다고 성립하는 것도
   아니다 — 게이트는 아는 결함만 막는다. 실측 2026-08-06: 검사기 5종을 통과한 빌드가
   출혈 강도를 2.76배 부풀렸다(`insight.pob-is-a-calculator-not-a-validator`).
5. **규율은 강제 지점이 있어야 한다** — 새 규율을 문서에 적기 전에 "도구가 감지할 수
   있나"를 먼저 묻는다. 감지되면 문서가 아니라 **도구에 넣는다**(거부 또는 반환값 자동
   부착). 감지 불가한 것만 문서에 남기고 **안 지켜질 수 있다고 가정**한다. 실측: 문서에만
   있던 규율은 인용까지 하고도 어겨졌다(61배 격차·룬 소켓 6칸 공란·4회 반복 위반).
   따름정리 — **금지하려면 대안 경로를 먼저 만든다**(도구 갭은 규율 위반을 강제한다).
   `insight.disciplines-need-enforcement-points`
6. **인덱스는 코드가 자동 재생성** — `var/index.sqlite`를 손대거나 커밋하지 말 것. `src/pok/index/`의 self-healing이 처리(없음/KB수정/버전업 감지).

## 협업 규율 (여러 세션이 동시에 돈다)

1. **main 직접 커밋 금지** — 브랜치에서 작업 후 PR.
2. ⚠️ **머지 후 로컬 `main`을 반드시 당긴다** — **원격 머지와 로컬 갱신은 다르다.**
   PR을 머지해도 로컬 `main`은 그대로이고, 그걸 쓰는 세션은 **옛 코드로 작업한다**.
   ```bash
   git -C <레포 루트> pull --ff-only
   ```
   실측 사고(2026-08-05): PR 4개(#16~#19)가 원격에 머지됐는데 로컬 `main`이 #15에
   멈춰 있었고, 그 상태로 빌드 테스트가 돌아 **규율 개정 6건·도구 수정 4건이 전부
   미적용**이었다 — 측정하려던 것을 측정하지 못했다.
3. **작업 시작 전 최신 여부를 확인한다** — `git fetch && git log HEAD..origin/main`.
   비어 있지 않으면 먼저 당긴다. 특히 **다른 세션의 결과를 이어받을 때**.
4. **세션 제목에 역할 접두를 붙인다** — `[엔진]`(엔진·KB 수정·백로그 관리) /
   `[빌드]`(빌드 생성·검증). 세션에는 원래 종류 구분이 없어 **다른 세션이 찾을 방법이
   없다** — `list_sessions`에서 접두로 고른다. 결함·제안은 `[엔진]` 접두 중 가장 최근
   활동 세션에 보내고, 없거나 애매하면 **추측하지 말고 사용자에게 묻는다**.
   역할을 섞지 말 것 — 빌드 세션이 결함을 찾아내는 이유는 **도구를 만들지 않았기
   때문**이다(docs/BACKLOG.md §운용).
5. **PR을 올린 세션이 머지 후 동기화까지 책임진다** — 머지는 사용자가, 당기는 것은
   세션이. 그래야 "누가 하겠지"로 빠지지 않는다.

## 적재적소 — 언제 무엇을 읽나

- 구조·경계·저장 위치 관련 작업 → **docs/PROJECT_STRUCTURE.md**
- 방향·결정 배경(D1~D24) → **docs/BLUEPRINT.md**
- KB 레코드·스키마·조건·관계 작업 → **docs/KB_DATA_MODEL.md** (KD-1~4 확정)
- KB 수집·정형화·원시 스냅샷·완전성 기준 → **docs/KB_INGEST.md** (KI-1~7 확정)
- 지금 어느 단계인지·다음 할 일 → **docs/ROADMAP.md**
- **미해결 결함·기능 제안 큐 → docs/BACKLOG.md** — 세션을 이어받으면 **여기부터** 읽는다.
  결함 상태·실측 수치·검증 여부가 있어 조사를 처음부터 다시 하지 않는다.
  ⚠ 「검증으로 뒤집힌 보고」 절을 반드시 볼 것 — 이관 보고 3건이 틀렸다.
- 실전 빌드 테스트를 수행한다 → **docs/BUILD_TEST_PROTOCOL.md** (무개입 규칙·기록 항목) (P0~P6, Exit 기준. 단계 건너뛰기 금지)
- 특정 모듈 작업 → 그 디렉터리의 **AGENTS.md** (자동 로드됨)
- MCP 도구 추가 → docs/PROJECT_STRUCTURE.md §4(의존 방향)·§7, `src/pok/mcp/AGENTS.md`

## 시험은 두 단계 — 평소엔 단위만

```bash
pytest                      # 기본 = tests/unit 만. 약 1분 30초
pytest tests/integration    # PoB 부팅 — 파일당 수 분, 전량 30분~1시간
```

**평소 개발은 단위로만 돌린다**(사용자 지시 2026-08-13). 통합은 **지시받았을 때**와
**PR 직전**에 돌린다 — 매 수정마다 돌리면 기능 개발이 멎는다.

기본값은 `pyproject.toml`의 `testpaths`가 강제하고, **CI는 경로를 명시**해 통합까지
돌린다(`pytest tests`). 그 대칭이 깨지면 커버리지가 줄었는데 초록불이 뜬다 —
`tests/unit/test_ci_runs_integration.py`가 막는다.

⚠ 통합에서만 드러나는 결함이 실재한다: 윈도우 CRLF 누출은 단위 480건이 전부 통과한
상태에서 `test_item_parse_gaps`(통합)만 깨졌다. **PR 전에는 반드시 한 번 돌릴 것.**

## 스택 (요약)

Python 3.12+ · FastMCP · git 텍스트 정본 + SQLite(FTS5) 인덱스 · PoB(LuaJIT, headless) 계산 오라클 · Windows+macOS.

<!-- WORKFLOW-GOVERNANCE:START -->
This repository follows [Workflow Governance](docs/WORKFLOW-GOVERNANCE.md).

Agents must keep [Current Plan](docs/CURRENT-PLAN.md) and its Mermaid status graph updated when work status changes. Durable history belongs in [History Map](docs/HISTORY-MAP.md).

This AGENTS.md block is intentionally thin. Do not duplicate workflow policy here.
<!-- WORKFLOW-GOVERNANCE:END -->
