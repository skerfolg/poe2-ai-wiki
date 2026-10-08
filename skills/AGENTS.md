# skills/ — 고수준 워크플로 (생성 파이프라인 오케스트레이션)

- 각 스킬은 **공통 절차 + 클라이언트별 등록 진입점**으로 구성한다. 두 클라이언트는 같은 실행 경로를 사용한다.
  - 공통 절차는 `skills/<이름>/AGENTS.md` 한 벌이다.
  - Claude Code 진입점은 `.claude/skills/<이름>/SKILL.md`, Codex 진입점은
    `.agents/skills/<이름>/SKILL.md`다. `AGENTS.md`만 두면 Codex 스킬 목록에 등록되지 않는다.
  - `SKILL.md`에는 **frontmatter(`name`·`description`)가 있어야** 한다. 없으면
    `Unknown skill`로 실패한다(실측 2026-08-04).
  - 지침 본문은 **`AGENTS.md` 한 벌만** 둔다 — 이 디렉터리가 그 자리다. `SKILL.md`는
    진입점(frontmatter + 시작 전 확인사항)이고 규율을 복사하지 않는다. 두 벌이 되면 어긋난다.
- **"무엇을 만들지"의 판단·순서가 여기 산다** — 엔진(`src/pok/engine/`)은 결정적 도구만 제공(AD-3).
- 생성 파이프라인(BLUEPRINT §10.2)의 오케스트레이션은 엔진이 아니라 스킬의 몫.
- `trade-search`는 자체 단발 실행기로 거래소를 검색한다. MCP·PoB 설정은 필요하지 않다.
- 상세: [PROJECT_STRUCTURE](../docs/PROJECT_STRUCTURE.md) §1 · [BLUEPRINT](../docs/BLUEPRINT.md) §10

## 명령 실행 환경 (Windows / macOS)

절차의 명령은 **레포 루트**에서 실행한다. 아래에서 현재 셸에 맞는 준비만 한 뒤
`python`을 사용한다. 가상환경이 없으면 [README](../README.md)의 설치부터 진행한다.

Windows PowerShell (실행 정책 때문에 활성화 스크립트를 열 필요 없음):

```powershell
$env:PATH = (Join-Path (Get-Location) '.venv/Scripts') + [IO.Path]::PathSeparator + $env:PATH
$env:PYTHONPATH = 'src'
python -c "import sys; print(sys.executable)"
```

macOS / Linux의 Bash·Zsh:

```sh
. .venv/bin/activate
export PYTHONPATH=src
python -c "import sys; print(sys.executable)"
```

출력이 이 레포의 `.venv` 파이썬인지 확인한다. 별도 셸 호출마다 환경이 초기화되면
준비를 반복하거나 Windows의 `.venv/Scripts/python.exe`, POSIX의 `.venv/bin/python`을
직접 호출한다. 아래 공통 절차는 환경변수 인라인 할당과 셸별 줄 연결 문법을 쓰지 않는다.
여러 명령은 앞 명령의 성공을 확인한 뒤 다음 명령을 실행한다. `<...>`는 입력할 값을
나타내는 자리표시자이므로 실제 값으로 바꾼다.
PoB 계산 단계에는 [README](../README.md)의 LuaJIT·핀 스냅샷 설정도 필요하다.

## 배포 런타임 실행 환경

데스크톱 배포 런타임에서는 리소스 루트가 읽기 전용일 수 있다. 이때는 앱이 제공한
`POK_RESOURCE_ROOT`, `POK_DATA_HOME`, `POK_CACHE_HOME`를 그대로 쓰고, Python은 런타임 안의
`python/python.exe`(Windows) 또는 `python/python`(POSIX)를 사용한다. 에이전트가 만든 거래소
검색 입력·결과 JSON은 `POK_DATA_HOME/live/trade-search/` 아래에 두고, 실행기 캐시는
`POK_CACHE_HOME/trade-search/` 아래에 둔다. 배포 런타임 사용을 위해 에이전트 권한을 넓히지
말고 기본 읽기 전용 + 요청 시 승인 정책을 유지한다.
