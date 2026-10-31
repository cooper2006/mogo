from __future__ import annotations

import io
import zipfile

import pytest

from app.execution_isolation.skill_bundle import SkillBundle, cache_skill_bundle, stage_skill_bundle
from app.services.skill_packages.validator import SkillPackageError, validate_skill_zip


def make_archive(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_packaged_skill_resources_are_staged_for_one_job(tmp_path):
    files = {
        "ppt-master/SKILL.md": "---\nname: ppt-master\ndescription: Create slides\n---\nUse templates.\n",
        **{f"ppt-master/templates/layout-{index}.txt": f"layout {index}" for index in range(300)},
    }
    data = make_archive(files)
    validated = validate_skill_zip(data)
    assert len(validated.files) == 301
    skill_dir = stage_skill_bundle(SkillBundle("ppt-master", validated.root_prefix, data), tmp_path)
    assert (skill_dir / "templates/layout-299.txt").read_text() == "layout 299"
    assert skill_dir == tmp_path / "skill/ppt-master"


def test_staging_rejects_untrusted_archive_paths(tmp_path):
    data = make_archive({
        "SKILL.md": "---\nname: test-skill\ndescription: Test\n---\nBody\n",
        "../escape.txt": "outside",
    })
    with pytest.raises(SkillPackageError) as raised:
        stage_skill_bundle(SkillBundle("test-skill", "", data), tmp_path)
    assert raised.value.code == "unsafe_archive_path"
    assert not (tmp_path / "escape.txt").exists()


def test_immutable_cache_reuses_package_without_reextracting(tmp_path, monkeypatch):
    data = make_archive({
        "SKILL.md": "---\nname: test-skill\ndescription: Test\n---\nBody\n",
        "templates/layout.txt": "first",
    })
    bundle = SkillBundle("test-skill", "", data)
    first = cache_skill_bundle(bundle, tmp_path)
    def fail_extract(*_args):
        raise AssertionError("cache hit must not extract the archive")
    monkeypatch.setattr("app.execution_isolation.skill_bundle.stage_skill_bundle", fail_extract)
    assert cache_skill_bundle(bundle, tmp_path) == first
    assert cache_skill_bundle(SkillBundle("test-skill", "", None, first), tmp_path) == first
    assert (tmp_path / "skill-cache" / first / "templates/layout.txt").read_text() == "first"


def test_repository_repack_keeps_script_executable_bit(tmp_path):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("repo/skills/sample/SKILL.md", "---\nname: sample\ndescription: Test\n---\nBody\n")
        executable = zipfile.ZipInfo("repo/skills/sample/scripts/run.sh")
        executable.create_system = 3
        executable.external_attr = 0o100755 << 16
        archive.writestr(executable, "#!/bin/sh\necho ok\n")
    package = validate_skill_zip(output.getvalue())
    root = stage_skill_bundle(SkillBundle(package.name, package.root_prefix, package.archive_bytes), tmp_path)
    assert (root / "scripts/run.sh").stat().st_mode & 0o111
