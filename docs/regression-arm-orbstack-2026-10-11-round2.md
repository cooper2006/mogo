# OrbStack ARM 准生产环境回归测试报告（第二轮）

- **日期**：2026-10-11 19:20–19:40 CST
- **环境**：OrbStack 2.2.3，Docker Server `aarch64/linux`（Server 29.4.0），镜像 tag `51a442a`
- **回归对象**：上一轮（`b4d8782` 修复后）之后推进的 **7 个提交**
- **与上一轮的区别**：本轮分支核心变更是 **document-parser 的 Python 3.13 升级 + docling 降级至 2.108.0**，
  故重点放在该变更的真实生产影响，而非重复上轮已验证的内容

---

## 一、结论摘要

| 维度 | 判定 |
| --- | --- |
| ARM 架构正确性 | **通过**——7 个应用镜像 + LB 全部原生 `linux/arm64`，无 emulation |
| document-parser 升级 | **通过**——Python 3.13.16、docling 2.108.0 离线运行时正常，**声称修复的生产 PDF OCR bug 已用真实推理坐实** |
| 三服务全量回归 | **通过**——**2717 项测试 0 失败**（chat-api 2262 / admin-api 433 / document-parser 22） |
| 部署栈可用性 | **通过**——14 容器 healthy，路由全 200 |
| 上轮修复（D1/D2/D3） | **均未复发**——DSH 恰 3 副本+LB、LB `RestartCount=0`、孤儿数据 0 |
| 韧性与不变量 | **通过**——副本故障转移可用、sticky 粘性 8/8 命中同一上游 |
| CI 同款检查 | **通过**——`check_compose_image_modes` + 三种 compose 配置校验 |

**总体**：OrbStack ARM 环境继续可作为准生产使用。本轮**未发现 ARM 特有缺陷**，也**未发现
document-parser 3.13 升级引入的回归**；反而确认该升级**修复了一个真实的生产 PDF OCR 故障**。

---

## 二、环境基线

- 镜像 tag `51a442a`，全栈运行 4 小时；`bootstrap` 正常 Exited(0)。
- Docker Server `aarch64/linux`；OrbStack 2.2.3。
- document-parser 容器内实测依赖，与 `requirements-docling.txt` 钉定**完全一致**：

| 包 | 版本 |
| --- | --- |
| Python | 3.13.16 |
| docling | 2.108.0 |
| docling-core | 2.99.0 |
| docling-ibm-models | 3.15.0 |
| docling-parse | 7.22.2 |
| rapidocr | 3.8.4 |
| numpy | **2.5.2** |
| torch | 2.14.1+cpu |
| onnxruntime | 1.22.1 |

> **numpy 由 1.26.4 升到 2.5.2**——跨大版本（NumPy 2.x 有 ABI 破坏性变更），
> 是本次升级风险最高项，故列为重点验证对象。

---

## 三、重点验证：document-parser 升级

### 3.1 声称修复的生产 PDF OCR bug —— **确认修复**

提交 `51a442a` 声称修复 "rapidocr v3→v4 模型不匹配"，评审文档称旧版 PDF OCR **失败**
（`en_PP-OCRv3_det_mobile.onnx` 不存在）。本轮以**真实推理**验证：

**证据链（三重）**：

1. **模型文件实证**
   - bundle：`/opt/docling/models/RapidOcr/onnx/PP-OCRv4/`（中文 v4 三件套）
   - 包内：`rapidocr/models/ch_PP-OCRv4_{det,rec}_mobile.onnx` + `ch_ppocr_mobile_v2.0_cls_mobile.onnx`
   - **全容器搜索 `en_PP-OCRv3_det_mobile.onnx`：不存在**（即旧版报错的那个文件）
2. **引擎加载日志**：`Det` / `Cls` / `Rec` 三模型均 `File exists and is valid`，
   **无下载请求、无异常**
3. **真实 OCR 推理结果**：
   ```
   ('Hello MOGO OCR 2026', 'Regression Test')
   ```
   识别内容与渲染文本完全一致。

**判定**：旧版 OCR 失败在本版本不复现，**修复属实**。

### 3.2 docling 离线运行时 + numpy 2.x 兼容性 —— **通过**

- `DocumentConverter()` 构造成功
- `StandardPdfPipeline(pipeline_options=PdfPipelineOptions())` + `download_models=False`
  加载 **770 项权重，零网络请求**（模型全部来自 bundle）
- `HybridChunker`、`BaseTokenizer`、`PdfPipelineOptions` 均可导入

### 3.3 真实 PDF 端到端解析 —— **通过**

宿主机手工构造合法 PDF（775 字节，不依赖 reportlab 等外部库），`docker cp` 进容器后：

- `DocumentConverter().convert()` → **`ConversionStatus.SUCCESS`**
- 标题识别为 `SectionHeaderItem`、段落为 `TextItem`，`prov` 坐标与 `charspan` 全部正确
- 直接调用生产函数 `chunk_docling_document()`（`document_parsing_service.py:178`）→
  返回 1 块：`'Service: document-parser Docling 2.108.0 on Python 3.13\nARM aarch64 native'`
  **完全离线**

### 3.4 两处"失败"经查均非缺陷（记录以免误判）

验证过程中出现的两次报错，追查后确认**均为探测代码写法问题，不是服务缺陷**：

