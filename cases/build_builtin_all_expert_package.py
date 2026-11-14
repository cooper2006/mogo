"""Build a single expert-package ZIP for all builtin skills (including legacy).

Merges every builtin skill under ``services/chat-api/app/skills_specs/`` into one
installable ``skillhub-expert-package`` archive, matching the format produced by
``build_builtin_expert_package.py`` but additionally including:

- Legacy YAML-spec skills (``research``, ``stock_analysis``) that lack a ``---``
  frontmatter — they get a synthetic one so the runtime can install them.
- ``customer_feedback_triage`` (normally excluded because ``build_skill_zip.py``
  owns its published artifact).
- All other snake_case skills (``blog_article_style_v1`` etc.) are given their
  kebab-case package name in the SKILL.md frontmatter, just like
  ``build_builtin_skill_zips.py`` does.

Usage::

    services/chat-api/venv/bin/python docs/cases/build_builtin_all_expert_package.py
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import re
import sys
import zipfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "services" / "chat-api" / "app" / "skills_specs"
VALIDATOR_PATH = (
    REPO_ROOT / "services" / "chat-api" / "app" / "services"
    / "skill_packages" / "validator.py"
)
OUT_DIR = Path(__file__).resolve().parent / "builtin-skills"
OUT_NAME = "mogo-builtin-skills-all"

LEGACY_YAML = {"research", "stock_analysis"}
SCHEMA_SUFFIX = ".xsd"

BUNDLE_SLUG = "mogo-builtin-skills-all"
BUNDLE_DISPLAY_NAME = "内置技能合集（全量）"
BUNDLE_SUMMARY = (
    "一次性导入全部内置技能：文档处理（Word / Excel / PPT / PDF）、主题工厂，"
    "以及竞品调研、财务分析、舆情监测等分析类技能；含 legacy 格式的 research 与 stock_analysis。"
)
BUNDLE_DESCRIPTION = (
    "需要处理 Office / PDF 文档、为交付物套用主题样式，或做竞品调研、财务分析、"
    "市场情报、舆情监测与报告综合时使用本专家包；包含 legacy research / stock_analysis 技能。"
)
BUNDLE_BODY = """本专家包内含全部内置技能。按用户诉求选择对应的子技能：

- 文档与交付物：`docx`（Word）、`xlsx`（Excel）、`pptx`（演示文稿）、`pdf`（PDF）、`theme-factory`（主题样式）
- 竞品深度调研链：`market-intelligence-v1` → `product-analysis-v1` → `financial-analysis-v1` → `sentiment-monitor-v1` → `report-synthesis-v1`
- 单点分析：`stock-analysis`（个股）、`research`（通用调研，legacy 格式）
- 写作风格约束：`blog-article-style-v1`、`deep-research-report-style-v1`
- 客户反馈分类：`customer-feedback-triage`

