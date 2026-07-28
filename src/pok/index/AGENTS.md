# index/ — 파생 검색 인덱스 (self-healing)

- `knowledge/` → `var/index.sqlite` (FTS5 + 태그). **출력은 `var/` 에만**, git 커밋 금지.
- **self-healing 계약**: `ensure_index()`가 (파일 없음 | `knowledge/` 해시 불일치 | 스키마/버전 불일치)면 자동 재빌드. 빌드 시 `source_fingerprint`(knowledge/ git HEAD 또는 콘텐츠 해시)와 `schema_version`을 인덱스에 각인.
- MCP 서버 기동 시 + 첫 검색 시 호출(멱등). 보조로 명시적 CLI(`python -m pok.index build`).
- ⚠️ **런타임 동작은 이 코드로 보장** — 에이전트가 "재빌드"를 기억할 필요 없음.
- 검색은 단계적: 키워드/태그 먼저 → (후속) 시맨틱/하이브리드(D13).
- 상세: [PROJECT_STRUCTURE](../../../docs/PROJECT_STRUCTURE.md) §5
