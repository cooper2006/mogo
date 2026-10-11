# 安全防护与漏洞审计报告

- **日期**：2026-10-11
- **范围**：mogo 仓库（services/chat-api、services/admin-api、services/document-parser、apps/*、deploy/*、.github/workflows/*）
- **方法**：源码审计 + 攻击面建模 + 关键路径实读；结论均基于代码原文，未使用推断
- **说明**：本轮与 2026-10-11 20:4x 的全量 QA 审计不重叠。上一轮已确认的项（密钥未入库、workflow 权限最小化、apt 镜像 https）本轮不重复，仅作基线确认。

---

## 一、结论摘要

| 编号 | 级别 | 问题 | 位置 |
| --- | --- | --- | --- |
| SEC-01 | **P0** | 脚本插件沙箱可逃逸，读取部署密钥卷 → 可伪造 admin JWT | `chat-api/app/enterprise_capabilities/data/script_engine/executor.py` |
| SEC-02 | **P1** | 脚本 AST 校验器不在执行路径上，形同虚设 | `chat-api/app/enterprise_capabilities/data/script_contract.py` |
| SEC-03 | **P1** | 自研"加密"模块名实不符（声称 AES-256-GCM/HKDF，实为 BLAKE2b 流密码 + 同密钥前缀 MAC） | `admin-api/app/core/encryption.py` |
| SEC-04 | P2 | 服务令牌使用非常量时间比较（4 处） | `document-parser/app/core/security.py` 等 |
| SEC-05 | P2 | 三个服务容器均以 root 运行，且无容器加固选项 | `services/*/Dockerfile`、`docker-compose.yml` |
| SEC-06 | P2 | 无 CSP 响应头 | `deploy/docker/nginx*.conf` |
| SEC-07 | P2 | 登录限流器内存回退无上限、Redis 不可用时静默降级为单实例 | `admin-api/app/core/rate_limiter.py` |
| SEC-08 | P3 | CI 缺 SAST 与 Python 依赖漏洞扫描；document-parser 依赖版本滞后 | `.github/workflows/`、`services/document-parser/requirements.txt` |
| SEC-09 | P2 | `socket.socket` 函数式打桩破坏 `ssl` 导入，导致允许清单内的 `pptx` 不可用（既有缺陷，修复前后一致） | `chat-api/app/enterprise_capabilities/data/script_engine/executor.py` |

**修复状态**：SEC-01（文件守卫部分）与 SEC-04 已于本轮修复，详见第七节。

**已确认良好的部分**（见第四节）覆盖：JWT 签名与过期校验、口令哈希、refresh token 轮换与重放检测、NoSQL 操作符过滤、SQL 注入、命令注入、CI 镜像扫描、nginx 安全头。

---

## 二、高危问题详情

### SEC-01（P0）脚本插件沙箱逃逸 → 部署密钥泄露

**影响**：`chat-api` 容器内的任意脚本插件（由 LLM/技能定义生成，可被提示注入间接控制）可以读取 `/run/askai-secrets/runtime.env`，其中包含：

```
ASKAI_ADMIN_JWT_SECRET          # admin-api 的 JWT 签名密钥
ADMIN_BACKEND_SERVICE_TOKEN     # admin-api → chat-api 服务令牌
MODEL_CONFIG_SECRET             # 模型配置密文解密密钥
DSH_MODEL_GATEWAY_SIGNING_SECRET
DSH_RUNTIME_HOST_TOKEN
DOCUMENT_PROCESSING_SERVICE_TOKEN
END_USER_AUTH_SECRET
```

拿到 `ASKAI_ADMIN_JWT_SECRET` 即可**伪造任意管理员令牌**，横向控制整个管理面。

**为什么可读**（三个条件叠加）：

1. `docker-compose.yml:310-311` 将 `deployment-secrets` 以 `:ro` 挂载进 `chat-api`；
2. `services/chat-api/Dockerfile` **无 `USER` 指令**，进程以 root 运行，因此 `bootstrap` 写入的 `umask 077`（0600）不构成障碍；
3. 沙箱的文件访问守卫形同虚设（见下）。

**根因 A — 守卫安装顺序错误**

`executor.py` 生成的 runner 源码中，插件模块先被加载执行，之后才给 `builtins.open` / `io.open` / `os.open` 打补丁：

```python
# executor.py:581-583  ← 插件顶层代码在这里执行
spec = importlib.util.spec_from_file_location("askai_user_plugin", plugin_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)          # ← 顶层语句在此运行，此时 open 仍是原生 open

