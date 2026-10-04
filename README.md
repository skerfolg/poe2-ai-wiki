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
도구 제한은 1,800초입니다(트리 최적화 기본 600초, 장비 자동 채움 기본 1,200초).
전역 설정과 다른 서버 설정은 보존하며, 기존 사용자 소유 `pok` 설정은 덮어쓰지 않습니다.
경로를 옮겼거나 별도 worktree를 쓰면 해당 위치에서 다시 실행합니다.
`--check`는 설정과 실행 환경을 검사하고, 옵션 없이 실행하면 설정 내용을 출력합니다.

Codex에서 이 저장소를 신뢰한 뒤 **새 작업을 열어** MCP와 스킬을 읽습니다.
기존 작업에는 도구 목록이 남을 수 있습니다. 새 작업에서 `server_info`를 호출해 연결을
확인하고, `$poe2-ai-wiki:build-generation` 또는 “PoE2 빌드를 구상해 줘”로 시작합니다.
PoE 스킬 7종은 `.agents/skills/`에서 발견하며 실제 절차는 `skills/` 한 곳을 참조합니다.
설정 형식과 탐색 규칙은 [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)와
[Skills](https://learn.chatgpt.com/docs/build-skills)를 따릅니다.

KB 조회에는 PoB 실행 환경이 필요하지 않습니다. **계산·조립에는** 고정 PoB 스냅샷과
LuaJIT가 필요합니다. `knowledge/ingest/manifest.json`이 가리키는 스냅샷을
`external/pob/<snapshot>/`에 준비하고, LuaJIT가 PATH에 없으면 `POK_LUAJIT`를
실행 파일 경로로 설정한 뒤 Codex를 다시 시작합니다. 설치된 스냅샷은 덮어쓰지 않습니다.
상세 규약은 [PoB 지침](src/pok/pob/AGENTS.md)을 봅니다.

## Claude Code

기존 `.mcp.json`과 `.claude/skills/`를 사용합니다. `POK_PYTHON`을 프로젝트 Python 경로로
설정합니다(Windows: `.venv/Scripts/python.exe`, macOS/Linux: `.venv/bin/python`).
계산·조립의 필수 절차 검사는 MCP 서버가 시행하므로 Claude 훅 유무에 의존하지 않습니다.
이미 실행 중인 Claude 세션도 MCP 서버를 재시작해 수정된 검사를 읽습니다.

## 검증

프로젝트 Python으로 `-m pytest`를 실행하면 단위 테스트만 수행합니다.
`-m pytest tests/integration`은 PoB 통합 테스트이며 실행 환경이 필요합니다.
PR 전에는 통합 테스트를 함께 실행합니다. CI는 `pytest tests`로 두 종류를 수집합니다.

## 📐 청사진 (Source of Truth)

- **[docs/BLUEPRINT.md](docs/BLUEPRINT.md)** — 프로젝트 정의, 핵심 결정(D1~D24), 데이터/KB/저장/계산/빌드생성/트리최적화 설계, 로드맵, 미결 사항, 부록(프로토타입 실패 교훈).

## 핵심 방향 (요약)

- 웹 서비스가 아니라 **엔진 + Claude/Codex용 MCP·스킬**. 사용자 접점 = Claude Code/Codex 대화 그 자체.
- 빌드 출력 = **PoB 형식**. **PoB = 계산·검증 오라클(headless)**, 계산 재구현 안 함.
- **KB** = poe2db(카탈로그)·PoB(계산)·poewiki(서술) 취합한 우리만의 canonical 지식(**관계 그래프**), 패치 때만 갱신, 학습과 분리.
- **빌드 생성** = KB그래프 + PoB델타 기반 재조합, 에이전트가 결정·PoB가 측정(반프록시), 저/중/고 스펙 티어.
- **학습** = 큐레이션 RAG(파인튜닝 아님). **Python 중심, Windows+macOS.**
- **철칙**: 코딩 전 프로젝트 구조 확정. 이전 프로토타입은 참고용만.

## 현재 작업과 결함

[CURRENT-PLAN](docs/CURRENT-PLAN.md)과 [BACKLOG](docs/BACKLOG.md)를 확인합니다.
