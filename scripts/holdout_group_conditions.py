"""컨셉 홀드아웃 — 그룹 부착이 **새 빌드로 일반화되나**. (BACKLOG #85)

## 결과: 안 된다 (2026-08-19, 2,683벌 · 컨셉 89종 · 5회)

    재현 282/482 = **58.5%**  ·  기저 **53.0%**

부착된 조건이 홀드아웃에서 재현되는 비율이 기저율보다 5.5%p 높을 뿐이고,
**5회 중 2회는 기저보다 낮았다**(50.0 vs 51.4 · 53.2 vs 55.1). 즉 코퍼스 안에서만
성립하는 상관이었다. 그래서 `NodeValue`에서 `groups`를 뺐다.

⛔ **이 파일을 지우지 말 것**(사용자 지시 2026-08-19). 표본 설계를 고치거나(컨셉 무관
무작위 표본 추가) 조건을 PoB로 직접 재게 되면 **같은 잣대로 다시 판정**해야 한다 —
잣대가 없으면 「이번엔 좋아 보인다」로 넘어간다.

## 왜 기저율을 함께 재나

「부착된 조건이 검증에서 맞았다」만으로는 부족하다. 리프트 2배 기준이 느슨해서 아무
짝이나 절반은 통과한다 — 기저율과 비교해야 「그룹이 실제로 뭔가를 안다」고 말할 수 있다.


코퍼스는 컨셉 112종에 50벌씩으로 잘려 있다. 같은 폴더의 50벌이 통째로 함께 움직이므로,
그 안에서만 성립하는 상관이 조건처럼 보일 수 있다. 컨셉을 **통째로 떼어** 학습에서
빼고, 거기서도 같은 조건이 성립하는지 본다.

⛔ 대조군이 필요하다 — 「부착된 조건이 검증에서 맞았다」만으로는 부족하다. 아무 조건이나
찍어도 맞을 확률(기저율)과 비교해야 「그룹이 실제로 뭔가를 안다」고 말할 수 있다.
"""

import glob
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from pok.common.paths import knowledge_dir
from pok.engine.counterfactual_aggregate import _build_groups, _spec_of
from pok.engine.counterfactual_campaign import REMOVALS, build_id, campaign_dir
from pok.engine.jewel_taint import classify
from pok.engine.mechanism_groups import derive
from pok.engine.tree.graph import TreeGraph

STAT = "CombinedDPS"
graph = TreeGraph(knowledge_dir())
groups = derive()

# (컨셉, 빌드그룹집합, {node_id: 움직였나})
table: list[tuple[str, frozenset[str], dict[int, bool]]] = []
seen: set[str] = set()
for p in sorted(glob.glob("artifacts/ingest-raw/ladder/0-5/*/*.json")):
    try:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
        bid = build_id(doc)
        if bid in seen:
            continue
        seen.add(bid)
        f = campaign_dir("0-5") / REMOVALS / f"{bid}.json"
        if not f.exists():
            continue
        res = json.loads(f.read_text(encoding="utf-8"))
        spec = _spec_of(doc)
    except Exception:
        continue
    taint = classify(spec, graph)
    if not taint.usable:
        continue
    fired = {
        r["node_id"]: abs(float(r["deltas"].get(STAT, 0.0))) > 0
        for r in res["removals"]
        if r["deltas"] and r["node_id"] not in taint.tainted_nodes
    }
    if fired:
        table.append((Path(p).parent.name, frozenset(_build_groups(spec, groups)), fired))

concepts = sorted({c for c, _, _ in table})
print(f"빌드 {len(table):,}벌 · 컨셉 {len(concepts)}종")


def attributions(rows, min_seen=5, min_lift=2.0, min_p=0.3):
    """(노드, 그룹) → 리프트. 집계기와 **같은 규칙**이어야 검증이 성립한다."""
    n_rows: Counter[int] = Counter()
    n_fired: Counter[int] = Counter()
    seen_g: dict[int, Counter[str]] = defaultdict(Counter)
    fired_g: dict[int, Counter[str]] = defaultdict(Counter)
    for _c, gs, fired in rows:
        for nid, moved in fired.items():
            n_rows[nid] += 1
            n_fired[nid] += int(moved)
            for g in gs:
                seen_g[nid][g] += 1
                if moved:
                    fired_g[nid][g] += 1
    out = {}
    for nid, rows_n in n_rows.items():
        for g, seen_n in seen_g[nid].items():
            without = rows_n - seen_n
            if seen_n < min_seen or without < min_seen:
                continue
            p_with = fired_g[nid][g] / seen_n
            p_wo = (n_fired[nid] - fired_g[nid][g]) / without
            if p_with < min_p:
                continue
            lift = float("inf") if p_wo == 0 else p_with / p_wo
            if lift >= min_lift:
                out[(nid, g)] = lift
    return out, n_rows, n_fired, seen_g, fired_g


rng = random.Random(17)
held = 0
kept = Counter()
for trial in range(5):
    test_c = set(rng.sample(concepts, max(1, len(concepts) // 4)))
    train = [r for r in table if r[0] not in test_c]
    test = [r for r in table if r[0] in test_c]
    trained, *_ = attributions(train)
    # 검증셋에서 같은 (노드, 그룹)의 리프트를 다시 잰다
    _, n_rows, n_fired, seen_g, fired_g = attributions(test, min_seen=1, min_lift=0, min_p=0)
    ok = testable = 0
    for nid, g in trained:
        seen_n = seen_g[nid].get(g, 0)
        without = n_rows.get(nid, 0) - seen_n
        if seen_n < 3 or without < 3:
            continue
        testable += 1
        p_with = fired_g[nid][g] / seen_n
        p_wo = (n_fired[nid] - fired_g[nid][g]) / without
        if p_wo == 0 or p_with / p_wo >= 2.0:
            ok += 1
    # 기저율 — **부착되지 않은** (노드, 그룹) 짝이 검증에서 우연히 통과하는 비율
    base_ok = base_n = 0
    pool = [(nid, g) for nid in seen_g for g in seen_g[nid] if (nid, g) not in trained]
    for nid, g in rng.sample(pool, min(len(pool), 3000)):
        seen_n = seen_g[nid].get(g, 0)
        without = n_rows.get(nid, 0) - seen_n
        if seen_n < 3 or without < 3:
            continue
        base_n += 1
        p_with = fired_g[nid][g] / seen_n
        p_wo = (n_fired[nid] - fired_g[nid][g]) / without
        if p_wo == 0 or p_with / p_wo >= 2.0:
            base_ok += 1
    print(
        f"  #{trial + 1} 학습 {len(train):>4}벌/검증 {len(test):>4}벌 · 부착 {len(trained):>4}건 · "
        f"검증가능 {testable:>3} · **재현 {ok / max(testable, 1) * 100:5.1f}%** "
        f"(기저 {base_ok / max(base_n, 1) * 100:4.1f}%, n={base_n})"
    )
    kept["ok"] += ok
    kept["testable"] += testable
    kept["b_ok"] += base_ok
    kept["b_n"] += base_n
print(
    f"\n합계: 재현 {kept['ok']}/{kept['testable']} = "
    f"**{kept['ok'] / max(kept['testable'], 1) * 100:.1f}%** · "
    f"기저 {kept['b_ok'] / max(kept['b_n'], 1) * 100:.1f}%"
)
