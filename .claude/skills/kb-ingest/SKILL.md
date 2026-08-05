---
name: kb-ingest
description: PoE2 KB 수집·정형화를 감독한다 (patch 갱신 시). poe2db/PoB에서 원시 스냅샷을 받아 파싱·병합·검증하고 정본에 반영. 새 패치 데이터 수집, 젬/모드/트리 갱신, ingest 리포트 확인, 수록 갭 판정에 쓴다.
---

# kb-ingest

**정본 지침은 [AGENTS.md](../../../skills/kb-ingest/AGENTS.md)다 — 먼저 그것을 읽고 순서를 그대로 따른다.**
이 워크플로는 저비용 에이전트로도 실행되도록 **재량을 제거한 절차**다. 순서를
벗어나지 말 것.

## 전제

- 레포 루트에서 실행, `.venv` 활성(또는 `.venv/bin/python`), `PYTHONPATH=src`
- 워크트리라면 `.venv`·`artifacts/ingest-raw`·`external/pob` 심링크가 있어야 한다

## 절대 규칙

⛔ **정본 레코드를 `write_text`로 직접 쓰지 말 것** — `store`의 쓰기 API만 쓴다
(B-6·B-7). 배치 규칙(KD-1)과 안전장치 6종이 거기 있다. 직접 쓰면 샤드가 통째로
날아간다(실측 2회, 830건·884건).

⛔ **제외는 조용히 하지 말 것** — 승인된 제외만 `knowledge/ingest/exclusions.json`에
근거와 함께 기록한다(KI-8). 지우기 전에 후보를 전량 나열해 사람이 판단한다.
