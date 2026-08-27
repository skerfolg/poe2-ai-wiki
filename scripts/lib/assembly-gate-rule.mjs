// #129 — 조립 파이프라인의 강제 지점을 **경고에서 거부로** 올린다.
//
// 왜 훅인가: MCP 반환 경고는 세션이 읽고 무시할 수 있다. 실측 2026-08-27 —
// `skipped_procedures`에 실린 경고를 세션이 **보고서에 옮겨 적고 실행은 안 했다**.
// `PreToolUse` 훅은 하버스가 실행하므로 세션이 우회할 수 없다(§0 ⑫ — 미룬 규율은
// 강제가 아니다).
//
// ⚠ `compute_pob`도 막는다. 안 그러면 조립을 피하고 계산 수치만 보고하는 경로로 샌다 —
// **이번 사고가 정확히 그 경로였다.**
//
// ⛔ 검사는 키워드와 무관하게 **항상** 켠다. 키워드 목록은 항상 사고보다 뒤처지고,
// 검사 여부를 거기 걸면 새 형태가 그대로 빠진다. 검사 대상이 `build_spec`이라
// 빌드 작업이 아니면 애초에 안 걸린다.

import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

/** 정본에서 `attribute_choice`(능력치 택1) 노드 id 전량. 실측 2026-08-27: 293개. */
export function attributeChoiceNodes(knowledgeDir = 'knowledge') {
  const dir = join(knowledgeDir, 'game-data', 'tree');
  const out = new Set();
  let files = [];
  try {
    files = readdirSync(dir).filter((f) => f.endsWith('.ndjson'));
  } catch {
    return out; // 정본을 못 읽으면 **검사를 끈다** — 훅이 환경 문제로 작업을 막으면 안 된다
  }
  for (const name of files) {
    let text = '';
    try {
      text = readFileSync(join(dir, name), 'utf8');
    } catch {
      continue;
    }
    for (const line of text.split('\n')) {
      if (!line.includes('attribute_choice')) continue;
      try {
        const rec = JSON.parse(line);
        const nid = rec?.data?.node_id;
        if (nid !== undefined && nid !== null) out.add(Number(nid));
      } catch {
        /* 깨진 줄은 건너뛴다 — 검사가 파싱 실패로 작업을 막지 않는다 */
      }
    }
  }
  return out;
}

/**
 * 이 빌드가 **가중치를 선언한 적이 있나**. `src/pok/engine/autofill.py::declared_weights`의
 * 짝이다 — 둘이 어긋나면 훅이 막은 것을 조립이 채우거나(무해) **훅이 통과시킨 것을
 * 조립이 못 채운다**(유해: 손으로 지은 아이템이 그대로 나간다).
 */
export function hasDeclaredWeights(spec) {
  const stamps = spec?.derived_from;
  if (!stamps || typeof stamps !== 'object') return false;
  return Object.values(stamps).some(
    (e) => e && typeof e === 'object' && e.weights && Object.keys(e.weights).length > 0,
  );
}

/**
 * 조립 전 필수 절차가 빠졌는지 판정한다.
 *
 * 반환 `{ ok, message }`. `ok:false`면 호출자가 거부한다.
 *
 * ⛔ **모르면 통과시킨다.** 정본을 못 읽거나 스펙이 빌드 모양이 아니면 검사를 건너뛴다 —
 * 게이트가 정상 작업을 막으면 우회 경로를 학습시킨다(§0 ⑪ 거짓 거부, #117·#118).
 */
