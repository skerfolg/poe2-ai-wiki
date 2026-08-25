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


def _sockets_spec(sockets: int) -> BuildSpec:
    """`Fists of Stone`(베이스 한도 3)에 소켓을 원하는 만큼 박은 장갑 한 짝."""
    runes = "\n".join(["Rune: Perfect Iron Rune"] * sockets)
    return BuildSpec(
        class_name="Sorceress",
        ascendancy="Sorceress1",
        items=(
            ItemSpec(
                slot="Gloves",
                text=(
                    "Rarity: RARE\nPok Gloves\nFists of Stone\nItem Level: 80\n"
                    f"Sockets: {' '.join('S' for _ in range(sockets))}\n{runes}"
                ),
            ),
        ),
    )


def test_PoB가_못_여는_소켓_수는_거부된다() -> None:
    """#120 — 사용자 신고 빌드의 결함. 계산은 통과하고 **상세보기에서만** 터졌다.

    막는 근거는 인게임 가부가 아니라 **PoB의 표현 한계**다(룬 드롭다운 6개). 열어 볼
    수 없는 빌드 코드를 출고하는 것은 산출물이 아니다.
    """
    with pytest.raises(IllegalBuildError, match="표현하지 못한다"):
        assemble(_sockets_spec(7), "socket-unrenderable")


def test_예산을_넘겨도_막지_않는다() -> None:
    """사용자 판정 2026-08-25: *물리적으로 불가능한 게 아니면 허용한다.*

    `Fists of Stone`은 베이스 3칸인데 4칸을 적었다 — 마셜 아티스트 `Runic
    Meridians`나 타락이면 정상이다. 실측 2026-08-25: 베이스 한도로 막았더니 신고
    빌드 4건 중 **3건이 거짓 거부**였다. 막지 않되 **기록에는 남긴다**.
    """
    built = assemble(_sockets_spec(4), "socket-over-budget")
    try:
        assert built.result.is_item_sockets_legal, "예산 초과는 차단 사유가 아니다"
        validation = json.loads((built.path / "validation.json").read_text(encoding="utf-8"))
        assert validation["item_sockets"]["warnings"], "조용히 넘기지도 않는다"
    finally:
        for f in built.path.iterdir():
            f.unlink()
        built.path.rmdir()


def test_예산_안이면_아무_말도_안_한다() -> None:
    """게이트가 **정상을 막으면** 신호가 죽는다(BACKLOG 형태 ⑤ · ⑪)."""
    built = assemble(_sockets_spec(3), "socket-ok")
    try:
        assert built.result.is_item_sockets_legal
        validation = json.loads((built.path / "validation.json").read_text(encoding="utf-8"))
        assert validation["item_sockets"]["legal"] is True
        assert not validation["item_sockets"]["warnings"]
        # 관측을 **기록에 남긴다** — 나중에 보는 쪽이 몇 칸으로 쟀는지 알아야 한다
        observed = validation["item_sockets"]["observed"]
        assert observed and observed[0]["sockets"] == 3 and observed[0]["limit"] == 3
    finally:
        for f in built.path.iterdir():
            f.unlink()
        built.path.rmdir()