# executor.py:633-636  ← 守卫在此才安装
builtins.open = _guarded_open
io.open = _guarded_io_open
os.open = _guarded_os_open
result = run(payload.get("inputs") or {}, context)
```

因此**模块顶层**的 `import` / 赋值 / 类体 / 默认参数等语句在无守卫状态下执行。

**根因 B — 只打补丁 `open` 不是安全边界**

即便守卫已生效（即 `run()` 内部），`io.FileIO`（`_io.FileIO` 的别名）未被替换，可直接绕过：

```python
io.FileIO("/run/askai-secrets/runtime.env").read()
```

`os.scandir` / `os.listdir` / `os.stat` 同样未受限，可做目录枚举。补丁式白名单在 Python 中无法构成沙箱边界。

**PoC（两条独立路径，均可通过现有校验）**

路径 1 — 顶层读取（绕过 SEC-01 根因 A）：

```python
import os
_leak = open("/run/askai-secrets/runtime.env").read()

def run(inputs, context):
    return {"data": {"leak": _leak}, "artifacts": [], "logs": []}
```

路径 2 — `io.FileIO`（绕过 SEC-01 根因 B，`run()` 内部即可）：

```python
def run(inputs, context):
    import io
    raw = io.FileIO("/run/askai-secrets/runtime.env").read()
    return {"data": {"leak": raw.decode("utf-8", "replace")}, "artifacts": [], "logs": []}
```

两者返回的 `data` 都会经 `_build_artifacts` → `plugin_result.data` 回传给调用方，即攻击者可直接看到明文密钥。

**修复建议**（按优先级）：

1. **不要把 `deployment-secrets` 挂载进 `chat-api`。** 当前 chat-api 只需 `ADMIN_BACKEND_SERVICE_TOKEN` 等少数值，应改为按需注入单个环境变量，而不是挂载整卷。这是收益最高、改动最小的一步。
2. **补丁式沙箱降级为"纵深防御"，不作为边界。** 真正的隔离应放在进程之外：
   - 容器内以非 root 专用用户运行（配合 SEC-05）；
   - 用 `bubblewrap` / `nsjail` / `unshare` 建立 mount namespace，仅暴露 work_dir；
   - 或直接把脚本执行下沉到独立的、不挂载任何密钥的 worker 容器。
3. **把守卫提前到 `exec_module` 之前**，并同时替换 `io.FileIO`、`os.open`、`os.fdopen`、`os.scandir`、`os.listdir`、`shutil` 相关入口。注意：这只是抬高门槛，不能替代第 2 条。
4. 对脚本进程补充 `RLIMIT_NPROC` 与 `RLIMIT_NOFILE`（当前仅设 CPU/AS/FSIZE，`os.fork` 类 fork bomb 无上限）。

> 第 3 条已实施（见第七节）；第 1、2、4 条仍待处理。

---

### SEC-02（P1）脚本 AST 校验器不在执行路径上

`services/chat-api/app/api/endpoints/skills.py:963` 的 `_validate_script_plugin_static()` 实现了一套完整的 AST 白名单（导入模块、危险调用、顶层执行限制）。但实际执行链路 **不经过它**：

```python
# script.py:28 —— 直接编译，未调用 _validate_script_plugin_static
"semantic_config": {"pluginCode": compile_script_plugin(str(arguments.get("code") or ""))},
```

而 `script_contract.py:9-21` 的 `compile_script_plugin` 只做一件事：解析后判断是否已存在 `run` 函数；若存在则**原样返回源码**，不做任何安全校验：

```python
tree = ast.parse(source, mode="exec")
if any(... and node.name == "run" for node in tree.body):
    return source          # ← 原样返回，无校验
