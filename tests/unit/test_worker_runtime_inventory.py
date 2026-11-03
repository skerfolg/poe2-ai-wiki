"""Production headless inventory follows upstream, never incidental source exports."""

import pytest

from pok.pob import worker_pack


@pytest.fixture
def upstream(tmp_path, monkeypatch):
    root = tmp_path / "pob"
    files = {
        "LICENSE.md": "license",
        "src/HeadlessWrapper.lua": "headless",
        "src/program.lua": "program",
        "src/TreeData/tree.lua": "tree",
        "src/picture.png": "visual",
        "runtime/lua/module.lua": "runtime",
        "src/Export/Bases/Rares.txt": "development export",
    }
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    manifest = """<Version>
<File name="program.lua" part="program"/>
<File name="TreeData/tree.lua" part="tree"/>
<File name="picture.png" part="program"/>
<File name="lua/module.lua" part="runtime" runtime="win32"/>
<File name="missing-other-platform" part="runtime" runtime="osx"/>
<File name="help.txt" part="default"/>
</Version>"""
    (root / "manifest.xml").write_text(manifest, encoding="utf-8")
    tracked = {"manifest.xml", *files}
    monkeypatch.setattr(worker_pack, "_git", lambda root, *args: "\0".join(sorted(tracked)) + "\0")
    return root, tracked


def test_declared_headless_files_only_are_copied(upstream, tmp_path):
    root, _ = upstream
    output = tmp_path / "runtime"
    selected = worker_pack._copy_headless_pob(root, output)
    expected = {
        "manifest.xml",
        "LICENSE.md",
        "src/HeadlessWrapper.lua",
        "src/program.lua",
        "src/TreeData/tree.lua",
        "runtime/lua/module.lua",
    }
    assert set(selected) == expected
    assert {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()} == expected
    assert (output / "src/program.lua").read_bytes() == (root / "src/program.lua").read_bytes()
    assert not (output / "src/Export/Bases/Rares.txt").exists()


def test_missing_required_program_file_is_not_silently_skipped(upstream, tmp_path):
    root, _ = upstream
    (root / "src/program.lua").unlink()
    output = tmp_path / "runtime"
    with pytest.raises(ValueError, match=r"required.*program.lua"):
        worker_pack._copy_headless_pob(root, output)
    assert not output.exists()


def test_untracked_required_resource_is_not_distributed(upstream, tmp_path):
    root, tracked = upstream
    tracked.remove("src/program.lua")
    with pytest.raises(ValueError, match=r"tracked.*program.lua"):
        worker_pack._copy_headless_pob(root, tmp_path / "runtime")


@pytest.mark.parametrize(
    "name",
    [
        "../escape.lua",
        "/absolute.lua",
        "C:/absolute.lua",
        "a//b.lua",
        "a/./b.lua",
        "a\\..\\escape.lua",
    ],
)
def test_invalid_upstream_resource_path_is_rejected(upstream, tmp_path, name):
    root, _ = upstream
    (root / "manifest.xml").write_text(
        f'<Version><File name="{name}" part="program"/></Version>', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="resource path"):
        worker_pack._copy_headless_pob(root, tmp_path / "runtime")


def test_unknown_inventory_part_is_not_guessed(upstream, tmp_path):
    root, _ = upstream
    (root / "manifest.xml").write_text(
        '<Version><File name="program.lua" part="new-required-part"/></Version>', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="part"):
        worker_pack._copy_headless_pob(root, tmp_path / "runtime")
