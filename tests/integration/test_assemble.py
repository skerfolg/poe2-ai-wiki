"""engine/assemble 통합 — 조립→검증→계산→기록 전체 파이프라인 (환경 없으면 skip)."""

from __future__ import annotations

import json

import pytest

from pok.engine.assemble import IllegalBuildError, assemble
from pok.pob import codec
from pok.pob.buildxml import BuildSpec, ItemSpec, spec_from_dict, to_xml
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
        # 재사용 스펙도 실제 계산한 XML과 같아야 한다 — 공유 코드 복원은 손실 경로다.
        saved = json.loads((built.path / "spec.json").read_text(encoding="utf-8"))
        resumed = spec_from_dict(saved)
        assert to_xml(resumed) == to_xml(spec)
        # 기록물: manifest + build.pob(코덱 왕복) + validation.json
        validation = json.loads((built.path / "validation.json").read_text(encoding="utf-8"))
        assert validation["tree"]["legal"] is True
        assert validation["items"]["Ring 1"]["legal"] is True
        assert validation["item_editor"]["checked"] is True
        assert validation["item_editor"]["compatible"] is True
        assert len(validation["item_editor"]["items"]) == 1
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


def _sockets_spec(
    sockets: int, *, exceptional: bool = False, corrupted: bool = False, runic: bool = False
) -> BuildSpec:
    """일반 1홈 장갑. 추가 홈의 드롭·타락·트리 경로는 각각 명시한다."""
    runes = "\n".join(["Rune: Perfect Iron Rune"] * sockets)
    return BuildSpec(
        class_name="Monk" if runic else "Sorceress",
        ascendancy="Monk1" if runic else "Sorceress1",
        tree_nodes=(20437, 39552) if runic else (),
        items=(
            ItemSpec(
                slot="Gloves",
                text=(
                    "Rarity: RARE\nPok Gloves\nFists of Stone\nItem Level: 80\n"
                    + ("Corrupted\n" if corrupted else "")
                    + f"Sockets: {' '.join('S' for _ in range(sockets))}\n{runes}"
                ),
                socket_sources=("exceptional",) if exceptional else (),
            ),
        ),
    )


def test_PoB가_못_여는_소켓_수는_거부된다() -> None:
    """#120 — 사용자 신고 빌드의 결함. 계산은 통과하고 **상세보기에서만** 터졌다.

    막는 근거는 인게임 가부가 아니라 **PoB의 표현 한계**다(룬 드롭다운 6개). 열어 볼
    수 없는 빌드 코드를 출고하는 것은 산출물이 아니다.
    """
    from pok.engine.item_sockets import audit_item_sockets

    text = "Rarity: UNIQUE\nMorior Invictus\nGrand Regalia\nCorrupted\nSockets: S S S S S S S"
    source = {
        "class_name": "Monk",
        "ascendancy": "Monk1",
        "tree_nodes": [20437, 39552],
        "items": [{"slot": "Body Armour", "text": text}],
    }
    checked = audit_item_sockets(source)
    assert checked["items"][0]["budget"] == 7, "고정 4홈 + 트리 2홈 + 타락 1홈의 경로는 성립한다"
    assert all("PoB" in problem for problem in checked["problems"]), checked
    spec = BuildSpec(
        class_name="Monk",
        ascendancy="Monk1",
        tree_nodes=(20437, 39552),
        items=(ItemSpec(slot="Body Armour", text=text),),
    )
    with pytest.raises(IllegalBuildError, match=r"PoB.*표현"):
        assemble(spec, "socket-unrenderable")


@pytest.mark.parametrize("sockets", [3, 4])
def test_추가_홈_획득_경로를_생략하면_거부한다(sockets: int) -> None:
    """PoB의 베이스 socketLimit=3은 일반 제작 예산을 증명하지 않는다 (#192)."""
    with pytest.raises(IllegalBuildError, match=r"Gloves.*획득 가능한"):
        assemble(_sockets_spec(sockets), "socket-missing-acquisition")


@pytest.mark.parametrize(("sockets", "runic"), [(3, False), (4, True)])
def test_획득_경로가_있으면_홈을_줄이지_않고_조립한다(sockets: int, runic: bool) -> None:
    """게이트가 **정상을 막으면** 신호가 죽는다(BACKLOG 형태 ⑤ · ⑪)."""
    built = assemble(
        _sockets_spec(sockets, exceptional=True, corrupted=True, runic=runic), "socket-ok"
    )
    try:
        assert built.result.is_item_sockets_legal
        validation = json.loads((built.path / "validation.json").read_text(encoding="utf-8"))
        assert validation["item_sockets"]["legal"] is True
        assert not validation["item_sockets"]["warnings"]
        acquisition = validation["item_sockets"]["acquisition"]["items"][0]
        assert acquisition["ordinary_limit"] == 1
        assert acquisition["exceptional_grant"] == 1
        assert acquisition["corruption_socket_allowance"] == 1
        assert acquisition["tree_grant"] == int(runic)
        # 관측을 **기록에 남긴다** — 나중에 보는 쪽이 몇 칸으로 쟀는지 알아야 한다
        observed = validation["item_sockets"]["observed"]
        assert observed and observed[0]["sockets"] == sockets and observed[0]["limit"] == 3
    finally:
        for f in built.path.iterdir():
            f.unlink()
        built.path.rmdir()
