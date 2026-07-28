# artifacts/ (코드) — 산출물 관리 (런타임↔정본 스테이징)

- 빌드 산출물·생성 세션·피드백은 재생성 불가 → `artifacts/` **데이터 디렉터리**(레포 루트, gitignore)에 계보(manifest)와 함께 저장한다.
- `store.py`(쓰기/읽기/조회) · `manifest.py`(계보: PoB버전·KB commit·해시) · `promote.py`(승격) · `retention.py`(보존).
- ⛔ **정본(`knowledge/`) 진입은 오직 승격(promote)으로만**: `feedback/candidates→insights`, `builds→builds`. 임의 기록 금지("학습이 KB를 직접 수정하지 않는다", §7).
- 상세: [PROJECT_STRUCTURE](../../../docs/PROJECT_STRUCTURE.md) §6
