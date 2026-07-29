# kb-ingest — KB 수집·정형화 감독 워크플로

> **상태**: 수집(plan/fetch/status) 명령 확정. process(parse→merge)는 구현 대기.
> 설계: [KB_INGEST](../../docs/KB_INGEST.md) (특히 KI-7).
> **대상**: 저비용 에이전트(저티어 Claude/Codex)로 실행 가능하도록 재량을 제거한 절차. **아래 순서를 벗어나지 말 것.**
> 전제: 레포 루트에서 실행, `.venv` 활성(또는 `.venv/bin/python`), `PYTHONPATH=src` (editable 미설치 환경 대비).

## 절차 (패치 수집)

1. 체크포인트 동기화: `artifacts/ingest-raw/`에서 `git pull` (없으면 `gh repo clone skerfolg/poe2-ai-wiki-data artifacts/ingest-raw`).
2. 계획 확인/생성: `python -m pok.kb.ingest plan --patch <ver>` — 이미 있으면 불변 반환. `⚠ 표시≠계획` 경고는 그대로 보고(수정 시도 금지).
3. 수집: `python -m pok.kb.ingest fetch --patch <ver> --rate 1.0` — 멱등(재실행 무해). 레이트 1.0 미만으로 내리지 말 것(정중함 정책).
4. 진행 확인: `python -m pok.kb.ingest status --patch <ver>` — pending>0이면 3을 반복. failed>0이면 fetch 1회 재실행(자동 재시도), 그래도 남으면 **사유와 함께 사람에게 보고**(임의 우회 금지).
5. 체크포인트 push: `artifacts/ingest-raw/`에서 `git add -A && git commit && git push` — 수집 즉시 다른 PC에서 접근 가능해야 함(멀티 PC 원칙). 커밋 메시지: `<patch>: poe2db 수집 진행 (fetched=N/M)`.
6. (구현 대기) parse→match→merge→validate → 리포트 제시 → **사람 승인 대기.** 승인 없이 `knowledge/`에 커밋 금지.

## 금지 사항

- ⛔ 스크립트를 우회한 직접 스크래핑/직접 `knowledge/` 편집.
- ⛔ 완전성 5중 기준(KB_INGEST §4) 미통과 상태에서 "수집 완료" 보고.
- ⛔ `fetch-plan.json` 수동 편집·삭제 (계획은 확정 불변. 문제 시 사람에게).
- ⛔ 서술 재작성 산출물에 `UNVERIFIED` 외 라벨 부여 (승격은 사람 스팟체크 후).
