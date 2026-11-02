"""Python source executed inside one governed script job."""

from __future__ import annotations


RUNNER_SOURCE = r'''
import importlib.util
import builtins
import _io
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
context = payload.get("context") or {}
if not context.get("allow_network"):
    socket.socket = _deny_network
    socket.create_connection = _deny_network

work_dir = os.path.realpath(str(context.get("work_dir") or ""))
skill_dir = os.path.realpath(str(context.get("skill_dir") or "")) if context.get("skill_dir") else ""
_open = builtins.open
_io_open = io.open
_os_open = os.open
_io_fileio = _io.FileIO
_os_scandir = os.scandir
_os_listdir = os.listdir

# 只读白名单：解释器与依赖包目录必须放行，否则守卫装上之后任何一次
# 「还没 import 过」的标准库导入（importlib 走 _io.FileIO）都会被自己拦住。
readable_roots = set()
for key in ("purelib", "platlib", "stdlib", "platstdlib"):
    value = sysconfig.get_paths().get(key)
    if value:
        readable_roots.add(os.path.realpath(value))
for value in (sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix):
    if value:
        readable_roots.add(os.path.realpath(value))

def _is_write_mode(mode):
    text = str(mode or "r")
    return any(ch in text for ch in ("w", "a", "x", "+"))

def _check_path(path, *, write=False):
    if not work_dir:
        return
    if isinstance(path, int):
        return
    try:
        raw = os.fspath(path)
    except TypeError:
        return
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
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
        if not write and any(real == root or real.startswith(root + os.sep) for root in readable_roots):
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

def _guarded_fileio(file, mode="r", *args, **kwargs):
    # Patching open() alone is not a boundary: io.FileIO / _io.FileIO open a
    # path directly and skip every hook above.
    _check_path(file, write=_is_write_mode(mode))
    return _io_fileio(file, mode, *args, **kwargs)

def _guarded_os_open(file, flags, mode=0o777, *, dir_fd=None):
    if dir_fd is None:
        write = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        _check_path(file, write=write)
    return _os_open(file, flags, mode, dir_fd=dir_fd)

def _guarded_scandir(path="."):
    _check_path(path)
    return _os_scandir(path)

def _guarded_listdir(path="."):
    _check_path(path)
    return _os_listdir(path)

# 白名单库（与 app/api/endpoints/skills.py 的 _SCRIPT_PLUGIN_ALLOWED_IMPORT_ROOTS
# 同步）必须在装守卫之前预热导入：openpyxl 等在 import 期会读系统配置/包内资源，
# 守卫先装的话这些读取会被自己的边界拦下，插件在模块级 import 就崩。
for _warm_name in ("json", "os", "re", "shutil", "zipfile", "csv", "math",
                   "statistics", "datetime", "collections", "docx", "openpyxl",
                   "pptx", "urllib"):
    try:
        __import__(_warm_name)
    except Exception:
        pass

# SEC-01: 守卫必须在 exec_module 之前装好。插件顶层语句在 import 时就会执行，
# 装晚了模块级 open() 直接落到原始 builtin 上。
builtins.open = _guarded_open
io.open = _guarded_io_open
io.FileIO = _guarded_fileio
_io.FileIO = _guarded_fileio
os.open = _guarded_os_open
os.scandir = _guarded_scandir
os.listdir = _guarded_listdir

spec = importlib.util.spec_from_file_location("askai_user_plugin", plugin_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
run = getattr(module, "run", None)
if not callable(run):
    raise RuntimeError("script plugin must define run(inputs, context)")

result = run(payload.get("inputs") or {}, context)
if result is None:
    result = {}
if not isinstance(result, dict):
    raise RuntimeError("run(inputs, context) must return a dict")
print(json.dumps(result, ensure_ascii=False))
'''.strip()


def runner_source() -> str:
    return RUNNER_SOURCE
