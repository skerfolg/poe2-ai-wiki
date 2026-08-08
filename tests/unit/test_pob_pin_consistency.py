"""PoB 스냅샷 핀이 **손으로 고치는 자리 셋**에서 갈라지지 않는지 (백로그 #16).

핀은 원래 8곳에 복사돼 있었다. 하나만 빠뜨리면 계산은 새 스냅샷으로 돌고 카탈로그
검증은 옛 파일을 읽어 **증거 체인(AD-2)이 조용히 거짓**이 된다.

지금은 소스 파생이 `pok.kb.pob_pin.POB_COMMIT` 하나에서 나온다. 남은 수기 자리는
셋이고, 파이썬 밖이거나 생성 시점이 달라 자동 파생이 안 되는 것들이다:

| 자리 | 왜 남았나 | 어긋나면 |
|---|---|---|
| `pob_pin.POB_COMMIT` | **authoring point** | — |
| `.github/workflows/{ci,pob-smoke}.yml` | YAML은 파이썬을 못 읽는다 | CI가 다른 PoB로 검증 |
| `knowledge/ingest/manifest.json` | `ingest manifest`가 쓰는 **생성물** | 런타임이 딴 스냅샷 |

manifest는 상수를 고친 뒤 재생성해야 갱신된다(`python -m pok.kb.ingest manifest
--patch <ver>`). 그 재생성을 잊는 것이 실제 실패 모드라, 여기서 대조한다.

⛔ `knowledge/game-data/**`의 `sources[].pob`는 대상이 아니다. 그건 그 레코드를
**언제 어느 커밋에서 긁었는가**의 증거라, 스냅샷을 올렸다고 덮으면 계보가 거짓이 된다.
"""

from __future__ import annotations

import re

from pok.common.paths import project_root
from pok.kb.ingest import ailments, merge
from pok.kb.pob_pin import POB_COMMIT, pob_short, pob_src_dir
from pok.pob import catalog
from pok.pob.versions import pinned_commit

_WORKFLOWS = (".github/workflows/ci.yml", ".github/workflows/pob-smoke.yml")


def test_런타임이_읽는_manifest가_상수와_같다() -> None:
    """상수만 고치고 `ingest manifest`를 안 돌리면 여기서 걸린다.

    `resolve_snapshot()`이 여는 스냅샷은 manifest가 정한다 — 갈라지면 계산과
    카탈로그 검증이 다른 PoB를 본다.
    """
    assert pinned_commit() == POB_COMMIT, (
        "manifest.json의 pob_commit이 pob_pin.POB_COMMIT과 다르다 — "
        "`python -m pok.kb.ingest manifest --patch <ver>`로 재생성할 것"
    )


def test_소스_파생이_한_곳에서_나온다() -> None:
    """상수를 복사한 모듈이 다시 생기지 않았는지 — 파생이면 자동으로 통과한다."""
    assert POB_COMMIT == merge.POB_COMMIT, "kb/ingest/merge.py"
    assert pob_src_dir() == catalog.pob_src(), "pob/catalog.py"
    assert pob_src_dir() == ailments.pob_src(), "kb/ingest/ailments.py"


def test_워크플로가_같은_커밋을_가리킨다() -> None:
    root = project_root()
    for rel in _WORKFLOWS:
        text = (root / rel).read_text(encoding="utf-8")
        found = re.findall(r"POB_COMMIT:\s*([0-9a-f]{40})", text)
        assert found, f"{rel}: POB_COMMIT을 못 찾았다"
        assert set(found) == {POB_COMMIT}, f"{rel}: {found} ≠ {POB_COMMIT}"


def test_옛_커밋이_소스에_남아_있지_않다() -> None:
    """ "고쳤다"는 착각을 막는다 — 잔존 핀은 조용히 통과하기 때문이다.

    `external/pob/<sha>` 꼴 경로를 소스·워크플로에서 훑는다. `knowledge/`와
    주석 안의 서술("실측 2026-07-30, PoB 5d173cb")은 **그때의 기록**이라 대상 밖이다.
    """
    root = project_root()
    short = pob_short()
    stray: list[str] = []
    for path in sorted((root / "src").rglob("*.py")):
        for found in re.findall(r"external/pob/([0-9a-f]{7,40})", path.read_text(encoding="utf-8")):
            if not POB_COMMIT.startswith(found):
                stray.append(f"{path.relative_to(root)}: {found}")
    for rel in _WORKFLOWS:
        text = (root / rel).read_text(encoding="utf-8")
        for found in re.findall(r"external/pob/([0-9a-f]{7,40})", text):
            if not POB_COMMIT.startswith(found):
                stray.append(f"{rel}: {found}")
    assert not stray, f"현재 핀({short})과 다른 PoB 커밋이 남아 있다: {stray}"
