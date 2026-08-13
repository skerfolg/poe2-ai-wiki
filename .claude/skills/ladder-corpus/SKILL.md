---
name: ladder-corpus
description: poe.ninja 래더에서 컨셉별 상위 빌드의 PoB 코드를 수집하고 겹쳐 읽어 채택률을 낸다 (UsageProfile·Build 레코드). 표본 확대, 새 컨셉 축 수집(skills·keypassives·skillmodes·items), 프로파일 재생성에 쓴다.
---

# ladder-corpus

**정본 지침은 [AGENTS.md](../../../skills/ladder-corpus/AGENTS.md)다 — 먼저 그것을 읽고 순서를 그대로 따른다.**

핵심만: 원시는 **append-only**이고 재생성 불가다(poe.ninja 스냅샷이 갱신되고 캐릭터가 리스펙된다) — 수집 후 데이터 repo에 **push**할 것. `--min-count`는 **주지 말 것**(기본 1=전량이 정책이다).
