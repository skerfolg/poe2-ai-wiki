# pob/ — PoB 계산·검증 오라클 (유일 비-Python 경계)

- PoE2 계산은 **재구현·포터블 이중구현 금지**. 공식 PoB(headless, LuaJIT)만이 계산 소스(AD-1). drift 위험 때문.
- 스냅샷별 독립 클론(`external/pob/<snapshot>/`), **새 버전=새 클론**(덮어쓰기 금지=재현성, AD-2/D4).
- OS 차이(Win/mac)·롱패스·경로는 이 모듈(어댑터)이 흡수(D21).
- 빌드코드 = XML↔Deflate↔Base64(`codec.py`). 결과는 `var/pob-cache/`에 캐시. 최적화 루프용 상주 프로세스(`daemon.py`).
- 효율/스펙은 추측 금지 → PoB 델타로 **측정**(반프록시, AD-8).
- 상세: [PROJECT_STRUCTURE](../../../docs/PROJECT_STRUCTURE.md) §1 · [BLUEPRINT](../../../docs/BLUEPRINT.md) §9
