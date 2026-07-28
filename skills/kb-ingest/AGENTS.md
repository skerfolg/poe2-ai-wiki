# kb-ingest — KB 수집·정형화 감독 워크플로

> **상태**: 스텁 (ingest CLI 구현 후 명령을 실명으로 확정). 설계: [KB_INGEST](../../docs/KB_INGEST.md) (특히 KI-7).
> **대상**: 저비용 에이전트(저티어 Claude/Codex)로 실행 가능하도록 재량을 제거한 절차. **아래 순서를 벗어나지 말 것.**

## 절차 (패치 수집)

1. `artifacts/ingest-raw/`에서 `git pull` — 체크포인트 동기화 (없으면 데이터 repo clone부터).
2. fetch 실행: `python -m pok.kb.ingest fetch --patch <ver> --source <src>` (멱등 — 중복 실행 무해).
3. status 확인: pending=0, failed=0 인지. failed 있으면 **재시도 1회만**, 그래도 실패면 사유와 함께 사람에게 보고(임의 우회 금지).
4. `artifacts/ingest-raw/`에서 커밋·push — 수집 즉시 다른 PC에서 접근 가능해야 함(멀티 PC 원칙).
5. parse→match→merge→validate 실행: `python -m pok.kb.ingest process --patch <ver>`.
6. 리포트를 사람에게 제시하고 **승인을 기다린다.** 승인 없이 `knowledge/`에 커밋 금지.

## 금지 사항

- ⛔ 스크립트를 우회한 직접 스크래핑/직접 `knowledge/` 편집.
- ⛔ 완전성 5중 기준(KB_INGEST §4) 미통과 상태에서 "수집 완료" 보고.
- ⛔ 서술 재작성 산출물에 `UNVERIFIED` 외 라벨 부여 (승격은 사람 스팟체크 후).