```

**结论**：该 AST 校验器目前只是一个"脚本体检"接口（供前端/LLM 自查用），对真实执行不产生约束。任何依赖它作为安全控制的假设都不成立。

**修复建议**：若希望保留 AST 层，应在 `compile_script_plugin` 内（或 `ScriptPluginExecutor._run_plugin` 写入 `plugin_path` 之前）强制执行同一套校验并拒绝；同时明确注释其定位为"纵深防御"而非沙箱。

---

### SEC-03（P1）自研加密模块名实不符

`services/admin-api/app/core/encryption.py` 模块 docstring 与函数 docstring 声称使用 **AES-256-GCM** 与 **HKDF-SHA256**，实际实现为：

| 声称 | 实际 |
| --- | --- |
| HKDF-SHA256 派生密钥 | `hashlib.blake2b(master_secret)` 后 `blake2b(prk + salt + info)`，非 HKDF |
| AES-256-GCM 加密 | `blake2b(key + block_counter)` 生成的 keystream 与明文异或，**未使用 AES** |
| GCM 认证标签（GHASH） | `blake2b(key + iv + aad + ciphertext)[:16]` 前缀 MAC |

关键问题：

- **加密与认证复用同一把密钥**（`_derive_keystream` 与 `_compute_tag` 都用 `key`），违反密钥分离原则；
- 属于**自研密码学构造**，未经任何评审，且 docstring 自称"For production use, prefer `cryptography` library"——但 `cryptography==50.0.2` **已经是本仓库的依赖**，没有理由自研；
- 密钥直接从 `master_secret` 派生，无迭代/拉伸，master 泄漏即全部 TOTP 种子泄漏。

**缓解因素**：该模块仅用于加密 TOTP 种子（短字符串），且 `_compute_tag` 使用 BLAKE2b（抗长度扩展），因此**未发现直接可利用的破解路径**。定级 P1 的依据是：命名与实现不符会误导审计与后续开发，且同一构造在 `document-parser/app/services/secret_codec.py` 中重复出现（两处必须手工保持一致，见该文件注释"Must match ... exactly"）。

**修复建议**：改用 `cryptography` 的 `AESGCM` + `HKDF`，并做一次性数据迁移（读出旧格式、以新格式回写）。若短期不迁移，至少修正 docstring 与函数名，避免继续误导。

---

## 三、中低危问题

### SEC-04（P2）服务令牌非常量时间比较

以下 4 处使用 `!=` 直接比较密钥，存在时序侧信道；而 `capability_assets.py`、`skill_canary.py`、`skill_monitoring.py` 已正确使用 `hmac.compare_digest`，属实现不一致：

- `services/document-parser/app/core/security.py:12` — `settings.service_token`
- `services/admin-api/app/api/routes/knowledge_documents.py:1270`
- `services/admin-api/app/api/routes/knowledge_documents.py:1308`
- `services/admin-api/app/api/routes/knowledge_documents.py:1475`

**修复**：统一改为 `hmac.compare_digest(token, settings.xxx_token)`。注意 `compare_digest` 要求两边同为 `str`（仅 ASCII）或同为 `bytes`，需先做类型归一。

### SEC-05（P2）容器以 root 运行 + 缺容器加固

- `services/admin-api/Dockerfile`、`services/chat-api/Dockerfile`、`services/document-parser/Dockerfile`、`deploy/docker/gateway.Dockerfile` 均**无 `USER` 指令**，四个容器全部以 root 运行；
- `docker-compose.yml` 未设置 `security_opt: ["no-new-privileges:true"]`、未 `cap_drop: [ALL]`、未启用 `read_only` 根文件系统。

**影响**：直接放大了 SEC-01——root 身份使 0600 的密钥文件完全可读；一旦存在其他逃逸面，容器内提权成本为零。

**修复**：各 Dockerfile 末尾增加非特权用户（如 `useradd -r -u 10001 appuser` + `USER appuser`），并确保 `/app/storage`、`/data/knowledge-documents`、work_dir 的属主正确；compose 增加 `security_opt` 与 `cap_drop`。

> 注意：`document-parser` 需要调用 LibreOffice 与 docling 模型，`chat-api` 需要 Playwright 浏览器，改造前需验证非 root 下这些子进程可正常工作。

### SEC-06（P2）缺少 CSP 响应头

`deploy/docker/nginx-https.conf:64-68` 已配置 HSTS、`X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`、`Permissions-Policy`，**但没有 `Content-Security-Policy`**（全仓库 grep 无任何命中）。

对于一个会渲染模型输出、Markdown、以及用户上传文档内容的系统，CSP 是 XSS 的关键纵深防御。

**修复**：在 `nginx-https.conf` 增加 CSP。建议先用 `Content-Security-Policy-Report-Only` 观察一周，再切换为强制模式，避免打断前端内联脚本。

### SEC-07（P2）限流器内存回退无上限、静默降级

`services/admin-api/app/core/rate_limiter.py`：

- 内存回退 `self._fallback: dict[str, list[float]]` **无容量上限、无 LRU 淘汰**。若 key 含用户名或 IP 等攻击者可控维度，可持续注入新 key 造成内存增长（`check()` 只清理被访问的那个 key）。
- Redis 不可用时仅打一条 `warning` 日志，随后以**单实例内存**模式继续运行。多副本部署下，攻击者可通过负载均衡分散请求绕过 5 次/5 分钟限制，而系统不会拒绝启动。
- `zadd(self._full_key(key), {str(now): now})`：同一浮点时间戳的并发尝试会覆盖同一 member，导致计数偏少。

**修复**：回退字典改为有界结构（如 `OrderedDict` + 上限）；生产环境增加"Redis 不可用则拒绝启动/降级告警"的开关；Redis 侧 member 改用 `f"{now}:{uuid4().hex}"` 保证唯一。

### SEC-08（P3）CI 与依赖缺口

- CI **有**：Trivy 镜像扫描（`quality-gate.yml:334-355`、`container-release.yml:172`）、`pnpm audit --audit-level high`（前端）。
- CI **缺**：Python 依赖漏洞扫描（pip-audit / OSV-Scanner）、SAST（bandit / semgrep / CodeQL）。SEC-01/02 这类问题本可由 SAST + 针对性规则更早发现。
- 依赖版本滞后（跨服务不一致）：
  - `document-parser`：`pymongo==3.13.0`（其余两服务为 `4.18.2`，3.x 为已停止维护分支）、`uvicorn==0.29.0`（其余为 `0.54.0`）、`redis==6.4.0`（其余为 `8.1.0`）。
- `admin-api` 与 `chat-api` 的 `fastapi` 版本也不一致（`0.142.2` vs `0.141.1`）。

**修复**：CI 增加 `pip-audit -r requirements.txt` 与 `bandit -r services/*/app`；统一三服务的 `pymongo`/`uvicorn`/`redis`/`fastapi` 版本基线。

---

## 四、已确认良好的部分（基线）

以下为本次实测确认**不存在**问题的项，供后续审计避免重复排查：

- **密钥入库**：`git ls-files` 仅追踪 `.env.example` 系列，真实 `.env` 未入库；`.env.example` 中所有 `*_API_KEY`/`*_TOKEN`/`*_SECRET` 均为空占位；`.gitignore:157-158` 治理正确。
- **JWT 实现**（`admin-api/app/core/security.py`）：自实现 HMAC-SHA256 签名令牌，格式固定（无 `alg` 头，天然免疫 `alg:none`）；**先验签后解析**；`hmac.compare_digest` 常量时间比较；校验 `exp`。refresh token 具备轮换 + 重放检测（`fid` 家族级吊销），recovery token 为 256-bit 随机、仅存 SHA-256 哈希。
- **口令哈希**：PBKDF2-HMAC-SHA256，120,000 次迭代，随机 salt，`compare_digest` 校验（admin-api 与 chat-api 一致）。
- **SQL 注入**：全仓未发现 `execute()` 中使用 f-string / `%` / `.format()` / 字符串拼接。
- **命令注入**：唯一两处 `subprocess` 调用自有代码（`document-parser/app/integrations/converters/libreoffice.py:56,92`）均使用**列表参数、无 `shell=True`**，且带 `timeout`，无注入面。
- **危险反序列化**：自有代码中无 `eval`/`exec`/`pickle.load`/`yaml.load`（`__import__` 命中均为 `hmac`/`re`/`os` 的防御性写法）。
- **NoSQL 注入**：`admin-api/app/core/nosql_guard.py` 递归剥离 `$` 前缀操作符，作为仓储层兜底。
- **脚本沙箱的已具备能力**：子进程隔离（`python -I`）、最小化环境变量（`_safe_env`）、网络禁用（socket 打桩）、`RLIMIT_CPU/AS/FSIZE`、stdout/插件体积上限、临时目录 per-request 隔离。
- **CORS**：`chat-api/app/main.py:49-55` 使用显式 origin 列表（默认 localhost），非 `*`。
- **nginx**：HTTPS 配置含 HSTS、nosniff、X-Frame-Options、Referrer-Policy、Permissions-Policy。
- **compose**：密钥卷以 `:ro` 挂载；`bootstrap` 用 `umask 077` 生成；无 `privileged`、无 `network_mode: host`、无 `cap_add`。

---

## 五、建议的处置顺序

| 顺序 | 动作 | 对应 | 状态 |
| --- | --- | --- | --- |
| 1 | 从 `chat-api` 移除 `deployment-secrets` 卷挂载，改为按需注入单变量 | SEC-01 | 待办（最高优先） |
| 2 | 修复 `executor.py` runner 的守卫安装顺序，并覆盖 `io.FileIO`/`os.scandir` 等 | SEC-01 | **已完成** |
| 3 | 4 处令牌比较改用常量时间比较 | SEC-04 | **已完成** |
| 4 | 三个 Dockerfile 增加非 root `USER` + compose 加 `no-new-privileges`/`cap_drop` | SEC-05 | 待办 |
| 5 | 在 `compile_script_plugin` 强制 AST 校验 | SEC-02 | 待办 |
| 6 | CI 增加 pip-audit + bandit | SEC-08 | 待办 |
| 7 | `encryption.py` 迁移到 `cryptography` 的 AESGCM+HKDF | SEC-03 | 待办 |
| 8 | nginx 增加 CSP（先 Report-Only） | SEC-06 | 待办 |
| 9 | 限流器内存回退加界 + 启动期 Redis 校验 | SEC-07 | 待办 |
| 10 | `socket.socket` 打桩改为子类，恢复 `ssl`/`pptx` 可用性 | SEC-09 | 待办 |

> 第 2、3 项已实施，见第七节。**注意：第 2 项只是纵深防御，不能替代第 1 项**——只要密钥卷仍挂在 chat-api 且容器仍是 root，就仍存在其他逃逸路径。

---

## 六、复现与验证方式

- SEC-01 / SEC-02：阅读 `executor.py`（runner 源码字符串）与 `script_contract.py:9-45`，确认修复前 `exec_module` 早于 `builtins.open` 打桩，且 `compile_script_plugin` 无校验调用。
- SEC-03：对比 `encryption.py` 的 docstring（第 1-8、34-42 行）与实际函数体（`_derive_key`、`_derive_keystream`、`_compute_tag`）。
- SEC-04：`grep -n "!= settings" services/*/app/**/*.py`，与常量时间比较的使用点对比。
- SEC-05：`grep -c '^USER' services/*/Dockerfile deploy/docker/gateway.Dockerfile` → 全部为 0。
- SEC-06：`grep -rn 'Content-Security-Policy' deploy/ apps/ services/` → 无命中。
- SEC-07：阅读 `rate_limiter.py:52-125`。
- SEC-09：在沙箱内 `import pptx` → `TypeError: function() argument 'code' must be code, not str`（`ssl.py` 的 `class SSLSocket(socket)` 因 `socket.socket` 被替换为函数而失败）。

---

## 七、本轮修复记录（2026-10-11 21:2x）

### 7.1 SEC-01：runner 守卫顺序与覆盖范围

改动文件：`services/chat-api/app/enterprise_capabilities/data/script_engine/executor.py`（`_runner_source()`）。

1. **守卫提前到插件导入之前**。`exec_module` 现位于守卫安装语句之后，插件顶层语句不再在无守卫状态下执行。
2. **补齐原始入口**。新增 `io.FileIO` / `_io.FileIO` 守卫（以 `_io.FileIO` 子类实现，保持 `isinstance` 语义），并新增 `os.scandir` 守卫；原有 `builtins.open` / `io.open` / `os.open` 守卫保留。
3. **预热允许导入的模块**。守卫提前后，`openpyxl` 等库在导入期读取系统配置（如 `/etc/mime.types`）会被守卫拦下。因此在安装守卫**之前**预热 `mimetypes` 及允许清单内的模块，恢复 HEAD 行为。

对照实验（`git show HEAD:...` 取原始 runner，同一插件分别跑两版）：

| 攻击向量 | 修复前 | 修复后 |
| --- | --- | --- |
| 顶层 `open('/etc/hosts')` | 泄漏文件内容 | `PermissionError` |
| `io.FileIO` / `_io.FileIO` | `LEAKED` | `PermissionError` |
| `os.scandir('/etc')` | 泄漏目录列表 | `PermissionError` |

回归验证：对允许清单内 13 个模块逐个对照 HEAD 与修复后的导入行为，**零回归**（`pptx` 两版均失败，属 SEC-09 既有缺陷）。预热循环经"移除后复测"确认是必需的（去掉后 `import openpyxl` 失败）。

新增测试 6 个，位于 `services/chat-api/tests/dsh_runtime/test_document_script_boundaries.py`。

### 7.2 SEC-04：令牌常量时间比较

- `services/document-parser/app/core/security.py`：新增 `constant_time_equals()`，`verify_service_token` 改用之。
- `services/admin-api/app/core/security.py`：新增同名 `constant_time_equals()`。
- `services/admin-api/app/api/routes/knowledge_documents.py`：3 处 callback 令牌校验改用该 helper。

实现要点：两侧统一 `.encode("utf-8")` 后再 `hmac.compare_digest`。**不能**直接对 `str` 调 `compare_digest`——非 ASCII 的 `Authorization` 头会触发 `TypeError`，把 401/403 变成 500。已用 8 组用例（含中文、`None`、空串）验证语义与原有 `!=` 一致。

### 7.3 仍未覆盖的残余风险（重要）

- **`os.listdir` 未受限**：`importlib._bootstrap_external` 依赖 `_os.listdir`（第 1676 行）完成模块查找，补丁化会直接破坏所有导入，因此本轮**未**处理。目录名枚举仍可行（不泄漏文件内容）。
- **`_io.open_code` 未受限**：同理，`importlib` 用它加载 `.py`（第 1214 行），补丁化会破坏导入。
- **`os.fork` / fork bomb**：`RLIMIT_NPROC` 仍未设置。
- **SEC-01 的根因未消除**：本轮只是把补丁式守卫做扎实。只要 `chat-api` 仍挂载密钥卷、容器仍以 root 运行，补丁式沙箱就不是安全边界。**处置顺序第 1 项（移除密钥卷挂载）仍应优先执行。**