| 现象 | 真实原因 |
| --- | --- |
| 裸 `HybridChunker()` 报连不上 HuggingFace | 生产代码注入本地 `AskAILocalTokenizer`（`_estimate_token_count` 正则估词），**刻意规避**了联网 |
| 自造 tokenizer 对象被 pydantic 拒绝 | 生产 `AskAILocalTokenizer` **继承** `BaseTokenizer`，故满足类型约束 |

两条路径合起来恰好证明：生产代码对 docling 2.108 的新 API 适配是**正确且完整**的。

---

## 四、回归结果

| 服务 | tests | failures | errors |
| --- | --- | --- | --- |
| chat-api | 2262 | 0 | 0 |
| admin-api | 433 | 0 | 0 |
| document-parser | 22 | 0 | 0 |
| **合计** | **2717** | **0** | **0** |

> 测试窗口 19:2x CST，非凌晨时段，与 R1（跨午夜时间炸弹）缺陷窗口无关。

---

## 五、上轮修复的复发检查

| 项 | 检查方式 | 结果 |
| --- | --- | --- |
| **D2**（空转副本） | `docker compose ps` 统计 DSH 容器 | 恰为 **3 副本 + LB**，空转副本未回来 |
| **D1**（LB DNS 陈旧） | `docker inspect` LB | **`RestartCount=0`**，保持 reload 而非 restart |
| **D3**（孤儿数据） | MongoDB 查询 `organizations` | `setup-test-*` 残留 **0** |
| 数据完整性 | tenants / chat_messages | tenants **2**、BONC chat_messages **18**、BOND 混入 **0**（与上轮一致） |

---

## 六、韧性与不变量

**副本故障转移**：停止 `dsh-runtime-host-2` 后

- `/askai-api/health` → **200**、`/healthz` → **200**
- LB 日志显示正常分流至剩余副本（`max_fails=3 fail_timeout=10s` 熔断生效）
- 已 `start` 恢复，15 秒内回到 **healthy**

**sticky 会话粘性**：同一 `X-Isolation-Key` 连续 8 次请求，LB 日志显示
**8/8 全部命中同一上游 `192.168.107.5:8101`**。

> 这再次确认了 D1 的方案价值：采用 `nginx -s reload` 而非变量式 `proxy_pass`，
> 正是**保住了 `hash $dsh_sticky_key consistent` 会话粘性**的关键。

---

## 七、CI 同款检查

- `scripts/check_compose_image_modes.sh` → **PASS**（本轮提交 `9f165fc` 改过镜像裸名，该门禁仍然有效）
- `docker compose config`（默认 / `-f docker-compose.build.yml` / `--profile single-host`）→ **三种均通过**

---

## 八、本轮发现（不构成缺陷）

`docs/pr-review-2026-10-11-docling-3.13-upgrade.md:25` 称
「`BaseTokenizer` 等生产 API 兼容全通过」。但在 docling 2.108 中，旧路径
`docling_core.transforms.tokenizer.base_tokenizer` **已失效**——模块被重构为
`docling_core.transforms.chunker.tokenizer.base`。

生产代码 `document_parsing_service.py:181` **用的正是新路径**，故运行正常；
但若外部或后续代码沿用旧路径则会 `ImportError`。

**建议**：在该评审文档中标注实际路径，避免误导后续维护者。本轮**未改动该文档**
（属其他会话产物，且不影响运行），仅在此记录。

---

## 九、未覆盖面（诚实记录）

- ~~**本地三服务 venv 仍为 Python 3.12，容器内已 3.13**~~ — **已于同日补齐**：
  三服务 venv 全部升级到 **Python 3.13.16**（与容器内版本完全一致，也与 CI matrix 对齐），
  2717 项测试在 3.13 下重跑**全绿**。详见 `docs/WORK_LOG.md` 同日
  「三服务 venv 升级到 Python 3.13」条目。

  > **但仍有一处未闭合**：`requirements-docling.txt` 内部存在平台相关矛盾
  > （钉 `transformers==5.10.0`，而同文件 `docling-ibm-models==3.15.0` 在 darwin 分支要求
  > `transformers<5.9.0`），导致 **docling 组无法在 macOS 本地安装**（Linux 生产无此限制）。
  > 经用户拍板不改生产依赖，故 docling/rapidocr 相关代码**仍未进入 3.13 的 pytest 覆盖范围**，
  > 继续由 §3.1–3.3 的容器内真实推理保证。
- 未执行 `./mogo build` 全量重建（本轮以现有 `51a442a` 镜像为回归对象）。
- `tests/benchmarks/` 三项专项基准未执行。
- 单副本（`--profile single-host`）拓扑仅配置校验，未实跑。
- D4（OrbStack virtiofs 挂载长时运行失效）本轮**未复现**，LB 已连续运行 19 小时正常。

---

## 十、判定

**通过。** OrbStack ARM 环境可继续作为 ARM 准生产环境使用。

本轮核心价值在于：把"提交声称修复了生产 PDF OCR bug"从**文档声明**升级为
**三重复合证据（文件存在性 + 引擎加载日志 + 真实推理结果）**，并确认
Python 3.13 + numpy 2.5.2 + docling 2.108 在 aarch64 原生环境下离线运行正常。
2717 项测试 0 失败，上轮三项修复均未复发。