"""PoB 스냅샷 핀 — **손으로 고치는 자리는 여기 하나**다 (백로그 #16).

## 왜 모듈 하나를 따로 두나

같은 커밋 SHA가 소스 5곳·CI 워크플로 2개·테스트 1곳에 복사돼 있었다. 하나만
빠뜨리면 계산은 새 스냅샷으로 돌고 카탈로그 검증은 옛 파일을 읽는다 — **조용히**
갈라지고, 그러면 "이 KB가 어느 PoB에 근거하는가"(AD-2 증거 체인)가 거짓이 된다.

이제 소스 쪽 파생은 전부 여기서 나온다. 손으로 고칠 곳은 **셋**이다:

1. 이 파일의 `POB_COMMIT`
2. `.github/workflows/ci.yml`의 `POB_COMMIT`
3. `.github/workflows/pob-smoke.yml`의 `POB_COMMIT`

(워크플로는 파이썬을 읽지 못해 남는다. 어긋나면
`tests/unit/test_pob_pin_consistency.py`가 **어느 파일인지 대며** 실패한다.)

## `knowledge/ingest/manifest.json`과의 관계

manifest는 **생성물**이다 — `python -m pok.kb.ingest manifest --patch <ver>`가 이
상수를 받아 적는다. 그리고 런타임(`pob.versions.resolve_snapshot`)은 그 **기록된
증거**를 읽어 스냅샷을 고른다. 즉 흐름은 한 방향이다:

    POB_COMMIT ──(ingest manifest)──▶ manifest.json ──(resolve_snapshot)──▶ external/pob/<short>

상수를 고치고 manifest 재생성을 잊으면 둘이 갈라지는데, 그것도 위 테스트가 잡는다.
교체 절차 전체는 `skills/pob-snapshot/`.
"""

from __future__ import annotations

from pathlib import Path

from pok.common.paths import project_root

# ⚠ 여기를 고쳤으면 워크플로 2개도 함께 고치고 manifest를 재생성할 것.
POB_COMMIT = "5d173cbf8c9cf394a975cbb813f19d0b6dc67ea6"


def pob_short() -> str:
    """스냅샷 디렉터리 이름 — `external/pob/<short>`의 그 7자."""
    return POB_COMMIT[:7]


def pob_root(root: Path | None = None) -> Path:
    """스냅샷 클론 루트."""
    return (root or project_root()) / "external" / "pob" / pob_short()


def pob_src_dir(root: Path | None = None) -> Path:
    """스냅샷의 `src/` — LuaJIT을 돌릴 때의 cwd이자 `Data/*.lua`의 부모."""
    return pob_root(root) / "src"
