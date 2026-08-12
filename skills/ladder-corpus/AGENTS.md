# ladder-corpus — 컨셉별 래더 빌드 수집·집계 절차

> **대상**: 저비용 에이전트(저티어 Claude/Codex)로 실행 가능하도록 **재량을 제거한 절차**.
> **아래 순서를 벗어나지 말 것.**
> 전제: 레포 루트에서 실행 · `PYTHONPATH=src` · `.venv/bin/python`.
> 설계 배경: [BACKLOG](../../docs/BACKLOG.md) #67 4·5차 절.

## 두 갈래가 있다 — 먼저 어느 쪽인지 확인할 것

| 갈래 | 컨셉 예 | 만드는 것 | 3단계에서 |
|---|---|---|---|
| **A군 (메커니즘 축)** | `skillmodes=Totem` | `UsageProfile` 레코드 | `profile` 명령이 **파일까지 쓴다** |
| **B군 (어센던시 빌드)** | `class=Blood Mage` | 기존 Build 레코드의 `data.observed` | 사람이 **손으로** 넣는다 |

A군은 표본에 여러 어센던시가 섞인다 — **그게 요점이다.** 클래스를 넘어 따라붙는
것이 곧 이식 가능한 문법이다(실측: `skillmodes=Totem` 10벌이 6개 어센던시에
걸쳐 있는데 8/10이 Archmage를 든다).

## 이 절차가 만드는 것

한 **컨셉**(= poe.ninja 질의 필터)의 상위 N명 PoB 코드를 모아 겹쳐서, 축마다
**불변(N/N = 필수)**과 **가변(3/N = 자유석)**을 가른다. 그 차이가 빌드 생성에
필요한 문법이다. 같은 빌드 여러 벌은 **중복이 아니라 데이터**다.

## 절차

### 1. 수집 — 컨셉 하나당 1회

```bash
PYTHONPATH=src .venv/bin/python -m pok.engine.ladder_aggregate collect \
  --league runesofaldur --filter class=Chronomancer --limit 10
```

- `--filter`는 반복 가능하다. **컨셉 정의가 곧 필터다.**
- ⚠ **필터 키는 복수형이다** — `skills` · `items` · `keypassives` · `skillmodes` ·
  `allskills` · `spiritgems` · `anointed` · `class` · `weaponmode`.
  단수형(`skill`·`item`·`skillmode`)은 poe.ninja가 **조용히 무시**하고 리그 전체
  상위 N명을 돌려준다(실측 2026-08-12). 수집기가 막아 주지만 처음부터 복수형을 쓸 것.
  값은 게임 내 표기 그대로 — 예 `--filter skills=Arc --filter skillmodes=Totem`.
- 리그 슬러그: 0.5=`runesofaldur` · 0.4=`vaal`.
- 멱등하다 — 다시 돌려도 같은 갱신본은 안 쌓인다(`skipped_same_revision`).
- 출력 JSON의 `failed`가 비어 있지 않으면 **그대로 보고**하고 다음 컨셉으로 넘어간다.
  임의로 재시도하거나 우회하지 말 것.

### 2. 집계 — 표본이 찼을 때만

```bash
PYTHONPATH=src .venv/bin/python -m pok.engine.ladder_aggregate aggregate \
  --season 0-5 --concept class-Chronomancer --min-sample 10
```

- `--min-sample`은 **기본값이 없다.** 사람이 지정한 값을 그대로 쓴다. 모르면 **묻는다.**
- 표본이 모자라면 `{"error": "표본 부족"}`과 함께 종료 1을 낸다 → 1로 돌아가
  `--limit`을 올려 더 모으거나, 사람에게 보고한다. **`--min-sample`을 임의로 낮추지 말 것.**
- 성공하면 `data.observed` 꼴 JSON이 stdout으로 나온다.

### 3-A. A군 — UsageProfile 만들기 (`profile`)

```bash
PYTHONPATH=src .venv/bin/python -m pok.engine.ladder_aggregate profile \
  --season 0-5 --concept skillmodes-Totem \
  --anchor mechanic.totems --label "토템 (Totem)" \
  --filter skillmodes=Totem --min-sample 10 --write
```

- `--concept`은 1에서 만들어진 디렉터리 이름과 **정확히 같아야 한다**
  (`artifacts/ladder/<시즌>/` 아래를 보고 확인할 것).
- `--filter`는 1에서 쓴 것과 **똑같이** 준다(레코드의 `query`가 된다 — 재현용).
- `--anchor`는 **KB 실존 id**다. `pok` MCP의 `search_kb`로 확인해서 넣는다.
  못 찾으면 **지어내지 말고 사람에게 보고**한다. 없는 id면 명령이 거부한다.
- `--write`가 있으면 `knowledge/game-data/usage-profiles/`에 파일을 쓴다.
  없으면 stdout으로만 낸다(확인용).
- 출력의 **클래스 구성을 반드시 보고**한다. 한 어센던시가 8/10 이상을 차지하면
  「클래스를 넘는 공통점」이 아니므로 그 사실을 함께 적는다.

3-A를 했으면 4로 간다(3-B는 건너뛴다).

### 3-B. B군 — 기존 Build 레코드에 싣기

2(`aggregate`)의 출력을 해당 Build 레코드의 `data.observed`에 넣는다
(`knowledge/game-data/builds/<시즌>/<빌드id>.json`).

- 넣을 자리는 `data` 안, `defense` **다음**이다.
- `data.offense`·`data.defense`(8축)는 **건드리지 않는다.** 그쪽은 해석이고 이쪽은 관측이다.
- 대상 레코드가 없으면 **만들지 말고 사람에게 보고**한다(8축 해석은 이 절차의 범위 밖).

### 4. 검증 — 반드시 통과시킬 것

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_build_entity.py -q
```

실패하면 되돌리고 사유와 함께 보고한다.

## 금지 사항

- ⛔ **중복 제거 금지.** 같은 빌드 여러 벌이 목적이다.
- ⛔ **`artifacts/ladder/`를 손으로 편집·삭제 금지.** PoB 코드는 재취득 불가라 곧 소실이다.
- ⛔ **`--min-sample`을 스스로 낮추지 말 것.** 표본 크기 판단은 사람 몫이다.
- ⛔ **`facets.tier` 금지.** 순위 주장은 시험(`test_no_build_claims_a_tier`)이 막는다.
- ⛔ 8축(`offense`/`defense`) 수정 금지 — 이 절차는 **관측만** 싣는다.
- ⛔ **앵커 id를 지어내지 말 것.** `search_kb`로 실존 확인, 없으면 사람에게 보고.
- ⛔ A군 결과를 Build 레코드에 넣지 말 것(클래스가 섞여 있어 빌드가 아니다).
- ⛔ 스크립트를 우회한 직접 스크래핑 금지.

## 보고 형식

컨셉마다 한 줄로:

- A군: `<컨셉> · 수집 N벌 · 클래스구성 [Oracle 4, Shaman 2, …] · 프로파일 <기록|표본부족(have/need)|앵커없음>`
- B군: `<컨셉> · 수집 N벌 · 집계 <성공|표본부족(have/need)> · 레코드 <반영|없음>`
