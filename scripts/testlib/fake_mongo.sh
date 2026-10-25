#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# scripts/testlib/fake_mongo.sh — 备份/恢复测试用的假 mongodump/mongorestore/mongosh
# ═══════════════════════════════════════════════════════════════════════
#
# 为什么需要它：备份脚本的价值全在"没有真库时也能验证行为"——加密是否真的
# 用了口令、异地上传是否发生、保留策略是否按文件名时间戳清理、恢复后文档数
# 是否与清单一致。这些都可以在没有 MongoDB 的机器上验证，只是需要把三个命令行
# 工具换成受控替身。真实 mongodump/mongorestore 的端到端演练留在
# docs/runbooks/disaster-recovery.md 的演练清单里，由 Phase 7 的 T113 记录。
#
# 用法：
#   source scripts/testlib/fake_mongo.sh
#   fake_mongo_init                      # 建立替身目录与状态文件
#   PATH="${FAKE_MONGO_BIN}:${PATH}"
#   ... 跑被测脚本 ...
#   fake_mongo_cleanup
#
# 替身读取 FAKE_MONGO_STATE（JSON：{库: {集合: [_id...]}}）模拟库内容；
# 每次调用把参数追加到 FAKE_MONGO_CALLS，测试用它断言"到底调没调、怎么调的"。
# 故障注入开关（env，值为 1 时生效）：
#   FAKE_DUMP_FAIL=1         mongodump 失败
#   FAKE_DUMP_EMPTY=1        mongodump 产出空文件（应被拒绝）
#   FAKE_RESTORE_FAIL=1      mongorestore 失败
#   FAKE_RESTORE_TRUNCATE=1  mongorestore "少恢复一条"，用来验证一致性校验能失败
set -Eeuo pipefail

fake_mongo_init() {
  FAKE_MONGO_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/mogo-fake-mongo.XXXXXX")"
  FAKE_MONGO_BIN="${FAKE_MONGO_ROOT}/bin"
  FAKE_MONGO_STATE="${FAKE_MONGO_ROOT}/state.json"
  FAKE_MONGO_CALLS="${FAKE_MONGO_ROOT}/calls.log"
  mkdir -p "${FAKE_MONGO_BIN}"
  : >"${FAKE_MONGO_CALLS}"

  cat >"${FAKE_MONGO_ROOT}/fake_mongo.py" <<'PY'
import json, os, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, "state.json")
CALLS = os.path.join(ROOT, "calls.log")


def load_state():
    try:
        with open(STATE) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def save_state(state):
    with open(STATE, "w") as fh:
        json.dump(state, fh)


def record(name, argv):
    with open(CALLS, "a") as fh:
        fh.write(name + "\t" + "\t".join(argv) + "\n")


def parse(argv):
    args = {"rest": [], "flags": set()}
    i = 0
    while i < len(argv):
        item = argv[i]
        if item.startswith("--"):
            if "=" in item:
                key, value = item[2:].split("=", 1)
                args[key] = value
            elif item in ("--gzip", "--oplog", "--drop", "--quiet"):
                args["flags"].add(item[2:])
            elif i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                args[item[2:]] = argv[i + 1]
                i += 1
            else:
                args["flags"].add(item[2:])
        else:
            args["rest"].append(item)
        i += 1
    return args


def db_of_uri(uri):
    # mongodb://host:27017/dbname?query
    tail = uri.split("//", 1)[-1]
    if "/" not in tail:
        return ""
    return tail.split("/", 1)[1].split("?", 1)[0]


def cmd_mongodump(argv):
    record("mongodump", argv)
    args = parse(argv)
    if os.environ.get("FAKE_DUMP_FAIL") == "1":
        sys.stderr.write("fake mongodump: injected failure\n")
        return 2
    archive = args.get("archive")
    if not archive:
        sys.stderr.write("fake mongodump: --archive is required by this fake\n")
        return 3
    if os.environ.get("FAKE_DUMP_EMPTY") == "1":
        open(archive, "wb").close()
        return 0
    # 内容无关紧要：真正被测的是加密/校验和/命名/清单，不是 dump 的二进制格式
    payload = b"FAKE-MONGO-DUMP\n" + json.dumps(load_state()).encode() + b"\n"
    with open(archive, "wb") as fh:
        fh.write(payload)
    return 0