export function evaluateAssemblySpec(spec, attrNodes) {
  if (!spec || typeof spec !== 'object') return { ok: true };
  const tree = Array.isArray(spec.tree_nodes) ? spec.tree_nodes.map(Number) : null;
  if (tree === null) return { ok: true }; // 빌드 스펙이 아니다

  const problems = [];

  // ① 능력치 택1 — 선택을 안 주면 PoB가 전부 기본값으로 계산한다.
  //    실측 2026-08-27: 배정 85노드 중 33개가 택1인데 선택 0건 → **능력치 165점 소실**,
  //    `req_shortfall`이 허수가 됐다.
  //    ⚠ **복원본은 한 칸 차이로 막지 않는다.** 복원기는 PoB 코드에 없는 선택을
  //       못 만들어 낸다 — 실측 2026-08-27: 49개 중 48개까지만 복원됐고 나머지 1개는
  //       코드 자체에 없다. 읽기를 막으면 **남의 빌드를 못 읽는다**. 대신 조립(쓰기)에서는
  //       그대로 막는다 — 거기서는 채울 수 있고, 안 채우면 능력치가 샌다.
  const fromRestore = Boolean(spec.restored_from);
  if (attrNodes && attrNodes.size && !fromRestore) {
    const need = tree.filter((n) => attrNodes.has(n)).length;
    const have = Array.isArray(spec.attribute_choices) ? spec.attribute_choices.length : 0;
    if (need > have) {
      problems.push(
        `능력치 택1 노드 ${need}개 중 ${have}개만 지정 — 나머지는 PoB가 기본값으로 계산한다 ` +
          `(능력치가 통째로 새고 req_shortfall이 허수가 된다). ` +
          `→ build_spec.attribute_choices에 {node_id: "str"|"dex"|"int"}를 채울 것`,
      );
    }
  }

  // ② 희귀 슬롯의 출처 — 손으로 지은 것과 도구 산출물을 구별할 수단이 `derived_from`뿐이다.
  //
  // ⚠ **2차(#129 자동 실행) 이후 이 검사는 좁아졌다.** `assemble_pob`이 도장 없는 희귀를
  //    **그 자리에서 `optimize_rare`로 채운다** — 채울 수 있으면 막을 이유가 없다(막으면
  //    자동 실행에 도달조차 못 한다). 채울 수 **없는** 경우에만 거부한다:
  //    빌드가 `weights`를 한 번도 선언하지 않아 **재사용할 판단이 없을 때**다
  //    (엔진은 빌드 판단을 지어내지 않는다 — 철칙 3).
  //
  // ⛔ **복원본은 검사하지 않는다.** `restore_pob_spec`으로 남의 빌드를 읽어 오면
  //    `derived_from`이 있을 수 없다 — 그때 막으면 **읽기 자체가 불가능해진다**
  //    (§0 ⑪ 거짓 거부: 통과 불가능한 게이트는 우회 경로를 학습시킨다).
  //    실측 2026-08-27: 이 검사를 무조건 걸었더니 복원한 실물 빌드가 그대로 막혔다.
  if (!spec.restored_from) {
    const handmade = (spec.items || [])
      .filter((it) => /Rarity:\s*Rare/i.test(String(it?.text || '')) && !it?.derived_from)
      .map((it) => it?.slot)
      .filter(Boolean);
    if (handmade.length && !hasDeclaredWeights(spec)) {
      problems.push(
        `희귀 슬롯 ${handmade.length}개에 derived_from이 없다 (${handmade.slice(0, 3).join(', ')}) — ` +
          `손으로 지은 접사는 실재 검증을 안 거쳤다. 이 빌드는 weights를 한 번도 선언하지 ` +
          `않아 자동 실행도 못 한다(엔진은 빌드 판단을 지어내지 않는다). ` +
          `→ optimize_rare를 한 번 돌려 판단을 밝히면, 나머지 슬롯은 조립이 알아서 채운다`,
      );
    }
  }

  if (!problems.length) return { ok: true };
  return {
    ok: false,
    message:
      `조립 전 필수 절차가 빠졌다 (#129):\n` +
      problems.map((p, i) => `  ${i + 1}. ${p}`).join('\n') +
      `\n\n이 검사는 경고가 아니라 거부다 — 경고로 실었더니 세션이 보고서에 옮겨 적고 ` +
      `실행은 안 한 사고가 있었다(2026-08-27).`,
  };
}
