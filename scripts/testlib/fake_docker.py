#!/usr/bin/env python3
"""023 T117 测试用假 docker（compose）命令替身。

为什么要有它：`scripts/drill/inject_dependency_fault.sh` 的价值全在「真的把容器停了」。
如果测试里只能跑 dry-run，那脚本最危险的部分（stop/start 的时序与断言）从未被执行过。
这个替身让脚本在 CI 里也能跑完整路径：stop 改状态文件 → 假 API 随即转红 → 断言成立。

状态文件（FAKE_DOCKER_STATE，JSON）：{"running": ["mongo", "gateway", ...]}
调用记录（FAKE_DOCKER_CALLS）：每行一条，形如 `compose stop mongo`。
"""
from __future__ import annotations

import json
import os
import sys

STATE_PATH = os.environ.get("FAKE_DOCKER_STATE", "")
CALLS_PATH = os.environ.get("FAKE_DOCKER_CALLS", "")


def _load_state() -> dict:
    if not STATE_PATH or not os.path.exists(STATE_PATH):
        return {"running": []}
    with open(STATE_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _save_state(state: dict) -> None:
    if not STATE_PATH:
        return
    with open(STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle)


def _record(args) -> None:
    if not CALLS_PATH:
        return
    with open(CALLS_PATH, "a", encoding="utf-8") as handle:
        handle.write(" ".join(args) + "\n")


def _split_compose(args: list[str]) -> list[str]:
    """去掉 compose 的全局选项（-p/-f 及其值），返回子命令。"""
    index = 0
    while index < len(args) and args[index].startswith("-"):
        if args[index] in {"-p", "-f", "--project-name", "--file"}:
            index += 2
        else:
            index += 1
    return args[index:]


def main() -> int:
    args = sys.argv[1:]
    _record(args)
    state = _load_state()

    if args[:1] == ["info"]:
        print("29.0.0")
        return 0

    if args[:1] != ["compose"]:
        print("fake docker: 不支持的命令 %r" % (args,), file=sys.stderr)
        return 1

    sub = _split_compose(args[1:])
    if not sub:
        print("fake docker: compose 缺少子命令", file=sys.stderr)
        return 1

    if sub[0] == "version":
        print("Docker Compose version v5.5.0")
        return 0

    if sub[0] == "ps":
        for name in state.get("running", []):
            print(name)
        return 0

    if sub[0] in {"stop", "start"} and len(sub) >= 2:
        name = sub[1]
        running = list(state.get("running", []))
        if sub[0] == "stop":
            if name not in running:
                print("fake docker: 服务 %s 没在运行" % name, file=sys.stderr)
                return 1
            running.remove(name)
        else:
            if name not in running:
                running.append(name)
        state["running"] = running
        _save_state(state)
        print("%s %s" % (sub[0], name))
        return 0

    print("fake docker: 不支持的子命令 %r" % (sub,), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
