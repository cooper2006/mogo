"""Path bootstrap for the sandbox-script unit tests.

``tests/sandbox_script/test_prepare_skill.py`` imports ``prepare_skill`` (which
lives in ``services/chat-api/sandbox_script/``) as a top-level module. That only
resolves when ``sandbox_script/`` is on ``sys.path`` — which is what the
runtime Docker image's ``PYTHONPATH`` provides, but not what a bare
``python -m pytest`` in CI / a host venv / a freshly built test image gives
you.

Registering the directory here (rather than editing the test's import to a
package path, or demanding an external ``PYTHONPATH``) keeps the fix local to
this test folder, so the same test file runs unchanged in every environment.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_SANDBOX_SCRIPT = Path(__file__).resolve().parents[2] / "sandbox_script"

if _REPO_SANDBOX_SCRIPT.is_dir() and str(_REPO_SANDBOX_SCRIPT) not in sys.path:
    sys.path.insert(0, str(_REPO_SANDBOX_SCRIPT))
