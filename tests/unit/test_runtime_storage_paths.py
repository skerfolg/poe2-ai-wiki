"""Configured writable storage preserves resource roots and explicit-root precedence."""

import pytest

from pok.common import paths


@pytest.fixture
def resource(tmp_path, monkeypatch):
    root = tmp_path / "resource"
    root.mkdir()
    monkeypatch.setattr(paths, "project_root", lambda: root)
    monkeypatch.delenv("POK_DATA_HOME", raising=False)
    monkeypatch.delenv("POK_CACHE_HOME", raising=False)
    return root


def test_unset_environment_retains_project_layout(resource):
    assert paths.artifacts_dir() == resource / "artifacts"
    assert paths.var_dir() == resource / "var"
    assert paths.index_db_path() == resource / "var/index.sqlite"


def test_data_and_cache_are_independent_of_read_only_resources(resource, tmp_path, monkeypatch):
    data, cache = tmp_path / "data", tmp_path / "cache"
    monkeypatch.setenv("POK_DATA_HOME", str(data))
    monkeypatch.setenv("POK_CACHE_HOME", str(cache))
    assert paths.artifacts_dir() == data / "artifacts"
    assert paths.var_dir() == cache
    assert paths.index_db_path() == cache / "index.sqlite"
    assert paths.knowledge_dir() == resource / "knowledge"
    assert paths.schema_dir() == resource / "knowledge/schema"
    assert not (resource / "artifacts").exists() and not (resource / "var").exists()
    assert paths.runtime_paths() == {
        "resource_root": str(resource),
        "artifacts_root": str(data / "artifacts"),
        "cache_root": str(cache),
    }


def test_explicit_root_takes_precedence_even_over_invalid_environment(
    resource, tmp_path, monkeypatch
):
    monkeypatch.setenv("POK_DATA_HOME", "relative")
    monkeypatch.setenv("POK_CACHE_HOME", "")
    explicit = tmp_path / "explicit"
    assert paths.artifacts_dir(explicit) == explicit / "artifacts"
    assert paths.var_dir(explicit) == explicit / "var"


@pytest.mark.parametrize("configured", ["POK_DATA_HOME", "POK_CACHE_HOME"])
def test_each_setting_can_be_enabled_independently(resource, tmp_path, monkeypatch, configured):
    selected = tmp_path / "selected"
    monkeypatch.setenv(configured, str(selected))
    assert (
        paths.artifacts_dir()
        == (selected if configured == "POK_DATA_HOME" else resource) / "artifacts"
    )
    assert paths.var_dir() == (selected if configured == "POK_CACHE_HOME" else resource / "var")


@pytest.mark.parametrize(
    "key,function", [("POK_DATA_HOME", paths.artifacts_dir), ("POK_CACHE_HOME", paths.var_dir)]
)
@pytest.mark.parametrize("value", ["", " ", "relative/folder"])
def test_invalid_configuration_never_falls_back_to_resources(
    resource, monkeypatch, key, function, value
):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match=key):
        function()
    assert not list(resource.iterdir())


@pytest.mark.parametrize(
    "key,function", [("POK_DATA_HOME", paths.artifacts_dir), ("POK_CACHE_HOME", paths.var_dir)]
)
def test_non_directory_failure_does_not_redirect_to_project(
    resource, tmp_path, monkeypatch, key, function
):
    file = tmp_path / "file"
    file.write_text("retain", encoding="utf-8")
    monkeypatch.setenv(key, str(file))
    with pytest.raises(OSError):
        function()
    assert file.read_text(encoding="utf-8") == "retain"
    assert not list(resource.iterdir())
