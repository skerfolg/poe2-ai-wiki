# artifacts/ (데이터) — 재생성 불가 산출물 (gitignore)

- 빌드 산출물(`builds/`)·생성 세션(`sessions/`)·큐레이션 대기 피드백(`feedback/`)·시세 스냅샷(`live-snapshots/`).
- ⚠️ **손으로 편집하지 말 것.** 오직 코드(`src/pok/artifacts/`)를 통해서만 쓰고 읽는다.
- 삭제 시 **정보 손실**(재생성 불가). `var/`(파생 캐시)와 다르다.
- 정본(`knowledge/`) 진입은 **승격(promote)으로만** — 임의로 knowledge/에 복사 금지.
- `ingest-raw/` = **별도 데이터 repo**(poe2-ai-wiki-data)의 clone — append-only, 기존 패치 폴더 수정·삭제 금지, 수집 후 즉시 push(멀티 PC 원칙). 상세: [KB_INGEST](../docs/KB_INGEST.md).
- 이 디렉터리는 gitignore이며, 이 `AGENTS.md`와 `.gitkeep`만 추적된다.
- 상세: [PROJECT_STRUCTURE](../docs/PROJECT_STRUCTURE.md) §3, §6
