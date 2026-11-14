#!/usr/bin/env python3
"""Python static-correctness gate (stdlib only).

Closes QA R3 leftover #2: the CI gate had no Python static analysis at all —
`compileall` only proves the file parses, and `check_production_wiring.py` only
proves one specific wiring. Three defect classes that parse fine but are wrong
slipped through:

  1. **duplicate ``except`` clauses** — the second handler is dead code; the
     author almost always meant a different exception type.
  2. **duplicate keys in a dict literal** — the first value is silently
     discarded, which is exactly how a typo'd config key becomes a no-op.
  3. **silent broad ``except``** — a handler for ``Exception`` / ``BaseException``
     / bare ``except:`` whose body is only ``pass`` / ``...``.

     This check is a **counted ceiling, not a defect list**. QA R4 audited every
     such block and *deliberately* kept 38 of them (see WORK_LOG "覆盖边界：38 处
     PASS_ONLY 有意不改"): cancellation-swallowing shutdown idioms, expected
     fall-through in chain attempts, and logging infrastructure that would
     recurse if it logged. Freezing the count means a *new* silent broad handler
     must be reviewed rather than slipping in.

     Scoped to *broad* handlers on purpose. A narrow ``except ValueError: pass``
     that falls through to the next parser is normal control flow (see
     ``orchestration/loader.py``); flagging those produced 63 hits of pure noise
     in the first draft of this gate.

Design notes
------------
* **stdlib only** — runs before ``pip install``, like the wiring check.
* **Precise, not noisy** — every check has an explicit negative case in
  ``--self-test``. A checker that fires on correct code is worse than none.
* Deliberately **not** implementing "undefined name": doing that correctly
  needs full scope + builtins analysis. That job belongs to ``pyflakes``,
  which CI runs separately (see quality-gate.yml).

Usage
-----
    python scripts/check_python_static.py app          # scan a tree
    python scripts/check_python_static.py --self-test  # adversarial self-check
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

# Bodies that mean "I swallowed this error and told nobody".
# `...` is an ast.Constant(Ellipsis) expression, not ast.Ellipsis (removed in 3.14).
SKIP_DIRS = {"__pycache__", ".venv", "venv", "node_modules", ".git", "tests"}


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _is_silent_stmt(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and stmt.value.value is Ellipsis
    )


def _exc_key(handler: ast.ExceptHandler) -> tuple[str, ...] | None:
    """A comparable identity for an ``except`` clause, or None if it cannot be
    compared (bare ``except:`` is its own key, never equal to a typed one)."""
    if handler.type is None:
        return ("<bare>",)
    parts: list[str] = []

    def render(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = render(node.value)
            return f"{base}.{node.attr}" if base else None
        return None

    if isinstance(node := handler.type, ast.Tuple):
        for elt in node.elts:
            rendered = render(elt)
            if rendered is None:
                return None          # unknown shape -> not comparable
            parts.append(rendered)
    else:
        rendered = render(handler.type)
        if rendered is None:
            return None
        parts.append(rendered)
    return tuple(sorted(parts))


def check_duplicate_except(tree: ast.AST, path: str) -> list[str]:
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        seen: dict[tuple[str, ...], int] = {}
        for handler in node.handlers:
            key = _exc_key(handler)
            if key is None:
                continue
            if key in seen:
                out.append(
                    f"{path}:{handler.lineno}: duplicate except clause "
                    f"'{'|'.join(key)}' (already handled at line {seen[key]})"
                )
            else:
                seen[key] = handler.lineno
    return out


BROAD_EXCEPTIONS = {"Exception", "BaseException", "StandardError"}


def _is_broad(handler: ast.ExceptHandler) -> bool:
    """True for bare ``except:`` or ``except Exception/BaseException``."""
    if handler.type is None:
        return True
    node = handler.type
    if isinstance(node, ast.Name):
        return node.id in BROAD_EXCEPTIONS
    if isinstance(node, ast.Attribute):
        return node.attr in BROAD_EXCEPTIONS
    if isinstance(node, ast.Tuple):
        return any(isinstance(e, ast.Name) and e.id in BROAD_EXCEPTIONS
                   for e in node.elts)
    return False


def check_silent_except(tree: ast.AST, path: str) -> list[str]:
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not _is_broad(node):
            continue          # narrow handler -> legitimate fall-through flow
        # A leading docstring is documentation, not behaviour — but `...` is a
        # statement and must NOT be stripped along with it.
        meaningful = [s for s in node.body if not _is_docstring(s)]
        if not meaningful or all(_is_silent_stmt(s) for s in meaningful):
            shown = "/".join(type(s).__name__.lower() for s in meaningful) or "empty"
            out.append(f"{path}:{node.lineno}: silent broad except (body is only {shown})")
    return out


def check_duplicate_dict_keys(tree: ast.AST, path: str) -> list[str]:
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        seen: dict[str, int] = {}
        for key in node.keys:
            if key is None:                       # **unpacking
                continue
            if isinstance(key, ast.Constant):
                literal = repr(key.value)
            elif isinstance(key, ast.Name):
                literal = key.id
            else:
                continue                          # computed key -> skip
            if literal in seen:
                out.append(
                    f"{path}:{key.lineno}: duplicate dict key {literal} "
                    f"(already defined at line {seen[literal]})"
                )
            else:
                seen[literal] = key.lineno
    return out


CHECKS = (
    ("duplicate-except", check_duplicate_except),
    ("silent-except", check_silent_except),
    ("duplicate-dict-key", check_duplicate_dict_keys),
)


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    files = sorted(root.rglob("*.py"))
    for path in files:
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            findings.append(f"{path}: could not parse: {exc}")
            continue
        rel = str(path)
        for _name, fn in CHECKS:
            findings.extend(fn(tree, rel))
    return findings


def check_name_of(line: str) -> str:
    """Map a finding line back to the check that produced it."""
    for name, _fn in CHECKS:
        if name == "silent-except" and "silent broad except" in line:
            return name
        if name == "duplicate-except" and "duplicate except clause" in line:
            return name
        if name == "duplicate-dict-key" and "duplicate dict key" in line:
            return name
    return "unknown"


def load_allowance(path: Path, service: str) -> dict[str, int]:
    """Counted ceilings per check, per service.

    Some checks describe a *pre-existing* condition (silent broad excepts remain
    after the R4 sweep). Blocking CI on those would make the gate useless on
    day one, so instead the count is frozen: the gate fails when the number
    **grows**, which is what "regression guard" means. Same idiom as
    ``check_dsh_native_code_boundary.py``'s counted allowance.
    """
    if not path.exists():
        return {}
    import json
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    per_service = data.get("services", {}).get(service)
    if per_service is None:
        return {}
    return {k: int(v) for k, v in per_service.items()}


def counts_by_check(findings: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {name: 0 for name, _ in CHECKS}
    for line in findings:
        counts[check_name_of(line)] = counts.get(check_name_of(line), 0) + 1
    return counts


# --------------------------------------------------------------------------
# Adversarial self-check: every check must fire on the bad sample and stay
# quiet on the good sample. Run with --self-test.
# --------------------------------------------------------------------------

BAD = '''
try:
    risky()
except ValueError:
    log("a")
except ValueError:          # duplicate-except
    log("b")

try:
    risky()
except Exception:
    pass                    # silent broad except

try:
    risky()
except BaseException:
    ...                     # silent broad except (ellipsis body)

CONFIG = {"timeout": 1, "timeout": 2}   # duplicate-dict-key
'''

GOOD = '''
try:
    risky()
except ValueError:
    log("a")
except KeyError:
    log("b")

try:
    risky()
except Exception as exc:
    log(f"suppressed {exc}")

# Narrow silent handler = legitimate fall-through control flow; must stay quiet.
try:
    return int(text)
except ValueError:
    pass
try:
    return float(text)
except ValueError:
    pass

CONFIG = {"timeout": 1, "retries": 2}
MERGED = {**CONFIG, "timeout": 3}
'''


def self_test() -> int:
    bad_tree = ast.parse(BAD)
    good_tree = ast.parse(GOOD)
    ok = True
    for name, fn in CHECKS:
        bad_hits = fn(bad_tree, "<bad>")
        good_hits = fn(good_tree, "<good>")
        fired = bool(bad_hits)
        quiet = not good_hits
        status = "OK" if (fired and quiet) else "FAIL"
        if not (fired and quiet):
            ok = False
        print(f"  [{status}] {name}: 坏样本命中={fired} 好样本零命中={quiet}")
        for line in good_hits:
            print(f"         误报 -> {line}")
    # a bare `except:` must not be confused with a typed one
    bare = ast.parse("try:\n    x()\nexcept:\n    log()\nexcept ValueError:\n    log()\n")
    bare_hits = check_duplicate_except(bare, "<bare>")
    if bare_hits:
        ok = False
        print(f"  [FAIL] bare-except-vs-typed 不应判重复: {bare_hits}")
    else:
        print("  [OK] bare-except-vs-typed 不误判为重复")
    print("自检结果：" + ("通过" if ok else "失败"))
    return 0 if ok else 1


VALUE_FLAGS = {"--service", "--allowance"}


def parse_args(argv: list[str]) -> tuple[list[str], str, Path | None]:
    """Split argv into (targets, service, allowance_path).

    Options that take a value must be skipped *together with* their value —
    otherwise `--service chat-api` leaks "chat-api" into the target list.
    """
    targets: list[str] = []
    service = "default"
    allowance: Path | None = None
    it = iter(argv[1:])
    for token in it:
        if token == "--service":
            service = next(it, "")
        elif token == "--allowance":
            value = next(it, "")
            allowance = Path(value) if value else None
        elif token in VALUE_FLAGS:
            next(it, None)                    # unknown value flag -> drop its value
        elif token.startswith("-"):
            continue                          # bare flag
        else:
            targets.append(token)
    return targets, service, allowance


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()

    targets, service, allowance_arg = parse_args(argv)
    if not targets:
        print("usage: check_python_static.py <dir>... [--service NAME] [--allowance FILE]"
              " | --self-test", file=sys.stderr)
        return 2

    allowance_path = allowance_arg or (
        Path(__file__).resolve().parent / "python_static_allowance.json"
    )

    findings: list[str] = []
    for target in targets:
        root = Path(target)
        if not root.exists():
            print(f"error: {target} does not exist", file=sys.stderr)
            return 2
        findings.extend(scan(root))

    ceilings = load_allowance(allowance_path, service)
    counts = counts_by_check(findings)

    regressions: list[str] = []
    for name, count in sorted(counts.items()):
        ceiling = ceilings.get(name)
        if ceiling is None:
            ceiling = 0                       # unlisted check -> must be clean
        if count > ceiling:
            regressions.append(f"{name}: {count} > ceiling {ceiling}")

    if regressions:
        for line in findings:
            print(f"::error file={line.split(':', 1)[0]}::{line}")
        print()
        for line in regressions:
            print(f"::error::{line}")
        print(f"\npython static check FAILED: {len(regressions)} check(s) above ceiling")
        return 1

    summary = ", ".join(f"{n}={c}/{ceilings.get(n, 0)}" for n, c in sorted(counts.items()))
    print(f"python static check passed (counts vs ceiling: {summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
