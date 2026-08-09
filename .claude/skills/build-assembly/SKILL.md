---
name: build-assembly
description: 컨셉이 확정된 PoE2 빌드를 정본으로 조립한다 — assemble_pob → artifacts/builds/<id>/ 루프. 장비를 기억이 아니라 파일로 들고 적법성 전수 검사를 거친다. 본조립, 최종 빌드 확정, 장비 확정, PoB 코드 산출, validation.json 확인에 쓴다. (컨셉 탐색은 build-generation)
---

# build-assembly

**정본 지침은 [AGENTS.md](../../../skills/build-assembly/AGENTS.md)다 — 먼저 그것을 읽고 순서를 그대로 따른다.**
이 워크플로는 저비용 에이전트로도 실행되도록 **재량을 제거한 절차**다. 순서를
벗어나지 말 것.

## 전제

- 레포 루트에서 실행, `.venv` 활성(또는 `.venv/bin/python`), `PYTHONPATH=src`
- `luajit` 사용 가능 (조립이 PoB를 돌린다)
- **컨셉이 확정돼 있을 것** — 스킬·어센던시·주력 축이 흔들리면 `build-generation`으로

## 절대 규칙

⛔ **장비를 대화에 들고 반복하지 말 것.** 실측 2026-08-09: 그렇게 20여 회 측정한 빌드가
**10슬롯 중 4개가 실재하지 않는 장비**였다. 문제는 부주의가 아니라 **정본이 없는 것**이다.

⛔ **탐색 단계(`compute_pob`) 수치를 최종 보고에 인용하지 말 것.** 보고 수치는
`artifacts/builds/<id>/validation.json`에서 가져온다.

⛔ **룬·희귀를 손으로 조립하지 말 것.** `optimize_runes`·`optimize_rare`가 낸 `text`를
그대로 쓴다 — 룬은 손기입 시 증폭이 **3.00배** 빠진다.

⛔ **스펙 편집본을 둘 새 디렉터리를 만들지 말 것** — 저장 위치 신설은 철칙 1(구조 합의)
사안이다. 재개는 `parse_pob(code_path="artifacts/builds/<id>/build.pob")`로 한다.
