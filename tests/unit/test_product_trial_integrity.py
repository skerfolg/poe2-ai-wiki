"""Frozen bytes, source additions and explicit shared junction boundaries."""

import hashlib
import importlib
import os
from pathlib import Path

import pytest


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "skills/build-generation")
    )
    return importlib.import_module("product_integrity")


def link_directory(target, link):
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def test_manifest_bytes_are_pinned_before_parsing(module, tmp_path):
    path = tmp_path / "manifest.json"
    original = b'{"files":{}}'
    path.write_bytes(original)
    assert module.load_pinned_json(path, sha(original)) == {"files": {}}
    path.write_bytes(b'{"files":{"changed":"value"}}')
    with pytest.raises(ValueError, match="checksum"):
        module.load_pinned_json(path, sha(original))


@pytest.mark.parametrize(
    "name",
    [
        "../source.py",
        "/absolute",
        "src/../other",
        "src\\other",
        "C:/data",
        ".",
        "src//a.py",
        "src/",
        "a\x00b",
    ],
)
def test_manifest_paths_cannot_change_scope(module, name):
    with pytest.raises(ValueError):
        module.relative_name(name)


def test_changed_missing_and_added_sources_are_reported(module, tmp_path):
    root = tmp_path / "product"
    (root / "src").mkdir(parents=True)
    (root / "src/original.py").write_bytes(b"original")
    expected = {"src/original.py": sha(b"original")}
    assert (
        module.verify_files(root, expected, shared_roots={}, inventory_roots=["src"])["status"]
        == "verified"
    )
    (root / "src/original.py").write_bytes(b"changed")
    (root / "src/extra.py").write_bytes(b"new input")
    report = module.verify_files(root, expected, shared_roots={}, inventory_roots=["src"])
    assert {row["code"] for row in report["diagnostics"]} >= {"FILE_CHANGED", "UNEXPECTED_FILE"}
    (root / "src/original.py").unlink()
    report = module.verify_files(root, expected, shared_roots={}, inventory_roots=["src"])
    assert {row["code"] for row in report["diagnostics"]} >= {
        "FILE_UNAVAILABLE",
        "INVENTORY_FILE_MISSING",
    }


def test_only_exact_declared_shared_target_is_accepted(module, tmp_path):
    product, shared, other = (tmp_path / name for name in ("product", "shared", "other"))
    shared.mkdir()
    other.mkdir()
    (shared / "data.lua").write_bytes(b"fixed data")
    (other / "data.lua").write_bytes(b"fixed data")
    link_directory(shared, product / "external/pob")
    expected = {"external/pob/data.lua": sha(b"fixed data")}
    assert (
        module.verify_files(
            product,
            expected,
            shared_roots={"external/pob": shared},
            inventory_roots=["external/pob"],
        )["status"]
        == "verified"
    )
    denied = module.verify_files(
        product, expected, shared_roots={}, inventory_roots=["external/pob"]
    )
    assert denied["status"] == "unverified"
    wrong = module.verify_files(
        product, expected, shared_roots={"external/pob": other}, inventory_roots=["external/pob"]
    )
    assert wrong["status"] == "unverified", "Equal bytes cannot disguise an unexpected mapping"
    (shared / "extra.lua").write_bytes(b"new source")
    extra = module.verify_files(
        product, expected, shared_roots={"external/pob": shared}, inventory_roots=["external/pob"]
    )
    assert any(row["code"] == "UNEXPECTED_FILE" for row in extra["diagnostics"])


def test_undeclared_nested_link_does_not_hide_extra_source(module, tmp_path):
    product, outside = tmp_path / "product", tmp_path / "outside"
    (product / "src").mkdir(parents=True)
    outside.mkdir()
    (outside / "shadow.py").write_bytes(b"unapproved")
    link_directory(outside, product / "src/redirect")
    report = module.verify_files(product, {}, shared_roots={}, inventory_roots=["src"])
    assert any(row["code"] == "UNDECLARED_LINK" for row in report["diagnostics"])


def test_generated_cache_is_not_promoted_to_source_truth(module, tmp_path):
    (tmp_path / "src/__pycache__").mkdir(parents=True)
    (tmp_path / "src/source.py").write_bytes(b"source")
    (tmp_path / "src/__pycache__/source.pyc").write_bytes(b"derived cache")
    report = module.verify_files(
        tmp_path, {"src/source.py": sha(b"source")}, shared_roots={}, inventory_roots=["src"]
    )
    assert report["status"] == "verified"
