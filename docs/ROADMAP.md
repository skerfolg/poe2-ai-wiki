# PoE2 AI Wiki — 로드맵 (Roadmap)

> **문서 상태**: v0.1 (2026-07-29) — 확정. BLUEPRINT §15-2 "재구축 로드맵/MVP"의 상세.
> **설계 근거**: "KB 먼저"(BLUEPRINT §7·§17) + "코드 먼저, 수집은 그 다음"(KB_INGEST KI-7) + 반프록시(AD-8) — 각 단계의 완료는 느낌이 아니라 **측정 가능한 Exit 기준**으로 판정한다.
> **변경 규칙**: 단계 순서·Exit 기준의 구조적 변경은 사용자 상호협의 후에만.
> **진행 상태**: ✅ P0 완료 → ✅ **P1a 완료** (2026-07-29, 시드 35·vocab v1·스키마·store 4층 검증·index self-healing, pytest 13 ✓, CI Win+mac green) → **현재: P1b** — ①젬 + ②트리 + ③유니크 완료 → **KB 5,960 레코드**. 완전성 기준 8중 확장(⑥⑦⑧) 가동 + 그로 드러난 결함 4건 교정 완료. 다음: KB_INGEST §6-2 ④ 베이스 아이템 + 모드 풀(제작규칙 RC4 설계 동반).
> - ① 젬 900 수록 (fetch 1,992 → KI-8 판정 → merge, GAME_DATA 796)
> - ② 트리 4,553 수록 (일괄 엔드포인트 2회 수집, 청크 분할 merge, 엣지 보존). 마스터리 368 제외 확정(구역 라벨/그래픽, 사람 판정) + 어센던시 선택 허브 5 수록(끊겼던 13노드 복구) + stats 마크업·개행 정규화 + 능력치 택1 노드 293 구조 승격(`attribute_choice`)
> - ③ 유니크 493 수록 (무기88·방어구219·기타138·재배48, PoB 대사 469, 변형은 현재 패치본만) + 성유 부여방법 884 노드 보강. 재배판 베이스타입 48건 승계·PoB 변형 베이스 6건 교정
> - 사람 확인 대기: 젬 보류 58, 미매칭 시드 9(support.pierce·passive.acrobatics — 실데이터는 티어드/개명 추정), PoB 전용 유니크 11
>
> **신규 PC 셋업**: `gh auth login` → clone → `python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"` → `.venv/bin/pre-commit install` → 데이터 repo clone(`gh repo clone skerfolg/poe2-ai-wiki-data artifacts/ingest-raw`)

---

## 0. 전체 그림

```
P0 부트스트랩
 └─ P1 KB 기반+수집  (P1a 시드 KB 실증 → P1b ingest 구현·대량 수집)
     └─ P2 MCP 조회            ← M1: 첫 사용자 가시 가치 (위키 엔진)
         └─ P3 PoB 계산+빌드 생성   ← ★ MVP 선언 지점
             └─ P4 트리 최적화
                 └─ P5 학습 루프
                     └─ P6 위키·챗봇 확장
```

- **MVP = P3 완료** (청사진의 1차 목표 "빌드 추천·최적화"가 처음 성립하는 지점). P2 완료는 중간 마일스톤 **M1**.
- **PoB 리스크 조기 해소**: P1의 ingest가 PoB 덤프(LuaJIT 실행)를 필수로 요구(소스이자 완전성 기준 ②) → 최대 기술 리스크(LuaJIT·OS별 셋업)의 절반이 P1에서 자동 검증됨. P3 진입 전 나머지 절반(계산 왕복)만 짧은 스파이크로 확인.

## 1. 단계 상세

