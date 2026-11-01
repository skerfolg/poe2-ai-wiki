# pok-ui 소비 계약 관측 — R2/R6 입력

2026-10-30. 조회한 UI HEAD: `d3817f68fa6506e7a49d9a82509c01fa9a79680c`.
조회 시 작업 트리는 깨끗했다. 별도 세션의 미래 변경을 대표하지 않는다.
범위: 로컬 소스 읽기. 실제 GUI·번들 실행·모델 통합 시험이나 개선 완료가 아니다.
정책: [BLUEPRINT](BLUEPRINT.md), 실행: [ROADMAP](ROADMAP.md).

R1 진행 중 동결된 엔진/지침/자료나 UI 저장소를 수정하지 않고 소비 경계만 확인했다.
아래 항목은 R2 계약 설계와 R6 재현 시험의 입력이며 설계 선택을 미리 확정하지 않는다.

| 관측 | 소스 | 후속 검증/계약 |
| --- | --- | --- |
| MCP text/structuredContent와 result 단일 래퍼를 해석하지만 큰 결과 참조 자동 복원은 없음 | `src/main/pok.ts`의 unwrapMcp/call/compute | 자동 restore/compute의 stored_tool_result 응답을 페이지·참조로 해석. 작은 응답과 동일한 구성/근거 도착 시험 |
| 연결 후 동적 도구 카탈로그 사용, compute는 server_info.stale만 확인 | `src/main/pok.ts` open/compute | identity_status=unavailable·번들 manifest·스키마/버전의 의미 분리. 도구 수를 호환성 인증으로 사용하지 않음 |
| projectActiveXml 뒤 assume_first_stat_set=true로 복원 | `src/main/pok.ts` compute | 활성 세트 선택과 스킬 stat-set 가정이 같은지 fixture로 확인. 모호성과 손실을 임의 기본값으로 감추지 않음 |
| 계산에 revision, 연결 변경에 generation을 결박 | `src/main/pok.ts`, `src/shared/contracts.ts` | 유지할 기반. 구버전·늦은 계산·재연결 때 결과가 다른 편집본에 붙지 않는지 실제 검증 |
| AI 제안은 전체 XML과 baseRevision, 적용 전 문법/리비전 확인 및 undo 저장 | `src/main/agent.ts` dynamicCall, `src/renderer/App.tsx` applyProposal | 문법 검사가 미지/비활성 정보 보존을 보장하지는 않음. 사용자 의도 변경과 비의도 손실을 diff/진단으로 구분하고 설계/PoB 리비전 동시성 계약 준비 |
| AppState/BuildDocument에는 구조화 설계 참조가 아직 없음 | `src/shared/contracts.ts` | 엔진 설계 정본을 UI에 복제하지 않도록 참조·캐시·오프라인·migration 계약을 R2에서 정의 |
| assemble_pob과 anchor 저장마다 개별 승인 요청 | `src/main/agent.ts` dynamicCall | 위임된 작업 공간의 가역 산출물 저장과 최종 XML 적용 승인을 구분. 사용자 반복 진행 지시를 줄이는 흐름과 충돌 여부 시험 |
| Chat 취소 API와 MCP 긴 호출이 별도 경로 | `src/main/agent.ts`, `src/main/pok.ts` | UI 취소·응답 분리·엔진 실행 중단을 서로 다른 사실로 표시. 실제 작업 종료·자원 회수까지 확인 |
| runtime verifier는 manifest.sha256의 존재/개수와 실행 파일 존재를 확인 | `scripts/verify-runtime.mjs` | 이 스크립트 자체는 파일별 SHA를 재계산하지 않음. 실행/배포 provenance 확인 경로와 변조 fixture 필요 |
| UI는 pok.exe serve와 resource/data/cache 환경 계약을 기대 | `src/main/pok.ts`, `scripts/stage-runtime.mjs` | 최신 엔진 main과 기존 데스크톱 런타임 변경의 병합/재사용 경계 확인. 환경 변수를 설정한 것만으로 엔진이 소비한다고 가정하지 않음 |

현재 UI 동작을 고장으로 단정하지 않는다. 정적 코드상 누락과 실제 재현 실패를 구분한다.
특히 원본 XML 전체 교체는 사용자의 의도일 수 있으므로 모든 차이를 손실로 거부하지 않는다.
앵커/진행 상태를 보여 주는 UI는 같은 엔진 기록을 소비하고 자체 게임 판단/다음 단계 솔버를 만들지 않는다.
구현 착수 시 UI HEAD와 작업 상태를 다시 조회하고 다른 세션의 변경을 보존한다.

## U0 후속 — 2026-10-31

UI 원격 main/로컬 HEAD d3817f6 동일·작업 트리 clean을 확인한 후 별도
`codex/pok-result-transport` 브랜치에서 첫 관측의 자동 참조 소비를 재현·수정했다.
신규3회귀가 수정 전 실패했고, 수정 후 전체64검사·경계·TypeScript·프로덕션 빌드가 통과했다.
현재 PoK Python 페이지 생성 코드로 만든 공개 합성 fixture를 포함하며 개인 데이터는 없다.
자동 연결/계산만 전체 결과를 회수하고 원문 UTF-8 해시·페이지 연속성·연결 세대와
결과 하나의 공유30분/64 MiB/25,000페이지 한도를 확인한다. 일반 모델 도구 호출은 작은 참조를 유지한다.
정규화 안내와 원문 참조도 계산 진단에 보존한다.

초안 [pok-ui PR #2](https://github.com/skerfolg/pok-ui/pull/2), 구현 커밋 `6fcddc6`.
병합·실제 GUI/최신 엔진/모델/배포 번들 검증은 하지 않았다. 이는 U0의 계약 회귀 수정이며
위 표의 다른 항목이나 R6 전체를 완료한 근거가 아니다. PoK 동결 코드/자료/지침은 바꾸지 않았다.

최종 UI HEAD `f6bc07b2e0ceea64ffd233d3e7cf357eae639ef8`의 원격 App checks도
2026-10-31 01:38:34 KST에 SUCCESS로 종료했다. 해당 워크플로는 `npm ci` →
`npm run check` → `npm run build`를 실행한다. Linux CI 통과를 Windows 앱/모델/번들
검증으로 확대하지 않는다. PR은 OPEN/draft이며 사용자 병합을 기다린다.
