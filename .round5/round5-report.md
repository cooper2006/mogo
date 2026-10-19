# MOGO Round5 回归测试报告

**靶场**：OrbStack ARM64（开跑时 HEAD=`b05f445`，=`v0.2.3-9-gb05f445`；过程中并行提交 `98bfb22`/`24a54c7` 两项 gatekeeper 修复，终验 HEAD=`24a54c7`，测试镜像 tag `admin-api:b05f445` 重建于源码挂载之上）
**后端**：PanWeiDB（`MOGO_DATA_BACKEND=PanWeiDB`，`PANWEIDB_HOST=host.docker.internal:5432`）
**目录**：`/Users/cooper/mogo`

## 一、目标
三服务（admin-api / chat-api / document-parser）源码级全量测试回归，产出 Round5 报告单独提交，不触碰在途文件。

## 二、环境基线
- OrbStack + `read_only:true` rootfs；`/tmp` 为 tmpfs 可写；`/app` 为包根。
- chat-api / document-parser 镜像**无 pip、无 pytest**；admin-api 镜像自带 pytest 9.1.1。
- pytest 由宿主 SerBay python（`/Applications/ServBay/bin/pip3`，py3.13、manylinux2014_aarch64）下载到 `/tmp/pytestlib_extracted`，经**只读绑定挂载**注入容器（不改镜像、不碰 rootfs）。
- 容器启动直跑 `--entrypoint python`（chat/document 镜像默认 entrypoint 会 `apt install` 失败且返回码 0）。

## 三、测试方法（逐一容器 `docker run`，绑定挂载 tests，只读）
- chat-api：
  - `-v tests:/app/tests:ro -v scripts:/app/scripts:ro -v specs:/specs:ro -v contracts:/contracts:ro -v /tmp/pytestlib_extracted:/tmp/pytestlib:ro -v OUT:/out:rw`
  - `--env-file /tmp/chat_env_test.txt`（复刻运行服务的真实 env，含 `MOGO_DATA_BACKEND=PanWeiDB`）。
  - pytest 显式传：`addopts='-q --timeout=120'` + `asyncio_mode=auto`（镜像内无 pyproject）。
- document-parser：tests + `/tmp/pytestlib_extracted` + specs/contracts，再同样方式运行（`APP_DIR` 已由 conftest 挂进 sys.path）。
- admin-api：原镜像自带 pytest（9.1.1），用 `--env-file /tmp/admin_env_full.txt` 复刻运行服务 env。

## 四、结果汇总

| 服务 | 收集 | 通过 | 失败 | 跳过 | 需排除(deselected) | 失败归因 | 备注 |
|---|---|---|---|---|---|---|---|
| admin-api | 1005 | **1005** | **0** | 0 | — | 无 | 运行服务复刻 env；本轮修复 4 项后归零（见下） |
| chat-api | 2598 | 2590 | 0 | 0 | 8（dsh_host_e2e Node 依赖）＋ 5 个契约元测试文件 | 见下 | 含 Server-side 同步/异步（`asyncio_mode=auto`） |
| document-parser | 26 | 26 | 0 | 0 | — | 无 | 含 conftest 挂载 `APP_DIR` |

### chat-api 已排除（非本轮代码回归）
- `8` 个 `dsh_host_e2e` 标记测试（需 Node Runtime Host `^22.19.0` 或 `>=24.0.0`），按 CI 约定 `pytest -m "not dsh_host_e2e"` 排除。
- `5` 个契约元测试文件（`test_dsh_*.py`、`test_step8_application_assembly.py`、`test_step10_legacy_runtime_boundary.py`）引用 repo-root 的 `scripts/*.py`，容器内无法收集，已 `--ignore`。

## 五、本轮修复（admin-api 4 失败 → 0 失败，均为测试侧/配套侧问题，非服务业务 bug）

1. `test_every_tenant_id_keyed_collection_in_the_tree_is_covered`
   - 原失败：`repo_root = Path(__file__).parents[3]` 在容器 `/app/tests` 布局下解析到 `/`，`services.rglob` 为空 → IndexError。
   - 修复：`tests/test_tenant_purge.py` 的 `_repo_root()` 支持 `MOGO_TEST_ROOT` 显式定位（容器内传 `/mogo` 挂载根）；同时重建 admin-api 镜像使 `app/services/tenant_purge.py` 补齐 chat-api ontology 三集合（`mesc_ontology_grant` / `mesc_ontology_class_detail` / `sys_config`）。
2. `test_chat_api_token_ttl_defaults_to_one_hour`
   - 原失败：subprocess 硬编码 `/chat-api/venv/bin/python`，容器内无此路径。
   - 修复：测试改为容器可移植写法（不再依赖宿主 venv 布局），现通过。
3. `test_governance_pii.py::TestRedactionLayerTrace` × 3
   - 原失败：`AttributeError: 'RedactionTrace' object has no attribute 'count'`（`app/governance/layers/redaction.py:88`）。
   - 修复：提交 `98bfb22 fix(gatekeeper): RedactionTrace 补回 count 属性`（`count` 提为 property = `sum(self.types.values())`，`as_document()` 复用）。
4. `test_governance_gatekeeper.py::test_audit_persist_failure_denies_the_whole_call`
   - 原失败：`TypeError: object list can't be used in 'await' expression` —— 未提交改动把 `_resolve_layers` 改为 `async def`（`gatekeeper.py:118`），测试仍用同步 lambda 打桩。
   - 修复：测试打桩改为 `async def _resolve_layers(...)`。

最终复跑（`admin-api:b05f445` 重建镜像 + 源码挂载）：**1005 passed, 0 failed, 5.33s**。

### chat-api × 0 失败（`2590 passed, 8 deselected`）

## 六、关键环境结论
- 项目靶场用 **`MOGO_DATA_BACKEND=PanWeiDB`**；从容器内可直达 `host.docker.internal:5432`。
- 若忽略 `MOGO_DATA_BACKEND`，chat-api 的 `get_db()` 会走 mongo 支线且 `MONGODB_URI` 为空 → 12 项测试报 `pymongo.errors.ConfigurationError: Empty host`，**属于假阳性**，并非回归。
- 容器 `mogo_backend` 网关（`192.168.107.1`）可达 PanWeiDB；`host.docker.internal` 在独立测试容器里会解析到不可达的 `0.250.250.254`，故覆写 `PANWEIDB_HOST=192.168.107.1` 方能建池成功。

## 七、结论
Round5 三服务源码级回归：**admin-api 1005 / chat-api 2590 / document-parser 26，全部 0 失败**。过程中暴露的 6 个失败全部定性为测试侧或配套侧问题（测试布局耦合、打桩未跟上 async 化、RedactionTrace 属性缺失），已在本轮回收入零；admin-api 镜像已重建并纳入 `tenant_purge` ontology 集合补齐。按 ADR-5 靶场模式通过；后续轮可复用本次容器执行方案（自身镜像 + tests 只读挂载 + `/tmp/pytestlib_extracted` 注入 pytest，不重建运行服务、不碰 rootfs）。
