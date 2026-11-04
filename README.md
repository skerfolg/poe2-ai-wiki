# PoE2 AI Wiki

Path of Exile 2의 지식을 구조화한 **AI Wiki 엔진** — Claude/Codex가 MCP 도구·스킬로 사용해 정보를 조회하고 **Path of Building(PoB) 형식**의 빌드를 생성·검증하며, 사람의 인게임 피드백을 누적해 지속적으로 나아지는 시스템.

KB 조회·관계 탐색·빌드 설계 보조·PoB 계산을 MCP 도구로 제공합니다.
방향·결정은 [BLUEPRINT](docs/BLUEPRINT.md), 현재 작업은 [CURRENT-PLAN](docs/CURRENT-PLAN.md)을 봅니다.

## Codex에서 시작하기

Python 3.12 이상으로 가상환경을 만들고 프로젝트를 설치합니다. 저장소 루트에서 실행합니다.

**Windows PowerShell**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe scripts/configure_codex.py --write
codex mcp get pok --json
```

**macOS / Linux**

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python scripts/configure_codex.py --write
codex mcp get pok --json
```

이미 설치된 환경은 생성·설치를 반복하지 않고 설정 명령부터 실행합니다.
`configure_codex.py`는 사용 중인 Python을 검증한 뒤 이 PC 전용 `.codex/config.toml`을
만듭니다. 실행 파일·작업 디렉터리·소스 경로는 절대 경로이고, 기동 제한은 60초,
도구 transport 제한은 1,800초입니다. 실제 요청 기본/최대 예산은
`get_server_capabilities.request_execution.budget_profiles`에서 확인합니다.
도구 내부 예산·요청 메타 기한·호스트 기한이 다르면 더 짧은 실제 한도를 적용합니다.
전역 설정과 다른 서버 설정은 보존하며, 기존 사용자 소유 `pok` 설정은 덮어쓰지 않습니다.
경로를 옮겼거나 별도 worktree를 쓰면 해당 위치에서 다시 실행합니다.
`--check`는 설정과 실행 환경을 검사하고, 옵션 없이 실행하면 설정 내용을 출력합니다.

