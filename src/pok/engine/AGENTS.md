# engine/ — 결정적 도구 상자 (지능 없음)

- ⛔ 여기엔 **빌드 솔버·생성 판단을 넣지 않는다**(AD-3/D5). 조립·계산·델타·트리연결(Steiner)·합법성 같은 **결정적 연산만**.
- "무엇을 만들지"의 판단·창의는 `skills/` + 외부 에이전트(Claude/Codex)의 몫.
- 노드/아이템/모드의 효율은 **추측 금지 → PoB 델타로 측정**(반프록시, AD-8, RC1).
- `tree/`: 연결 비용은 결정적 알고리즘(Steiner/최단경로), 가치는 PoB 실측 + KB 후보 압축(D23).
- 목적함수는 단일 축(DPS/EHP) 금지 → **다차원 목적 프로파일**(`objective.py`, RC3).
- 상세: [PROJECT_STRUCTURE](../../../docs/PROJECT_STRUCTURE.md) §1 · [BLUEPRINT](../../../docs/BLUEPRINT.md) §10.3
