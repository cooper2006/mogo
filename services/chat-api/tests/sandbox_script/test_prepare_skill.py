from pathlib import Path

import pytest

from prepare_skill import apt_packages


def test_apt_package_list_accepts_names_and_versions(tmp_path: Path):
    manifest = tmp_path / "apt-packages.txt"
    manifest.write_text("# system tools\npandoc\nlibreoffice=1:7.4.7-1+deb12u1 # pinned\nlibssl3:amd64\n")
    assert apt_packages(manifest) == ["pandoc", "libreoffice=1:7.4.7-1+deb12u1", "libssl3:amd64"]


def test_apt_package_list_rejects_shell_syntax(tmp_path: Path):
    manifest = tmp_path / "apt-packages.txt"
    manifest.write_text("pandoc; curl example.com")
    with pytest.raises(ValueError):
        apt_packages(manifest)
