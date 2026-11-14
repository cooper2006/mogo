"""Build installable Skill ZIPs for the repo's builtin skills.

``services/chat-api/app/skills_specs/`` holds the builtin skills as code-layer assets:
they are never seeded or synced into MongoDB, so they do not show up in the user-web
"select a Skill" picker. The supported UI entry is the ZIP install channel
(admin-web -> Skill 管理 -> POST /organization-skills/install-zip).

For every builtin skill this script:

1. packages the whole directory, skipping ``__pycache__`` / ``*.pyc``,
2. rewrites the SKILL.md frontmatter ``name`` to its kebab-case package name, because
   the runtime validator (``app/services/skill_packages/validator.py``) enforces
   ``^[a-z0-9](?:[a-z0-9-]{0,125}[a-z0-9])?$`` while most repo ids are snake_case
   (``packageName`` in the frontmatter wins when present),
3. validates the produced archive with that same validator, loaded straight from its
   file so no chat-api package import is needed (requires PyYAML),
4. writes ``docs/cases/builtin-skills/<package-name>-<version>.zip``.

``customer_feedback_triage`` is excluded because ``build_skill_zip.py`` already owns its
published artifact. ``research`` and ``stock_analysis`` are skipped: their SKILL.md is a
legacy YAML spec without ``---`` frontmatter or an instruction body, so the validator
rejects them as ``missing_frontmatter`` / ``empty_skill_body``.

Usage::

    services/chat-api/venv/bin/python docs/cases/build_builtin_skill_zips.py
    services/chat-api/venv/bin/python docs/cases/build_builtin_skill_zips.py --skills docx,xlsx
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import zipfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "services" / "chat-api" / "app" / "skills_specs"
VALIDATOR_PATH = REPO_ROOT / "services" / "chat-api" / "app" / "services" / "skill_packages" / "validator.py"
OUT_DIR = Path(__file__).resolve().parent / "builtin-skills"

ALREADY_PACKAGED = {"customer_feedback_triage"}
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
EXCLUDED_PARTS = {"__pycache__"}


def load_validator():
    spec = importlib.util.spec_from_file_location("skill_package_validator", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves the defining module through sys.modules, so register it first.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def package_name(skill_dir: Path, meta: dict) -> str:
    declared = str(meta.get("packageName") or "").strip()
    return declared or skill_dir.name.replace("_", "-")


def packaged_skill_md(skill_dir: Path) -> tuple[str, dict, bytes]:
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    match = FRONTMATTER.match(text)
    if not match:
        raise ValueError("SKILL.md has no '---' frontmatter (legacy YAML spec, not a DSH skill)")
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValueError("SKILL.md frontmatter is not a mapping")
    name = package_name(skill_dir, meta)
    # Rewrite only the name line inside the frontmatter; keep everything else verbatim.
    frontmatter = re.sub(r"^name:[^\n]*$", f"name: {name}", match.group(1), count=1, flags=re.MULTILINE)
    rewritten = text[:4] + frontmatter + text[4 + len(match.group(1)) :]
    return name, meta, rewritten.encode("utf-8")


def skill_files(skill_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in skill_dir.rglob("*")
        if path.is_file()
        and not EXCLUDED_PARTS.intersection(path.relative_to(skill_dir).parts)
        and path.suffix != ".pyc"
    )


def build_one(skill_dir: Path, validator) -> tuple[bool, str]:
    try:
        name, meta, skill_md = packaged_skill_md(skill_dir)
    except (ValueError, yaml.YAMLError) as exc:
        return False, f"skip  {skill_dir.name:30s} {exc}"
    version = str(meta.get("version") or "").strip() or "1.0.0"
    out_path = OUT_DIR / f"{name}-{version}.zip"
    files = skill_files(skill_dir)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(skill_dir).as_posix()
            data = skill_md if relative == "SKILL.md" else path.read_bytes()
            archive.writestr(f"{name}/{relative}", data)
    archive_bytes = out_path.read_bytes()
    try:
        validated = validator.validate_skill_zip(archive_bytes)
    except validator.SkillPackageError as exc:
        return False, f"FAIL  {name:30s} {exc.code}: {exc.message}"
    expanded = sum(item["size"] for item in validated.files)
    warnings = ",".join(item["code"] for item in validated.warnings) or "-"
    return True, (
        f"ok    {validated.name:30s} v{validated.version:<8s} files={len(validated.files):3d} "
        f"zip={len(archive_bytes) // 1024:5d}KB expanded={expanded // 1024:5d}KB "
        f"model={validated.model_invocable} user={validated.user_invocable} warnings={warnings}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build installable ZIPs for the builtin skills.")
    parser.add_argument("--skills", help="comma separated directory names; defaults to every builtin skill")
    args = parser.parse_args()

    if args.skills:
        selected = [SKILLS_ROOT / item.strip() for item in args.skills.split(",") if item.strip()]
    else:
        selected = sorted(path for path in SKILLS_ROOT.iterdir() if path.is_dir())

    validator = load_validator()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0
    built = 0
    for skill_dir in selected:
        if not (skill_dir / "SKILL.md").exists():
            print(f"skip  {skill_dir.name:30s} no SKILL.md")
            failures += 1
            continue
        if not args.skills and skill_dir.name in ALREADY_PACKAGED:
            print(f"skip  {skill_dir.name:30s} already published by build_skill_zip.py")
            continue
        ok, message = build_one(skill_dir, validator)
        print(message)
        if ok:
            built += 1
        else:
            failures += 1
    print(f"\nbuilt {built} ZIP(s) into {OUT_DIR.relative_to(REPO_ROOT)}; {failures} not packaged")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
