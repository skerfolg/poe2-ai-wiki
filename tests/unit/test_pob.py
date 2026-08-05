"""pob/ 어댑터 유닛 — LuaJIT 없이 검증 가능한 부분 (직렬화·코덱·프로토콜 파서)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from pok.pob import codec
from pok.pob.buildxml import BuildSpec, GemSpec, SkillGroupSpec, to_xml
from pok.pob.runner import PobRunError, _parse


def _spec(**overrides: object) -> BuildSpec:
    base: dict = {
        "class_name": "Sorceress",
        "ascendancy": "Sorceress1",
        "level": 90,
        "tree_nodes": (4739, 22419),
        "skills": (
            SkillGroupSpec(
                gems=(GemSpec(gem_id="Metadata/Items/Gems/SkillGemSpark", name="Spark", level=20),)
            ),
        ),
    }
    base.update(overrides)
    return BuildSpec(**base)


class TestBuildXml:
    def test_스파이크_계약_속성이_그대로_들어간다(self) -> None:
        root = ET.fromstring(to_xml(_spec()))
        assert root.tag == "PathOfBuilding2"
        build = root.find("Build")
        assert build is not None
        # targetVersion은 빌드 포맷 버전 — "0_1" 이 아니면 Tree/Skills 무증상 유실
        assert build.get("targetVersion") == "0_1"
        assert build.get("characterLevelAutoMode") == "false"
        assert build.get("level") == "90"
        spec_el = root.find("Tree/Spec")
        assert spec_el is not None
        assert spec_el.get("classInternalId") == "7"  # Sorceress
        assert spec_el.get("ascendancyInternalId") == "Sorceress1"
        assert spec_el.get("nodes") == "4739,22419"
        assert spec_el.get("treeVersion") == "0_5"

    def test_젬과_소켓그룹(self) -> None:
        root = ET.fromstring(to_xml(_spec()))
        gem = root.find("Skills/SkillSet/Skill/Gem")
        assert gem is not None
        assert gem.get("gemId") == "Metadata/Items/Gems/SkillGemSpark"
        assert gem.get("level") == "20"

    def test_config_입력_타입별_직렬화(self) -> None:
        spec = _spec(
            config=(
                ("enemyIsBoss", True),
                ("enemyLevel", 84),
                ("customMods", "fire resistance is 75"),
            )
        )
        root = ET.fromstring(to_xml(spec))
        inputs = {i.get("name"): i for i in root.findall("Config/Input")}
        assert inputs["enemyIsBoss"].get("boolean") == "true"
        assert inputs["enemyLevel"].get("number") == "84"
        assert inputs["customMods"].get("string") == "fire resistance is 75"

    def test_모르는_클래스는_거부(self) -> None:
        with pytest.raises(ValueError, match="클래스"):
            to_xml(_spec(class_name="Scion"))  # PoE1 클래스

    def test_레벨_범위_검증(self) -> None:
        with pytest.raises(ValueError, match="레벨"):
            to_xml(_spec(level=0))


class TestCodec:
    def test_왕복(self) -> None:
        xml = to_xml(_spec())
        assert codec.decode(codec.encode(xml)) == xml

    def test_urlsafe_치환과_패딩누락_허용(self) -> None:
        xml = to_xml(_spec())
        code = codec.encode(xml)
        assert "+" not in code and "/" not in code  # PoB 공유 코드 규약
        assert codec.decode(code.rstrip("=")) == xml

    def test_손상_코드는_ValueError(self) -> None:
        with pytest.raises(ValueError, match="빌드코드"):
            codec.decode("이건 코드가 아님")


class TestDriverProtocol:
    STDOUT = (
        "Loading passive tree...\n"
        'POK_META:{"class":"Sorceress","ascendancy":"Stormweaver","level":90,'
        '"allocPoints":2,"allocAscendancy":0,"allocSecondaryAscendancy":0}\n'
        "POK_ALLOC:[4739,22419]\n"
        'POK_JSON:{"Life":1187,"TotalDPS":97.3214}\n'
        "POK_OK\n"
    )

    def test_정상_파싱(self) -> None:
        stats, meta, alloc = _parse(self.STDOUT)
        assert stats["Life"] == 1187
        assert meta["class"] == "Sorceress"
        assert alloc == (4739, 22419)

    def test_OK_없으면_실패(self) -> None:
        with pytest.raises(PobRunError, match="POK_OK 없이"):
            _parse(self.STDOUT.replace("POK_OK\n", ""))

    def test_ERR_라인은_사유를_전달(self) -> None:
        with pytest.raises(PobRunError, match="XML 파일 열기 실패"):
            _parse("POK_ERR:XML 파일 열기 실패: /없는/경로\n")


class TestJewelXml:
    def test_소켓_직렬화(self) -> None:
        from pok.pob.buildxml import JewelSpec

        spec = _spec(
            tree_nodes=(4739, 22419, 61419),
            jewels=(JewelSpec(socket_node_id=61419, text="Rarity: RARE\nJ\nSapphire"),),
        )
        root = ET.fromstring(to_xml(spec))
        socket = root.find("Tree/Spec/Sockets/Socket")
        assert socket is not None
        assert socket.get("nodeId") == "61419"
        assert socket.get("itemId") == "1"  # 일반 아이템 0개 뒤 첫 id
        assert root.find("Items/Item").get("id") == "1"

    def test_소켓이_트리에_없으면_거부(self) -> None:
        from pok.pob.buildxml import JewelSpec

        with pytest.raises(ValueError, match="tree_nodes에 없음"):
            to_xml(_spec(jewels=(JewelSpec(socket_node_id=999, text="Rarity: RARE\nJ\nSapphire"),)))


def test_중첩_스펙_오류가_어디서_무엇이_빠졌는지_말한다() -> None:
    """raw TypeError는 "missing 1 required positional argument: 'gem_id'"만 남긴다.

    어느 젬인지도, 그 값을 어디서 얻는지도 알 수 없어 호출자는 추측으로 재시도한다.
    최상위 키는 이미 친절히 거부하고 있었는데 중첩만 날것이었다(실측 2026-08-05).
    """
    import pytest

    from pok.pob.buildxml import spec_from_dict

    base = {"class_name": "Witch", "ascendancy": "Witch2", "level": 90}
    with pytest.raises(ValueError, match=r"skills\[0\]\.gems\[0\].*gem_id"):
        spec_from_dict({**base, "skills": [{"gems": [{"name": "Bone Blast", "level": 20}]}]})
    with pytest.raises(ValueError, match=r"모르는 키.*lvl"):
        spec_from_dict({**base, "skills": [{"gems": [{"gem_id": "x", "name": "y", "lvl": 20}]}]})
    with pytest.raises(ValueError, match=r"items\[0\].*slot"):
        spec_from_dict({**base, "items": [{"text": "foo"}]})
