# mcp/ — FastMCP 인터페이스 (얇은 어댑터)

- 도구(`tools/`)는 `engine`/`kb`/`pob` 호출을 감싸는 **얇은 어댑터**. 여기에 비즈니스 로직·판단·상태를 쌓지 말 것.
- 의존 방향의 최상위: **무엇도 `mcp`를 import하지 않는다**(§4). 새 도구 추가 시 방향 규칙 준수.
- 토큰 최소화 2단계: `search_kb`(압축 히트) → `get_entry`(선별 상세)(D14).
- 도구 카탈로그(러프): [BLUEPRINT](../../../docs/BLUEPRINT.md) §11. 추가 전 [PROJECT_STRUCTURE](../../../docs/PROJECT_STRUCTURE.md) §4·§7 확인.
