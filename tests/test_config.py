"""Tests for tools.yml configuration loader."""

from pathlib import Path

import pytest

from predict_structure.config import (
    get_tools,
    get_tool_config,
    get_image_uri,
    get_image_scheme,
    get_docker_image,
    get_command,
    get_cwl_path,
    WORKSPACE_ROOT,
)


class TestConfigLoader:
    def test_loads_all_tools(self):
        tools = get_tools()
        assert set(tools) == {"boltz", "chai", "alphafold", "esmfold", "openfold"}

    def test_each_tool_has_image(self):
        for tool in get_tools():
            uri = get_image_uri(tool)
            assert "://" in uri, f"{tool} image URI missing scheme: {uri}"

    def test_each_tool_has_cwl(self):
        for tool in get_tools():
            cfg = get_tool_config(tool)
            assert "cwl" in cfg, f"{tool} missing 'cwl' key"

    def test_each_tool_has_command(self):
        for tool in get_tools():
            cmd = get_command(tool)
            assert len(cmd) >= 1, f"{tool} has empty command"
            assert cmd[0].startswith("/"), f"{tool} command should be absolute path: {cmd[0]}"

    def test_unknown_tool_raises(self):
        with pytest.raises(KeyError, match="Unknown tool"):
            get_tool_config("nonexistent")


class TestImageHelpers:
    def test_docker_scheme(self):
        assert get_image_scheme("boltz") == "docker"

    def test_get_docker_image_strips_prefix(self):
        img = get_docker_image("boltz")
        assert not img.startswith("docker://")
        assert "boltz" in img

    def test_get_docker_image_all_tools(self):
        for tool in get_tools():
            img = get_docker_image(tool)
            assert "/" in img  # registry/image format

    def test_docker_image_for_file_uri_raises(self, tmp_path):
        """get_docker_image raises if tool has a file:// URI."""
        import os
        import yaml

        config = {
            "tools": {
                "test_tool": {
                    "image": "file:///path/to/image.sif",
                    "cwl": "test.cwl",
                }
            }
        }
        cfg_path = tmp_path / "test_config.yml"
        cfg_path.write_text(yaml.dump(config))

        os.environ["PREDICT_STRUCTURE_CONFIG"] = str(cfg_path)
        try:
            from predict_structure.config import _load_config
            _load_config.cache_clear()

            with pytest.raises(ValueError, match="not a Docker image"):
                get_docker_image("test_tool")
        finally:
            del os.environ["PREDICT_STRUCTURE_CONFIG"]
            _load_config.cache_clear()


class TestCWLHelpers:
    def test_cwl_paths_are_absolute(self):
        for tool in get_tools():
            path = get_cwl_path(tool)
            assert path.is_absolute()

    def test_cwl_paths_exist(self):
        for tool in get_tools():
            path = get_cwl_path(tool)
            assert path.exists(), f"CWL for '{tool}' not found at {path}"

    def test_workspace_root_exists(self):
        assert WORKSPACE_ROOT.is_dir()
