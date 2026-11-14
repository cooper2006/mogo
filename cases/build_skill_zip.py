"""Build an installable Skill ZIP for the customer_feedback_triage case.

The in-repo builtin skill lives at
``services/chat-api/app/skills_specs/customer_feedback_triage/`` with a
snake_case id (repo convention). The runtime ZIP validator
(``app/services/skill_packages/validator.py``) requires a kebab-case
``name`` in SKILL.md frontmatter, so this script rewrites ``name`` to the
declared ``packageName`` (customer-feedback-triage) in the packaged copy.

Output: docs/cases/customer-feedback-triage-<version>.zip

The ZIP can then be installed from the admin console
(Skill 管理 -> 安装 ZIP -> POST /organization-skills/install-zip) so the
skill shows up in the user-web "选择 Skill -> 企业" picker.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "services" / "chat-api" / "app" / "skills_specs" / "customer_feedback_triage"
OUT_DIR = Path(__file__).resolve().parent

BUNDLE_DIR = "customer-feedback-triage"
INCLUDED = [
    "SKILL.md",
    "templates/triage_report.md",
    "templates/action_items.csv",
    "scripts/severity_heuristics.py",
    "scripts/__init__.py",
    "validation.yaml",
]


def packaged_skill_md() -> tuple[str, bytes]:
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    version = re.search(r"^version:\s*(\S+)", text, re.MULTILINE).group(1)
    # Rewrite the snake_case repo id to the kebab-case package name so the
    # validator's SKILL_NAME check passes. Keep everything else verbatim.
    text = re.sub(r"^name:\s*customer_feedback_triage\s*$",
                  "name: customer-feedback-triage", text, count=1, flags=re.MULTILINE)
    return version, text.encode("utf-8")


def main() -> int:
    version, skill_md_bytes = packaged_skill_md()
    out_path = OUT_DIR / f"{BUNDLE_DIR}-{version}.zip"
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in INCLUDED:
            src = SKILL_ROOT / rel
            if not src.exists():
                print(f"[skip] missing resource: {rel}")
                continue
            data = skill_md_bytes if rel == "SKILL.md" else src.read_bytes()
            zf.writestr(f"{BUNDLE_DIR}/{rel}", data)
    size = out_path.stat().st_size
    print(f"built: {out_path} ({size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
