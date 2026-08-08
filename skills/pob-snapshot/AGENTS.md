# pob-snapshot — PoB 스냅샷 교체 워크플로

> **대상**: 저비용 에이전트로도 실행되도록 **재량을 제거한 절차**. 순서를 벗어나지 말 것.
> 전제: 레포 루트, `.venv` 활성(또는 `.venv/bin/python`), `PYTHONPATH=src`, `luajit` 사용 가능.
> 근거: [BLUEPRINT](../../docs/BLUEPRINT.md) §9(AD-1/AD-2/D4) · [KB_INGEST](../../docs/KB_INGEST.md) §5.

## 왜 절차가 필요한가

핀을 잘못 고치면 계산은 새 스냅샷으로 돌고 카탈로그 검증은 옛 파일을 읽는 식으로
**조용히** 갈라져 증거 체인(AD-2)이 거짓이 된다. 그리고 스냅샷이 바뀌면 **PoB가 읽는
문구도 바뀌므로** 파싱 갭 표기(트리 500건)가 통째로 낡는다.

문서 체크리스트는 안 지켜진다(철칙 5). 그래서 **빠뜨림은 테스트가 잡는다** —
`tests/unit/test_pob_pin_consistency.py`(핀 일치)와
`tests/integration/test_tree_parse_gaps.py`(표기 최신). 이 절차는 그 테스트를
**통과시키는 순서**이지, 규율의 유일한 방어선이 아니다.

## 절차

### 0. 무엇으로 올릴지 확정

새 커밋 SHA(전체 40자)를 사람에게서 받는다. **임의로 최신을 고르지 말 것** —
스냅샷은 KB와 같은 증거 체인에 묶인다(KI-5).

### 1. 새 클론 (덮어쓰기 금지 — AD-2/D4)

```bash
NEW=<40자 SHA>
git clone --no-checkout https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2.git \
  external/pob/${NEW:0:7}
git -C external/pob/${NEW:0:7} checkout $NEW
```

⛔ 기존 `external/pob/<옛 short>/`를 지우거나 덮지 않는다. **새 버전 = 새 클론**이
재현성의 근거다. 옛 스냅샷은 사람이 따로 지시할 때만 지운다.

### 2. 핀 갱신 — 손으로 고칠 곳은 **셋**

소스 쪽 파생은 전부 `src/pok/kb/pob_pin.py`의 `POB_COMMIT` 하나에서 나온다(#16).
나머지 둘은 파이썬 밖이라 자동으로 못 따라온다.

| 순서 | 파일 | 무엇 |
|---|---|---|
| ① | `src/pok/kb/pob_pin.py` | `POB_COMMIT` (전체 40자) — **authoring point** |
| ② | `.github/workflows/ci.yml` | `POB_COMMIT` |
| ③ | `.github/workflows/pob-smoke.yml` | `POB_COMMIT` |

그리고 **manifest를 재생성한다** — 런타임(`resolve_snapshot()`)이 여는 스냅샷은
manifest가 정하므로, 이걸 잊으면 상수만 새 것이고 실제로는 옛 PoB가 돈다:

```bash
PYTHONPATH=src python -m pok.kb.ingest manifest --patch <ver>
```

⛔ **`knowledge/game-data/**`의 `sources[].pob`는 건드리지 않는다.** 그건 그 레코드를
**언제 어느 커밋에서 긁었는가**의 증거다. 스냅샷을 올렸다고 덮으면 계보가 거짓이 된다 —
재수집이 값을 바꿀 때 그 경로가 갱신한다. 주석 안의 "실측 (5d173cb)" 서술도 같다:
그때 잰 값이라는 기록이므로 그대로 둔다.

확인:

```bash
PYTHONPATH=src pytest tests/unit/test_pob_pin_consistency.py -q
```

빠뜨린 곳이 있으면 **어느 파일인지 이름을 대며** 실패한다(manifest 재생성 누락 ·
워크플로 2개 · 소스에 옛 경로 재등장 — 네 갈래 전부 돌연변이로 감지 확인).

### 3. 파싱 갭 감사 재실행 (필수)

스냅샷이 바뀌면 PoB가 읽는 문구가 바뀐다 — 이제 파싱되는 노드도, 새로 못 읽게 된
노드도 생긴다.

```bash
PYTHONPATH=src python -m pok.pob.parse_gaps        # 트리 노드
PYTHONPATH=src python -m pok.pob.item_parse_gaps   # 아이템·룬 접사 (베이스 20종, 수 분)
```

- 출력의 **표기/해제 건수를 보고에 그대로 옮긴다.** 해제(cleared)가 많으면 PoB가
  그 계열을 구현했다는 뜻이라 **설계 판단이 달라진다**(그 노드들의 델타가 이제 0이 아니다)
- 먼저 세어만 보려면 `--dry-run`
- 배경: `src/pok/pob/parse_gaps.py` · `src/pok/pob/item_parse_gaps.py`

### 4. 전량 검증

```bash
PYTHONPATH=src pytest
```

인자 없이 돌린다. `tests/unit/`과 `tests/integration/`을 따로 돌리면 잡히지 않는
것이 있다(실측 2026-08-08: 파일명 중복이 CI에서만 터졌다).

실패가 나면 **고치기 전에 분류부터** 한다:
- **핀 불일치** → 2로 돌아간다
- **파싱 갭 표기 낡음** → 3을 안 돌렸다
- **계산값 변화**(스냅샷 실측 고정값을 든 테스트) → **PoB가 계산을 바꾼 것**이다.
  숫자를 맞춰 고치기 전에 **무엇이 왜 바뀌었는지 사람에게 보고**한다. 조용히
  기대값을 갈아끼우면 회귀를 놓친다

### 5. 재수집 필요 여부 판정

PoB 유래 KB(젬 스탯·트리·유니크·상태이상 상수)는 스냅샷에서 온다. 스냅샷이 바뀌면
**값이 달라졌을 수 있다.**

```bash
PYTHONPATH=src python -m pok.kb.ingest status --patch <ver>
```

값 갱신이 필요하면 이 스킬이 아니라 **`kb-ingest` 스킬**로 넘긴다(수집은 그쪽 소관).
넘긴다는 사실과 이유를 보고에 남긴다.

### 6. 커밋

핀 갱신 · 파싱 갭 표기 · (있다면) 재수집 결과를 **한 PR**로 올린다. 커밋 메시지에
**옛/새 커밋 SHA와 파싱 갭 증감**을 적는다 — 나중에 "언제 무엇이 달라졌나"를
역추적하는 유일한 단서다.

## 금지 사항

- ⛔ 기존 스냅샷 디렉터리 덮어쓰기·삭제 (AD-2 — 새 버전은 새 클론)
- ⛔ `knowledge/game-data/**`의 `sources[].pob` 일괄 치환
- ⛔ 테스트 기대값을 **먼저** 고치기 (계산 변화는 보고 대상이지 수선 대상이 아니다)
- ⛔ 3(파싱 갭 감사)을 **둘 중 하나만** 돌리고 4로 가기 — 트리와 아이템은 경로가 달라
  각각 표기가 낡는다. 통합 테스트가 막지만, 막힌 뒤에 도는 건 낭비다
- ⛔ PoB 소스를 고쳐 문제를 우회 (AD-1 — 계산 소스는 손대지 않는다)