先读「Internal child Skill directory」确认各子技能的职责与适用场景，再按需完整读取对应子技能的全部指令。多个子技能可组合使用（例如先调研、再综合、最后套主题出稿）。
"""

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
# Legacy YAML-spec skills have no `---` delimiters: the entire file is one bare
# YAML mapping (no blank-line separator), so parse it whole.
LEGACY_FRONTMATTER = re.compile(r"\A(.*)", re.DOTALL)
EXCLUDED_PARTS = {"__pycache__"}


def load_validator():
    spec = importlib.util.spec_from_file_location("skill_package_validator", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def package_name(skill_dir: Path, meta: dict) -> str:
    """Return the kebab-case install name: packageName > name > dir-name."""
    declared = str(meta.get("packageName") or "").strip()
    if declared:
        return declared
    frontmatter_name = str(meta.get("name") or "").strip()
    if frontmatter_name and frontmatter_name != skill_dir.name:
        return frontmatter_name.replace("_", "-")
    return skill_dir.name.replace("_", "-")


def rewrite_skill_md(skill_dir: Path) -> tuple[str, bytes]:
    """Rewrite SKILL.md frontmatter name to kebab-case, return (name, rewritten_bytes).
    For legacy YAML-spec skills, synthesize a minimal frontmatter."""
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    match = FRONTMATTER.match(text)

    if match:
        raw_meta = match.group(1)
    else:
        # Legacy bare YAML: parse the leading mapping so displayName/description
        # survive into the synthesized frontmatter below.
        legacy = LEGACY_FRONTMATTER.match(text)
        raw_meta = legacy.group(1) if legacy else ""

    try:
        meta = yaml.safe_load(raw_meta) or {}
        if not isinstance(meta, dict):
            meta = {}
    except yaml.YAMLError:
        meta = {}

    slug = package_name(skill_dir, meta)
    version = str(meta.get("version") or "1.0.0").strip()

    if not match:
        # Legacy YAML: synthesize frontmatter
        desc = str(meta.get("description", "")).strip()
        display_name = str(meta.get("displayName") or meta.get("display_name") or "").strip()
        tools_list = [str(t) for t in (meta.get("tools") or [])]
        header = (
            f"name: {slug}\n"
            f"version: {version}\n"
            f"description: {desc or 'Legacy skill'}\n"
            + (f"displayName: {display_name}\n" if display_name else "")
            + "tools:\n"
            + "".join(f"  - {t}\n" for t in tools_list)
        )
        rewritten = f"---\n{header}\n---\n{text}"
        return slug, rewritten.encode("utf-8")

    # Rewrite the name line; keep everything else verbatim
    frontmatter = re.sub(
        r"^name:[^\n]*$", f"name: {slug}", match.group(1), count=1, flags=re.MULTILINE
    )
    rewritten = text[:4] + frontmatter + text[4 + len(match.group(1)):]
    return slug, rewritten.encode("utf-8")


def skill_files(skill_dir: Path, *, exclude_schemas: bool = True) -> list[Path]:
    return sorted(
        p
        for p in skill_dir.rglob("*")
        if p.is_file()
        and not EXCLUDED_PARTS.intersection(p.relative_to(skill_dir).parts)
        and p.suffix != ".pyc"
        and (not exclude_schemas or not p.name.endswith(SCHEMA_SUFFIX))
    )


def build_one(skill_dir: Path, validator, *, exclude_schemas: bool = True) -> tuple[str, int, bytes]:
    """Returns (slug, file_count, zip_bytes)."""
    slug, skill_md_bytes = rewrite_skill_md(skill_dir)
    files = skill_files(skill_dir, exclude_schemas=exclude_schemas)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for path in files:
            rel = path.relative_to(skill_dir).as_posix()
            content = skill_md_bytes if rel == "SKILL.md" else path.read_bytes()
            out.writestr(f"{slug}/{rel}", content)
    zip_bytes = buf.getvalue()

    # Validate
    try:
        validated = validator.validate_skill_zip(zip_bytes)
        warnings_str = ",".join(item["code"] for item in validated.warnings) or "-"
        print(
            f"ok    {validated.name:30s} v{validated.version:<8s} files={len(validated.files):3d} "
            f"zip={len(zip_bytes)//1024:5d}KB model={validated.model_invocable} user={validated.user_invocable} warnings={warnings_str}"
        )
    except validator.SkillPackageError as exc:
        print(f"warn  {slug:30s} validation: {exc.code}: {exc.message}")

    return slug, len(files), zip_bytes


def build_bundle(*, output: Path | None = None, exclude_schemas: bool = True) -> tuple[bytes, list[tuple[str, str, int, bytes]]]:
    sources = sorted(SKILLS_ROOT.iterdir())
    if not sources:
        raise SystemExit(f"no skill dirs in {SKILLS_ROOT}")

    validator = load_validator()
    children: list[tuple[str, str, int, bytes]] = []
    seen: set[str] = set()

    for skill_dir in sources:
        if not (skill_dir / "SKILL.md").exists():
            print(f"skip  {skill_dir.name:30s} no SKILL.md")
            continue
        try:
            slug, file_count, zip_bytes = build_one(skill_dir, validator, exclude_schemas=exclude_schemas)
        except Exception as exc:
            print(f"fail  {skill_dir.name:30s} {exc}")
            continue
        if slug in seen:
            print(f"dup   {slug!r} — skipping {skill_dir.name}")
            continue
        seen.add(slug)
        children.append((slug, skill_dir.name, file_count, zip_bytes))

    slugs = [s for s, *_ in children]
    manifest = {
        "type": "skillhub-expert-package",
        "slug": BUNDLE_SLUG,
        "displayName": BUNDLE_DISPLAY_NAME,
        "summary": BUNDLE_SUMMARY,
        "version": "1.0.0",
        "skillSlugs": slugs,
        "skills": [{"slug": s, "namespace": "builtin"} for s in slugs],
    }
    descriptor = (
        "---\n"
        f"name: {BUNDLE_SLUG}\n"
        f"displayName: {BUNDLE_DISPLAY_NAME}\n"
        f"description: {BUNDLE_DESCRIPTION}\n"
        "version: 1.0.0\n"
        "orchestration:\n"
        "  children:\n"
        + "".join(f"    - {s}\n" for s in slugs)
        + "---\n"
        + BUNDLE_BODY
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr(f"skillsets/{BUNDLE_SLUG}.md", descriptor)
        for slug, _, _, zip_bytes in children:
            archive.writestr(f"skills/{slug}.zip", zip_bytes)
    return buf.getvalue(), children


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a single expert-package ZIP for all builtin skills.")
    parser.add_argument("--out", help="output ZIP path; defaults to builtin-skills/<slug>-<version>.zip")
    parser.add_argument("--keep-schemas", action="store_true", help="keep .xsd schemas (may exceed 256 file cap)")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else OUT_DIR / f"{BUNDLE_SLUG}-1.0.0.zip"

    data, children = build_bundle(output=out_path, exclude_schemas=not args.keep_schemas)

    print(f"\nchildren ({len(children)}):")
    for slug, src, fc, zip_bytes in children:
        print(f"  {slug:30s} {len(zip_bytes) // 1024:5d}KB  from {src} ({fc} files)")

    out_path.write_bytes(data)
    print(f"wrote  {out_path.relative_to(REPO_ROOT)}")
    print(f"total {len(children)} skills in expert package")
    return 0


if __name__ == "__main__":
    sys.exit(main())
