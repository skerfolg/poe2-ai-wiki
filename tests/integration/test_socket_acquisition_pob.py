"""실제 PoB가 계산한 소켓 수와 게임에서 획득 가능한 홈 수를 구별한다."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from pok.artifacts import store
from pok.engine.assemble import IllegalBuildError, assemble
from pok.mcp.tools.build import compute_pob
from pok.pob.buildxml import spec_from_dict
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")


def _spec(sockets: int, *, modifier: bool = True) -> dict[str, Any]:
    lines = [
        "Rarity: RARE",
        "Engineered Gloves",
        "Adorned Wraps",
        "Sockets: " + " ".join(["S"] * sockets),
        *["Rune: Perfect Iron Rune"] * sockets,
        "Item Level: 80",
        "Quality: 20",
        "Implicits: 0",
    ]
    if modifier:
        lines.append("{custom}{range:0.5}(15-25)% increased Evasion and Energy Shield")
    lines += [
        "Corrupted",
        *["{rune}20% increased Armour, Evasion and Energy Shield"] * sockets,
    ]
    return {
        "class_name": "Mercenary",
        "ascendancy": "Mercenary3",
        "items": [
            {
                "slot": "Gloves",
                "text": "\n".join(lines),
                "socket_sources": ["exceptional"],
                "derived_from": {
                    "tool": "manual",
                    "why": "사용자 장갑 반례의 고정 입력과 단일 축 대조",
                },
            }
        ],
    }


@pytest.fixture
def isolated_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pok.engine.assemble as module

    monkeypatch.setattr(module, "record_build", partial(store.record_build, root=tmp_path))
    monkeypatch.setattr(module, "new_build_id", partial(store.new_build_id, root=tmp_path))
    monkeypatch.setattr(module, "find_by_hash", partial(store.find_by_hash, root=tmp_path))


def test_public_compute_does_not_mistake_pob_limit_for_obtainable_socket_count() -> None:
    result = compute_pob(_spec(3), ["EnergyShield", "Evasion"])
    assert result["stats"]["EnergyShield"] > 0, "PoB computes the impossible item normally"
    assert result["items_legal"] is True, "the modifier itself is a real corruption modifier"
    assert result["item_sockets_legal"] is False, result
    assert result["item_socket_problems"]


def test_strict_exploration_assembly_refuses_the_v20_combination(
    isolated_artifacts: None,
) -> None:
    with pytest.raises(IllegalBuildError, match="Gloves"):
        assemble(spec_from_dict(_spec(3)), "corruption-socket-conflict", purpose="exploration")


@pytest.mark.parametrize(("sockets", "modifier"), [(2, True), (3, False)])
def test_valid_corruption_routes_remain_importable_and_record_as_legal(
    isolated_artifacts: None, sockets: int, modifier: bool
) -> None:
    source = _spec(sockets, modifier=modifier)
    built = assemble(
        spec_from_dict(source),
        "corruption-socket-valid",
        spec_data=source,
        purpose="exploration",
    )
    validation = json.loads((built.path / "validation.json").read_text(encoding="utf-8"))
    saved = json.loads((built.path / "spec.json").read_text(encoding="utf-8"))
    assert saved["items"][0]["socket_sources"] == ["exceptional"]
    assert built.is_legal
    assert validation["item_sockets"]["legal"] is True
    assert validation["item_sockets"]["problems"] == []
    observed = validation["item_sockets"]["observed"]
    assert any(row["slot"] == "Gloves" and row["sockets"] == sockets for row in observed)
    result = compute_pob(source, ["EnergyShield", "Evasion"])
    assert result["item_sockets_legal"] is True
    for key in ("EnergyShield", "Evasion"):
        assert result["stats"][key] == built.result.stats[key]