| 단계 | 내용 | Exit 기준 (측정 가능) |
|---|---|---|
| **P0. 부트스트랩** (짧게) | `pyproject.toml`(패키지 `pok`)·common·pre-commit·CI 골격·**import-linter**(계층 위반=CI 실패) | `pip install -e .` 성공 + 빈 테스트 통과 + 의존 방향 위반 시 CI 실패 확인 |
| **P1a. 시드 KB 실증** | condition vocab v1 + `knowledge/schema/` 작성 → **손으로 소수 레코드**(스킬10·서포트10·패시브10) 작성 → store 로드·검증·인덱스 빌드·검색·관계 순회 전 구간 통과. 스키마 결함을 "30개 수정"으로 조기 발견 | 시드 30개가 스키마 검증+`ensure_index()` 3트리거+`search_kb` 왕복을 통과. 시드는 이후 `tests/` 픽스처로 영구 재사용 |
| **P1b. ingest 구현·대량 수집** | ingest CLI(fetch·parse·match·merge·report) + PoB 덤프 스크립트 → **저비용 에이전트로 수집 가동**(kb-ingest 스킬, KI-7) + 서술 재작성 병행(KI-2) | **완전성 8중 기준(KB_INGEST §4) 전부 통과한 첫 KB 커밋** + 증거 체인(manifest→데이터 repo) 성립 |
| **P2. MCP 조회** — M1 | FastMCP 서버 + `search_kb`/`get_entry`(D14 2단계) + 관계 그래프 순회 도구. **한국어 부분어 검색 개선 검토**(현 unicode61은 '불꽃'→'전기불꽃' 미매칭, 2026-07-29 실증 — FTS5 trigram/prefix 후보) | **Claude/Codex 대화에서 실제 KB 질의 응답** — 위키 엔진 탄생 |
| **P3. PoB 계산+빌드 생성** — ★MVP | (진입 스파이크: headless 계산 왕복 Win/mac 검증) → PoB 어댑터·daemon·codec·버전맵 → `assemble`/`compute_pob`/`check_item_legality` → build-generation 스킬(후보 2~3 → 사용자 선택 → 3티어 조립·검증, D24/D18) | 자연어 요청 → **PoB 코드 산출** + `validation.json`에 다차원 목적(RC3) 실측 기록 |
| **P4. 트리 최적화** | `evaluate_delta`·`connect_anchors`(Steiner)·`optimize_tree` + PoB 상주 프로세스 성능(D23) | 베이스라인 대비 **포인트마다 PoB 델타로 정당화**되는 개선 산출 |
| **P5. 학습 루프** | feedback→큐레이션→승격(promote) 완성, artifacts store·retention, 인사이트 검색 반영(RAG) | 인게임 피드백 1건이 verified 인사이트로 승격돼 **다음 생성에 반영되는 왕복 1회** 실증 |
| **P6. 위키·챗봇 확장** | 시맨틱 검색(하이브리드, D13)·i18n 심화·가격 추산 스킬(D19)·챗봇 범위(§15-4) | P6 진입 시 정의 |

## 2. 파킹된 결정의 배치

| 결정 | 배치 |
|---|---|
| condition vocab 초판 범위 | **P1a 첫 작업** |
| build-id 체계 · artifacts(builds/sessions/feedback) 멀티 PC 동기화 확장 | P3 |
| 인사이트 3계층(canonical/durable/season) · 보존 정책 | P5 |
| 위키/챗봇 범위(§15-4) · 가격 추산 구체화(§15-5) · i18n 수준(§15-6) | P6 진입 시 |

## 3. 운용 원칙

- **단계 건너뛰기 금지** — Exit 기준 미달 상태로 다음 단계 착수하지 않는다(반프록시: "얼추 된 것 같음"은 완료가 아님).
- **각 단계 완료 시** 해당 문서 갱신(PROJECT_STRUCTURE·KB_* 등) + BLUEPRINT 버전 갱신 검토.
- 병렬 여지: P1b 수집(저비용 에이전트)이 도는 동안 P2 MCP 서버 골격 개발 가능(수집은 감독만 필요하므로).
