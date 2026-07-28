# artifacts/ (데이터) — 재생성 불가 산출물 (gitignore)

- 빌드 산출물(`builds/`)·생성 세션(`sessions/`)·큐레이션 대기 피드백(`feedback/`)·시세 스냅샷(`live-snapshots/`).
- ⚠️ **손으로 편집하지 말 것.** 오직 코드(`src/poe2_wiki/artifacts/`)를 통해서만 쓰고 읽는다.
- 삭제 시 **정보 손실**(재생성 불가). `var/`(파생 캐시)와 다르다.
- 정본(`knowledge/`) 진입은 **승격(promote)으로만** — 임의로 knowledge/에 복사 금지.
- 이 디렉터리는 gitignore이며, 이 `AGENTS.md`와 `.gitkeep`만 추적된다.
- 상세: [PROJECT_STRUCTURE](../docs/PROJECT_STRUCTURE.md) §3, §6
