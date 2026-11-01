"""All migrated native adapters run through owned capture on actual PoB."""

import pytest

from pok.common.execution import ExecutionScope, bind_execution
from pok.pob import item_editor, item_parse_gaps, parse_gaps, roundtrip
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready():
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT or pinned PoB unavailable")
ITEM = (
    "Rarity: RARE\nPoK Capture Probe\nGold Ring\nItem Level: 80\nImplicits: 0\n+10 to maximum Life"
)


@pytest.mark.parametrize("kind", ["roundtrip", "editor", "tree", "item"])
def test_actual_native_adapter_has_confirmed_owned_cleanup(kind):
    scope = ExecutionScope("native-capture-" + kind, 300)
    with bind_execution(scope):
        if kind == "roundtrip":
            result = roundtrip.roundtrip({"probe": ITEM})
            assert result[0].rebuilt and not result[0].error
        elif kind == "editor":
            result = item_editor.audit_item_editor({"probe": ITEM})
            assert result["checked"] and result["compatible"]
        elif kind == "tree":
            result = parse_gaps.dump_tree_parse_gaps()
            assert result.scanned > 0 and result.tree_version != "?"
        else:
            result = item_parse_gaps._probe(
                {"supported": ["+10 to maximum Life"], "unsupported": ["PoKUnknownModifier12345"]},
                item_parse_gaps._PRIMARY_BASE,
                resolve_snapshot(),
                120,
            )
            assert "supported" not in result and "unsupported" in result
    receipt = scope.finish()
    assert receipt["state"] == "completed"
    assert receipt["resources"]
    assert all(row["details"]["status"] == "confirmed" for row in receipt["resources"].values())
