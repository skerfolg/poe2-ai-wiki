# knowledge/ — 정본 KB (git 버전관리 = 단일 진실)

- 프로젝트의 **유일한 진실**: 구조적 레코드(`game-data/`)·서술(`wiki/`)·제작규칙(`crafting-rules/`)·검증된 인사이트(`insights/`)·reference 빌드(`builds/`).
- **수정은 패치/시즌 변경 시에만** (통제된 재수집 → git commit/tag). 평상시 read-only.
- 서술은 원문 인용이 아니라 **자체 재작성**(D10). 각 레코드엔 검증 라벨·출처 부착.
- `insights/`·`builds/`에는 **승격된 것만** 들어온다 (원천은 `artifacts/`, 승격은 `src/poe2_wiki/artifacts/promote.py`).
- ⚠️ `var/index.sqlite`는 여기서 **자동 재생성되는 파생물** — 직접 만들거나 커밋하지 말 것. 여기 파일을 고치면 인덱스가 self-healing으로 재빌드된다.
- **레코드 형태·스키마·조건 언어 = [KB_DATA_MODEL](../docs/KB_DATA_MODEL.md)** — 혼합 배치(큐레이션=개별 JSON, 벌크=NDJSON), 조건 expr 필수, 스키마는 `schema/`에 정본. 스키마 위반 레코드 커밋 금지.
- 상세: [PROJECT_STRUCTURE](../docs/PROJECT_STRUCTURE.md) §3 · [BLUEPRINT](../docs/BLUEPRINT.md) §7
