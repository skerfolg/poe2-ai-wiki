# kb/ — 지식베이스 로직 (판단 substrate)

- **생성 품질은 KB 의미 깊이에 상한이 걸린다 → KB 먼저**(BLUEPRINT §7).
- 시너지는 키워드가 아니라 **관계 그래프**(`scales_with`·`triggers`·`enables`…)로 판단한다(RC2 회피).
- **조건(condition)은 1급 필드** — 발동 조건을 명시하고 만족 가능성을 검증(가정 금지, RC1).
- 이 모듈 = 정본 접근(`store.py` — 로드·검증·**쓰기**)·그래프(`graph/`)·수집(`ingest/`, 패치 때만)·제작규칙(`crafting/`) 로직. **정본 파일은 `knowledge/`** 에 있다.
- ⛔ **정본 레코드를 `write_text`로 직접 쓰지 말 것** — `store.write_shard`/`write_record`/`patch_records`/`patch_record_field`만 쓴다(B-6·B-7). 배치 규칙(KD-1)과 안전장치 6종(재검증·**레코드** 감소 거부·원자성·깊은 병합·**필드** 감소 거부·검사 선행)이 거기 있다. 직접 쓰면 샤드가 통째로 날아간다(실측 2회).
- ⚠️ **부분 갱신은 부분만 바꾼다** — 중첩 dict를 통째로 넘기지 말 것. `patch_records`가 재귀 병합하므로 바뀌는 키만 주면 된다. 값이 사라지면 쓰기가 **거부**된다(의도한 삭제는 `None` 또는 `allow_drop`으로 근거를 남긴다).
- 상세: [PROJECT_STRUCTURE](../../../docs/PROJECT_STRUCTURE.md) §2 · [BLUEPRINT](../../../docs/BLUEPRINT.md) §7
