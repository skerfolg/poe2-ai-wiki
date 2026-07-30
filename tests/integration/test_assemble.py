"""engine/assemble 통합 — 조립→검증→계산→기록 전체 파이프라인 (환경 없으면 skip)."""

from __future__ import annotations

import json

import pytest

from pok.engine.assemble import IllegalBuildError, assemble
from pok.pob import codec
from pok.pob.buildxml import BuildSpec, ItemSpec
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")


def test_적법_빌드_조립_기록(tmp_path_factory: pytest.TempPathFactory) -> None:
    spec = BuildSpec(
        class_name="Sorceress",
        ascendancy="Sorceress1",
        tree_nodes=(4739, 22419),
        items=(
            ItemSpec(
                slot="Ring 1",
                text=(
                    "Rarity: RARE\nPok Ring\nIron Ring\nItem Level: 80\n"
                    "Adds 1 to 3 Cold damage to Attacks"
                ),
            ),
        ),
    )
    built = assemble(spec, "smoke-테스트")
    try:
        assert built.is_legal
        assert built.result.stats["Life"] == 1187
        # 기록물: manifest + build.pob(코덱 왕복) + validation.json
        validation = json.loads((built.path / "validation.json").read_text(encoding="utf-8"))
        assert validation["tree"]["legal"] is True
        assert validation["items"]["Ring 1"]["legal"] is True
        xml = (built.path / "build.xml").read_text(encoding="utf-8")
        assert codec.decode(built.build_code) == xml
    finally:
        for f in built.path.iterdir():
            f.unlink()
        built.path.rmdir()  # 테스트 산출물은 남기지 않는다


def test_비합법_아이템은_거부된다() -> None:
    spec = BuildSpec(
        class_name="Sorceress",
        ascendancy="Sorceress1",
        items=(
            ItemSpec(
                slot="Ring 1",
                text="Rarity: RARE\nPok Ring\nIron Ring\nItem Level: 80\n+999% to Pok Resistance",
            ),
        ),
    )
    with pytest.raises(IllegalBuildError, match="Ring 1"):
        assemble(spec, "illegal")
