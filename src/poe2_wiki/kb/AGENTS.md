# kb/ — 지식베이스 로직 (판단 substrate)

- **생성 품질은 KB 의미 깊이에 상한이 걸린다 → KB 먼저**(BLUEPRINT §7).
- 시너지는 키워드가 아니라 **관계 그래프**(`scales_with`·`triggers`·`enables`…)로 판단한다(RC2 회피).
- **조건(condition)은 1급 필드** — 발동 조건을 명시하고 만족 가능성을 검증(가정 금지, RC1).
- 이 모듈 = 로드(`store.py`)·검증·그래프(`graph/`)·수집(`ingest/`, 패치 때만)·제작규칙(`crafting/`) 로직. **정본 파일은 `knowledge/`** 에 있다.
- 상세: [PROJECT_STRUCTURE](../../../docs/PROJECT_STRUCTURE.md) §2 · [BLUEPRINT](../../../docs/BLUEPRINT.md) §7
