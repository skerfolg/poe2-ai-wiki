# proposal-round — M5 제안 라운드 (브리프 → 제안 → 측정 → 다이제스트)

> **대상**: 재량을 제거한 절차. **아래 순서를 벗어나지 말 것.**
> 전제: 레포 루트 · `PYTHONPATH=src` · `.venv` 파이썬.
> 설계: [ROADMAP §M5 확정 설계](../../docs/ROADMAP.md) · 철칙 3(엔진=결정적)·4(PoB는
> 검증기가 아니다)·5(강제 지점).
> **저장**: 제안·전개·측정은 **데이터 repo**(`artifacts/ingest-raw/proposals/<시즌>/`).

## 이 라운드가 무엇을 만드나

**빌드 개선 가설을 짓고 전부 재서 쌓는다.** 코퍼스(M2)는 남들이 채택한 것을,
반사실(M3~M4)은 버티는 것을 알려 주지만, 둘 다 **아직 아무도 안 해 본 조합**은
말해 주지 않는다. 교체 공간은 전수 불가(46일)라 그 좁히기를 LLM이 한다.

⛔ **여기서 정본은 안 움직인다.** 산출물은 제안·측정·다이제스트뿐이고, 정본 진입은
큐레이션(M6 = 사람 판정)이다. 그래서 라운드는 무인으로 돌아도 안전하다.

---

## P0. 브리프 — 무엇을 제안받을지 (결정적)

```bash
python -m pok.engine.proposal_round brief --season 0-5
```

`artifacts/ingest-raw/proposals/0-5/round-brief.json`이 나온다. **이걸 읽고 시작한다.**
안에 든 것: 유형 할당량 · 이미 낸 제안 목록(재탕 금지) · 검증 경로와 **알려진 한계**.

⚠ **할당량을 채워라.** 스태킹은 전개기가 있어 쓰기 쉽고, 그래서 안 지키면 제안이
거기로 쏠린다 — 창의의 중심 축(트리거 연쇄·상태이상·자원 순환)이 통째로 빠져도
다이제스트를 보기 전엔 아무도 모른다.

---

## P1. 제안 — 이 구간만 LLM이 한다

브리프의 `materials`에 있는 도구로 **근거를 먼저 모으고** 제안을 짓는다:

- `search_kb`·`get_entry` — 담체·메커니즘 조회. ⛔ 기억으로 아이템 효과를 쓰지 말 것
  (실측: 구변형을 현행으로 오판한 사고가 있다)
- `suggest_anchors` — 채택률 **옆에 제거 실측**이 붙어 나온다. `removal_mark`가
  `habit`인 노드는 「전원이 찍지만 빼도 안 아픈」 것 = **갈아탈 예산**이다
- `search_insights` — **이미 반증된 것을 다시 제안하지 말 것**
- `scan_supply_edges`·`trace_chains` — 스태킹 축의 비례 공급 그래프

각 제안은 다섯 필드다 (`engine/proposal.validate`가 강제한다):

| 필드 | 뜻 | 빠지면 |
|---|---|---|
| `title` | 짧은 이름 | 중복 판정 불가 |
| `mechanism` | 창의 축(스태킹·트리거 연쇄·상태이상·DoT·자원 순환·방어 구성·기타) | 쏠림이 안 보인다 |
| `premise` | **전제 기재** — 이 묶음이 어느 담체/메커니즘 위에서 성립하나 | 측정이 계보를 잃는다 |
| `route` | 검증 경로(브리프의 `routes` 키) | 가짜 검증 |
| `bundle` | 구체 변경안 | 잴 것이 없다 |

⛔ **못 재겠으면 버리지 말고 갭으로 남겨라**: `route: "unverifiable"` +
`route_gap: "<무엇이 없어서 못 재나>"`. 그 라벨의 누적이 다음 측정기의 우선순위
데이터다 — 조용히 빼면 「없던 제안」이 된다.

저장은 파이썬으로 (검증기를 통과해야 파일이 생긴다):

```python
from pok.engine.proposal import validate
from pok.engine.proposal_flow import expand, save
from pok.kb.store import load

p = validate({
    "title": "...", "mechanism": "트리거 연쇄",
    "premise": ["Cast on Critical", "..."],
    "route": "trigger-rate",
    "bundle": ["...", "..."],
})
save("0-5", p, expand(p, load()),
     proposed_by={"model": "<모델>", "session": "<세션 id>"})
```

`proposed_by`는 **필수**다 — 어느 모델·세션의 가설인지 없으면 재현도 교차 검증도
못 한다(M5 함정 ③).

---

## P2. 측정 — 전수 (결정적)

기준 빌드 스펙 JSON이 필요하다. **기준이 없으면 델타가 없다** — 제안은 「무엇을
바꾸나」이지 빌드 전체가 아니다.

```bash
python -m pok.engine.proposal_round measure --season 0-5 --spec <기준빌드.json>
```

- 이미 측정된 제안은 건너뛴다(**재개 가능** — 중단해도 된다)
- `route: unverifiable`은 재지 않고 갭으로 집계된다
- 담체를 변경안으로 못 옮기면 **부분 묶음을 재지 않고** 실패로 기록한다 —
  무엇을 잰 건지 모르는 수치를 남기는 것보다 낫다

---

## P3. 다이제스트 — 사람이 볼 것만

```bash
python -m pok.engine.proposal_round digest --season 0-5
```

`ranked`(DPS 델타 순) · `quota_shortfall`(유형 미달) · `tool_gaps`(못 잰 것)가 나온다.

⛔ **순위는 측정값이지 채택 권고가 아니다**(철칙 3·4). 인게임 성립·조작 난이도·
플레이 감각은 PoB가 못 잰다. 상위 항목도 사람 판정을 거쳐야 정본에 간다.

`synergy`가 양수인 항목을 특히 볼 것 — 개별로는 0인데 함께여야 열리는 조합이고
(실측: 눈알 왕관+래스피스 각각 0, 함께 1.44배), M5에 LLM을 쓰는 이유가 그 항이다.

---

## P4. 푸시

```bash
git -C artifacts/ingest-raw add -A && \
git -C artifacts/ingest-raw commit -m "0-5 제안 라운드 — <n>건" && \
git -C artifacts/ingest-raw push
```

데이터 repo는 append-only이고 PR 없이 직접 push한다.

---

## 하지 말 것

- ⛔ 제안을 **정본에 쓰지 말 것** — `knowledge/`는 큐레이션만 건드린다
- ⛔ 측정 없이 「좋아 보인다」로 다이제스트에 순위를 매기지 말 것
- ⛔ 브리프의 `already_proposed`에 있는 것을 다시 내지 말 것(예산 재탕)
- ⛔ 한 유형만 채우고 라운드를 끝내지 말 것 — 미달은 다이제스트에 남는다
