"""Python source executed inside one governed script job."""

from __future__ import annotations


RUNNER_SOURCE = r'''
import importlib.util
import builtins
import io
import json
import os
import socket
import sys
import sysconfig

def _deny_network(*args, **kwargs):
    raise RuntimeError("network access is disabled in script_plugin")

plugin_path, stdin_path = sys.argv[1], sys.argv[2]
with open(stdin_path, "r", encoding="utf-8") as f:
    payload = json.load(f)
if not (payload.get("context") or {}).get("allow_network"):
    socket.socket = _deny_network
    socket.create_connection = _deny_network

spec = importlib.util.spec_from_file_location("askai_user_plugin", plugin_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
run = getattr(module, "run", None)
if not callable(run):
    raise RuntimeError("script plugin must define run(inputs, context)")

context = payload.get("context") or {}
work_dir = os.path.realpath(str(context.get("work_dir") or ""))
skill_dir = os.path.realpath(str(context.get("skill_dir") or "")) if context.get("skill_dir") else ""
_open = builtins.open
_io_open = io.open
_os_open = os.open
package_roots = set()
for key in ("purelib", "platlib"):
    value = sysconfig.get_paths().get(key)
    if value:
        package_roots.add(os.path.realpath(value))

def _is_write_mode(mode):
    text = str(mode or "r")
    return any(ch in text for ch in ("w", "a", "x", "+"))

def _check_path(path, *, write=False):
    if not work_dir:
        return
    raw = os.fspath(path)
    if not raw:
        return
    if not os.path.isabs(raw):
        raw = os.path.join(work_dir, raw)
    real = os.path.realpath(raw)
    if write and skill_dir and (real == skill_dir or real.startswith(skill_dir + os.sep)):
        raise PermissionError("Skill package resources are read-only")
    if real != work_dir and not real.startswith(work_dir + os.sep):
        if not write and skill_dir and (real == skill_dir or real.startswith(skill_dir + os.sep)):
            return
        if not write and any(real == root or real.startswith(root + os.sep) for root in package_roots):
            return
        raise PermissionError("script_plugin file access is limited to work_dir")

def _guarded_open(file, *args, **kwargs):
    mode = args[0] if args else kwargs.get("mode", "r")
    _check_path(file, write=_is_write_mode(mode))
    return _open(file, *args, **kwargs)

def _guarded_io_open(file, *args, **kwargs):
    # pathlib imported after this hook binds io.open as an accessor
    # method, passing its accessor instance before the real path.
    if not isinstance(file, (str, bytes, os.PathLike, int)) and args:
        file, args = args[0], args[1:]
    # io.open also accepts already-open descriptors (e.g. pipes
    # created by subprocess); no filesystem path is opened here.
    if isinstance(file, int):
        return _io_open(file, *args, **kwargs)
    mode = args[0] if args else kwargs.get("mode", "r")
    _check_path(file, write=_is_write_mode(mode))
    return _io_open(file, *args, **kwargs)

def _guarded_os_open(file, flags, mode=0o777, *, dir_fd=None):
    if dir_fd is None:
        write = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        _check_path(file, write=write)
    return _os_open(file, flags, mode, dir_fd=dir_fd)

builtins.open = _guarded_open
io.open = _guarded_io_open
os.open = _guarded_os_open
result = run(payload.get("inputs") or {}, context)
if result is None:
    result = {}
if not isinstance(result, dict):
    raise RuntimeError("run(inputs, context) must return a dict")
print(json.dumps(result, ensure_ascii=False))
'''.strip()


def runner_source() -> str:
    return RUNNER_SOURCE