def cmd_mongorestore(argv):
    record("mongorestore", argv)
    args = parse(argv)
    if os.environ.get("FAKE_RESTORE_FAIL") == "1":
        sys.stderr.write("fake mongorestore: injected failure\n")
        return 2
    archive = args.get("archive")
    if not archive or not os.path.exists(archive):
        sys.stderr.write("fake mongorestore: archive missing\n")
        return 3
    ns_from = args.get("nsFrom", "")
    ns_to = args.get("nsTo", "")
    src_db = ns_from.split(".", 1)[0] or db_of_uri(args.get("uri", ""))
    dst_db = ns_to.split(".", 1)[0] or src_db
    state = load_state()
    if "drop" in args["flags"]:
        state[dst_db] = {}
    state[dst_db] = json.loads(json.dumps(state.get(src_db, {})))
    if os.environ.get("FAKE_RESTORE_TRUNCATE") == "1":
        for name in sorted(state[dst_db]):
            docs = state[dst_db][name]
            if docs:
                state[dst_db][name] = docs[:-1]
                break
    save_state(state)
    return 0


def cmd_mongosh(argv):
    record("mongosh", argv)
    args = parse(argv)
    script = args.get("eval", "")
    state = load_state()
    db = db_of_uri(args["rest"][0] if args["rest"] else "")

    if "dropDatabase" in script:
        state.pop(db, None)
        save_state(state)
        return 0

    if "getSiblingDB" in script:
        # 抽样 _id：从脚本里取库名与 limit
        start = script.index("getSiblingDB(")
        quote = script[start + len("getSiblingDB(")]
        end = script.index(quote, start + len("getSiblingDB(") + 1)
        target = script[start + len("getSiblingDB(") + 1:end]
        limit = 5
        if "limit(" in script:
            chunk = script.split("limit(", 1)[1]
            digits = ""
            for ch in chunk:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            if digits:
                limit = int(digits)
        for name in sorted(state.get(target, {})):
            ids = sorted(str(item) for item in state[target][name])[:limit]
            print(name + "\t" + ",".join(ids))
        return 0

    if "countDocuments" in script:
        for name in sorted(state.get(db, {})):
            print(name + "\t" + str(len(state.get(db, {}).get(name, []))))
        return 0

    sys.stderr.write("fake mongosh: unsupported eval script\n")
    return 4


def main():
    name = os.environ.get("FAKE_MONGO_TOOL") or os.path.basename(sys.argv[0])
    argv = sys.argv[1:]
    if name == "mongodump":
        return cmd_mongodump(argv)
    if name == "mongorestore":
        return cmd_mongorestore(argv)
    if name == "mongosh":
        return cmd_mongosh(argv)
    if name == "openssl-fake":
        return 0
    sys.stderr.write("fake_mongo: unknown command " + name + "\n")
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
PY

  local tool
  for tool in mongodump mongorestore mongosh; do
    cat >"${FAKE_MONGO_BIN}/${tool}" <<EOF
#!/usr/bin/env bash
exec env FAKE_MONGO_TOOL=${tool} python3 "${FAKE_MONGO_ROOT}/fake_mongo.py" "\$@"
EOF
    chmod +x "${FAKE_MONGO_BIN}/${tool}"
  done

  # 默认状态：两个集合，文档数固定，便于断言
  fake_mongo_seed '{"mogo": {"users": ["u1", "u2", "u3"], "posts": ["p1", "p2"]}}'
}

fake_mongo_seed() {
  printf '%s' "${1}" >"${FAKE_MONGO_STATE}"
}

fake_mongo_calls() {
  cat "${FAKE_MONGO_CALLS}"
}

fake_mongo_cleanup() {
  [[ -n "${FAKE_MONGO_ROOT:-}" ]] && rm -rf "${FAKE_MONGO_ROOT}"
}
