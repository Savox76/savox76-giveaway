import sys

from savox_giveaway.updater import is_newer_version, platform_slug, release_asset_name


def test_semantic_version_comparison():
    assert is_newer_version("v0.2.0", "0.1.9")
    assert not is_newer_version("v0.1.0", "0.1.0")
    assert not is_newer_version("unbekannt", "0.1.0")


def test_release_asset_matches_current_platform():
    system, architecture = platform_slug()
    assert system in {"windows", "macos", "linux"}
    assert architecture in {"x86_64", "arm64"}
    assert release_asset_name() == f"Savox76Giveaway-{system}-{architecture}.zip"
    if sys.platform == "win32":
        assert "windows" in release_asset_name()
