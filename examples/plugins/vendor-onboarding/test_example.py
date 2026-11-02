from pathlib import Path


def test_plugin_manifest_is_present() -> None:
    folder = Path(__file__).resolve().parent
    assert (folder / "plugin.yaml").is_file()
    assert (folder / "example.yaml").is_file()