Codex에서 이 저장소를 신뢰한 뒤 **새 작업을 열어** MCP와 스킬을 읽습니다.
기존 작업에는 도구 목록이 남을 수 있습니다. 새 작업에서 `server_info`를 호출해 연결을
확인하고, `$poe2-ai-wiki:build-generation` 또는 “PoE2 빌드를 구상해 줘”로 시작합니다.
PoE 스킬 8종은 `.agents/skills/`에서 발견하며 실제 절차는 `skills/` 한 곳을 참조합니다.
설정 형식과 탐색 규칙은 [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)와
[Skills](https://learn.chatgpt.com/docs/build-skills)를 따릅니다.

KB 조회에는 PoB 실행 환경이 필요하지 않습니다. **계산·조립에는** 고정 PoB 스냅샷과
LuaJIT가 필요합니다. `knowledge/ingest/manifest.json`이 가리키는 스냅샷을
`external/pob/<snapshot>/`에 준비하고, LuaJIT가 PATH에 없으면 `POK_LUAJIT`를
실행 파일 경로로 설정한 뒤 Codex를 다시 시작합니다. 설치된 스냅샷은 덮어쓰지 않습니다.
상세 규약은 [PoB 지침](src/pok/pob/AGENTS.md)을 봅니다.

## 설계 기록과 계산 계약

`server_info`로 실제 소스/커밋과 stale 여부를 확인하고 `get_server_capabilities`로
지원 계약을 확인합니다. 저장소를 갱신한 것과 이미 실행 중인 서버가 새 코드를 읽는
것은 다릅니다. 미지원 API를 호출하거나 새 기능이 기본 배포됐다고 가정하지 않습니다.

빌드 구상·개정은 `build-generation`, 실제 후보/채택안 조립은 `build-assembly`를
사용합니다. 두 클라이언트의 등록 진입점은 같은 `skills/` 정본을 참조합니다.
명시 v2 경로에서는 사용자 고정·메커니즘 필요조건·잠정 구현·성능 후보와 근거/질문을
기록하며, 공격→방어나 특정 최적화 호출을 불변 순서로 강제하지 않습니다.

- `compute_pob(input_policy="explicit")`은 제공 입력을 자동 완성 없이 계산합니다.
  절차 누락과 입력/성립 진단을 계산 불능이나 추천 완료로 합치지 않습니다.
- `assemble_pob(input_policy="explicit", purpose="exploration")`은 명시 후보를 조립합니다.
  최종 `purpose="recommendation"`은 현재 구성에 결박된 비교/설계 근거를 따로 검사합니다.
- 원문 XML이 정본이면 문서 편집/계산 API로 미지 정보와 비활성 세트를 보존합니다.
  스펙 재조립을 원본 전체 무손실로 취급하지 않습니다.
- 계산 성공·적법성 검사·추천 준비도는 인게임 가동률이나 빌드 품질 인증이 아닙니다.
  기존 legacy 기본값은 호환용으로 유지하며 새 경로의 전반적 품질 우월성을 주장하지 않습니다.

정확한 필드·호환·손실 범위는 [계약](docs/POK_REDESIGN_CONTRACTS.md),
실제 품질 검증은 [최종 비교](docs/POK_FINAL_BUILD_QUALITY_PROTOCOL.md)를 봅니다.

## 저장 경로와 독립 PoB worker

`POK_DATA_HOME`을 명시하면 그 아래 `artifacts/`를, `POK_CACHE_HOME`을 명시하면 해당
폴더 자체를 사용합니다. 둘 다 절대 경로여야 하며 미지정 시 기존 `artifacts/`·`var/`를
유지합니다. 명시 경로가 잘못됐거나 쓸 수 없을 때 다른 위치로 조용히 우회하지 않습니다.
`server_info.runtime_paths`에서 리소스/산출물/캐시의 실제 위치를 구분합니다.

수동 PoB 작업용 worker는 기존 `src/pok/pob`가 소유하며 KB·AI 연결 없이 동작합니다.
현재 Windows 번들 builder는 고정 upstream 배포 목록의 headless 실행 자산을 선택하고
필수 파일·Git 추적·경로와 포함 파일 전체 해시를 검사합니다. 개발 Export 자료나 임의
사용자 파일을 실행 자산으로 자동 포함하지 않습니다.

별도 pok-ui 저장소는 독립 소비자입니다. 코어 worker/CLI 검증과 실제 UI GUI·모델·설치
번들 검증을 구분하며, 새 기능을 모든 UI 브랜치가 이미 소비한다고 가정하지 않습니다.
현재 UI 경로·버전/스키마·실행 출처와 단계별 적용은 [UI 인계](docs/POK_UI_REDESIGN_HANDOFF.md)를
따릅니다. Windows worker 번들 결과를 macOS 애플리케이션 검증으로 확대하지 않습니다.

## 거래소 검색

`$poe2-ai-wiki:trade-search` 또는 “거래소에서 이 조건의 매물을 찾아줘”로 호출합니다.
호스트·리그·아이템 조건을 받아 거래소 파라미터를 구성하고 검색 결과를 JSON으로 돌려줍니다.
검색 링크만 만들 수도 있습니다. 구매·귓속말·이동·상시 감시는 수행하지 않습니다.
이 스킬은 Python 표준 라이브러리만 사용하며 MCP·PoB·overlay 설치가 필요하지 않습니다.
직접 실행과 입력 예제는 [거래소 검색 절차](skills/trade-search/AGENTS.md)를 봅니다.

## Claude Code

기존 `.mcp.json`과 `.claude/skills/`를 사용합니다. `POK_PYTHON`을 프로젝트 Python 경로로
설정합니다(Windows: `.venv/Scripts/python.exe`, macOS/Linux: `.venv/bin/python`).
기존 legacy 절차와 명시 v2 계산/추천의 검사를 구분합니다. v2 기본 계산에는 특정
최적화 호출 이력이 필요하지 않으며, 추천 근거 검사는 별도로 적용합니다. 검사는
MCP 서버가 시행하므로 Claude 훅 유무에 의존하지 않습니다.
이미 실행 중인 Claude 세션도 MCP 서버를 재시작해 수정된 검사를 읽습니다.

## 검증

프로젝트 Python으로 `-m pytest`를 실행하면 단위 테스트만 수행합니다.
`-m pytest tests/integration`은 PoB 통합 테스트이며 실행 환경이 필요합니다.
PR 전에는 통합 테스트를 함께 실행합니다. CI는 `pytest tests`로 두 종류를 수집합니다.

## 📐 청사진 (Source of Truth)

- **[docs/BLUEPRINT.md](docs/BLUEPRINT.md)** — 프로젝트 정의, 핵심 결정(D1~D24), 데이터/KB/저장/계산/빌드생성/트리최적화 설계, 로드맵, 미결 사항, 부록(프로토타입 실패 교훈).

## 핵심 방향 (요약)

- 웹 서비스가 아니라 **엔진 + Claude/Codex용 MCP·스킬**. 사용자 접점 = Claude Code/Codex와 별도 pok-ui.
- 빌드 출력 = **PoB 형식**. **PoB = 계산 오라클(headless)**, 계산 재구현 안 함.
- **KB** = poe2db(카탈로그)·PoB(계산)·poewiki(서술) 취합한 우리만의 canonical 지식(**관계 그래프**), 패치 때만 갱신, 학습과 분리.
- **빌드 생성** = KB그래프 + PoB델타 기반 재조합, 에이전트가 결정·PoB가 측정(반프록시). 요청한 구성과 범위의 근거를 검토하며
  고정 티어·호출 횟수·ready 도장을 품질로 대신하지 않음.
- **학습** = 큐레이션 RAG(파인튜닝 아님). **Python 중심, Windows+macOS.**
- **철칙**: 코딩 전 프로젝트 구조 확정. 이전 프로토타입은 참고용만.

## 현재 작업과 결함

[CURRENT-PLAN](docs/CURRENT-PLAN.md)과 [BACKLOG](docs/BACKLOG.md)를 확인합니다.
