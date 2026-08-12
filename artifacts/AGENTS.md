# artifacts/ (데이터) — 재생성 불가 산출물 (gitignore)

- 빌드 산출물(`builds/`)·생성 세션(`sessions/`)·큐레이션 대기 피드백(`feedback/`)·시세 스냅샷(`live-snapshots/`)·래더 PoB 코드(`ingest-raw/ladder/`).
- `ingest-raw/ladder/<시즌>/<컨셉>/` = poe.ninja 래더에서 받은 **PoB 공유 코드 원본**
  ⚠ **별도 데이터 repo 안이다**(gitignore가 아니라 poe2-ai-wiki-data에 커밋된다) — PoB 코드는
  재취득 불가라 이 PC에만 두면 시즌이 넘어갈 때 소실된다(KI-1). 수집 즉시 push.
  (`src/pok/artifacts/ladder.py`가 쓴다). 예: `ladder/0-5/class-Chronomancer/`.
  ⚠ **리그 슬러그가 아니라 시즌으로 재운다** — 정본(`knowledge/game-data/builds/<시즌>/`)이
  시즌으로 갈리므로 원시가 슬러그(`runesofaldur`·`vaal`)면 둘을 못 잇는다.
  대응표는 `ladder._SEASON_BY_SLUG`이고, 모르는 리그는 **추측하지 않고 멈춘다**.
  컨셉 디렉터리는 질의 필터에서 나온다 — **컨셉 정의가 곧 필터**다.
  **append-only** — 코드는 나중에 다시 못 가져온다(스냅샷 갱신·리스펙·캐릭터 삭제).
  같은 캐릭터라도 갱신본이 다르면 **새 파일**로 쌓아 시간축을 보존한다.
  ⚠ 같은 빌드 여러 벌은 중복이 아니다 — 축의 **불변/가변**을 가르는 재료다.
- ⚠️ **손으로 편집하지 말 것.** 오직 코드(`src/pok/artifacts/`)를 통해서만 쓰고 읽는다.
- 삭제 시 **정보 손실**(재생성 불가). `var/`(파생 캐시)와 다르다.
- 정본(`knowledge/`) 진입은 **승격(promote)으로만** — 임의로 knowledge/에 복사 금지.
- `ingest-raw/` = **별도 데이터 repo**(poe2-ai-wiki-data)의 clone — append-only, 기존 패치 폴더 수정·삭제 금지, 수집 후 즉시 push(멀티 PC 원칙). 상세: [KB_INGEST](../docs/KB_INGEST.md).
- 이 디렉터리는 gitignore이며, 이 `AGENTS.md`와 `.gitkeep`만 추적된다.
- 상세: [PROJECT_STRUCTURE](../docs/PROJECT_STRUCTURE.md) §3, §6
