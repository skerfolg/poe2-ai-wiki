"""동명 베이스의 변종 — 하나만 실으면 베이스 선택이 조용히 틀린다 (백로그 #32)."""

from __future__ import annotations

import pytest

from pok.kb.ingest.base_variants import scan_variants, variant_patch


def _pob_ready() -> bool:
    from pok.kb.pob_pin import pob_src_dir

    return (pob_src_dir() / "Data" / "Bases").is_dir()


needs_pob = pytest.mark.skipif(not _pob_ready(), reason="external/pob 스냅샷 없음")


def test_only_multi_variant_bases_get_the_field() -> None:
    """1,768종 전부에 달면 잡음이다 — **정보가 있는 곳에만** 붙인다."""
    assert variant_patch("X", {"X": ["a"]}) == {}
    assert variant_patch("X", {}) == {}
    assert variant_patch("X", {"X": ["a", "b"]}) == {"implicit_variants": ["a", "b"]}


@needs_pob
def test_scan_finds_the_variants_pob_itself_loses() -> None:
    """PoB는 Lua 테이블이라 **나중 것이 앞의 것을 덮는다** — 원본을 직접 읽는 이유."""
    variants = scan_variants()
    fork = variants["Runemastered Runic Fork"]
    assert len(fork) == 3, fork
    assert any("additional Projectiles" in line for line in fork)
    assert any("Runic Ward" in line for line in fork), "덤프에 남던 유일한 변종"

    multi = {name: lines for name, lines in variants.items() if len(lines) > 1}
    assert len(multi) == 16, f"변종 보유 베이스 {len(multi)}종"


def test_kb_carries_every_variant() -> None:
    """수록돼 있어야 도구가 쓴다 — 베이스 선택을 KB로 가를 수 있는가."""
    from pok.common.paths import knowledge_dir
    from pok.kb.store import load

    store = load(knowledge_dir())
    fork = store.get("item.runemastered-runic-fork").raw["data"]
    assert len(fork["implicit_variants"]) == 3, fork.get("implicit_variants")

    # 보고는 "implicit이 통째로 없다"였지만 **필드 이름 오해**였다 — 단수 `implicit`에
    # 573종이 이미 있었다. 그 사실도 함께 잠가 둔다(다시 "없다"고 판단하지 않게).
    normals = [
        r
        for r in store.records.values()
        if r.type == "Item" and (r.raw.get("data") or {}).get("rarity") == "normal"
    ]
    with_implicit = [r for r in normals if (r.raw.get("data") or {}).get("implicit")]
    assert len(with_implicit) > 500, f"{len(with_implicit)}/{len(normals)}"
    assert store.get("item.attuned-wand").raw["data"]["implicit"]
