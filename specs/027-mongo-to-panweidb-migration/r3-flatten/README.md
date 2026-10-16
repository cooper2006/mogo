# 027-R3 扁平化迁移产物（mogo_dev.mogo_dev）

本目录是 **R3 关系扁平化**（方案 `docs/027-r3-relational-four-tables-plan.md`）在
PanWeiDB / openGauss 3.2.0 的**实体库落地产物**：加列 DDL、数据回填、索引，以及生成与审查脚本。

- **执行时间**：2026-10-16
- **目标库**：`mogo_dev` 数据库的 `mogo_dev` schema（库名与 schema 名相同）
- **执行结果**：四个阶段全部成功，**0 错误**

## 执行方式（连接通道）

原生 `psql` 连不上（openGauss 3.2.0 的 MD5 认证与 PostgreSQL 不同，`boncuser` 曾因反复认证失败被锁，
需 `ALTER USER boncuser ACCOUNT UNLOCK` 解锁）。可用通道是容器内 `local all all trust` 免密：

```bash
docker cp <sql文件> panweidb:/tmp/<name>.sql
docker exec panweidb sh -c "su - omm -c 'export PATH=/database/panweidb/soft/bin:\$PATH; export LD_LIBRARY_PATH=/database/panweidb/soft/lib:\$LD_LIBRARY_PATH; gsql -d mogo_dev -U omm -f /tmp/<name>.sql'"
```

注意：`su - omm` 内外层 shell 的单引号会与 SQL 单引号冲突，用外层双引号 + heredoc `<<'EOF'` 结构
（见 `collect_keys.sql` 的生成器 `collect.py` 中的用法）。panweidb 是独立容器，不在 compose 文件里。

## 文件清单与执行顺序

| 文件 | 用途 | 状态 |
|---|---|---|
| `01_add_columns.sql` | 455 条 DO 块加列（44 张平铺表）。openGauss 不支持 `ADD COLUMN IF NOT EXISTS`，故用 DO 块查 `information_schema.columns` 判断，**可重跑** | ✅ 已执行 |
| `02_backfill.sql` | 455 条回填：只处理**同名列**（doc 内 snake_case 同名 key → 列） | ✅ 已执行 |
| `03b_backfill_fix.sql` | 24 条高/中置信度**语义映射**回填（doc 早期 Mongo 字段名有别名差） | ✅ 已执行 |
| `03_indexes.sql` | 44 条索引：带 `WHERE deleted_at IS NULL` 的部分 `UNIQUE` 索引 + 普通索引 | ✅ 已执行 |
| `column_types.md` | 逐列类型审查清单（依据方案 §8.A + 命名规则推断；方案未给列类型） | 审查产物 |
| `candidate_mapping.md` | 107 个缺失列的候选 `doc_key` 映射表（高/中/低/留空），中置信度歧义逐条标注 | 审查产物 |
| `mapping_report.md` | 列名 vs doc key 匹配分析（哪些列 doc 无对应字段） | 审查产物 |
| `gen.py` | 解析方案 §3 表格 → 生成 01/02/03 SQL + `column_types.md` | 工具 |
| `gen_fix.py` | 基于 doc 真实 key 生成候选映射表 + 03b SQL | 工具 |
| `collect.py` / `collect_keys.sql` | 导出各表 doc 实际 key（供匹配分析） | 工具 |
| `analyze.py` | 列名 vs doc key 匹配分析 → `mapping_report.md` | 工具 |
| `exec_01.txt` … `exec_03b.txt` | 四个阶段的执行日志（gsql 原样输出，含 `UPDATE/ANONYMOUS BLOCK EXECUTE` 回显）。仓库 `.gitignore` 忽略 `*.log`，故以 `.txt` 存档 | 执行证据 |

工具默认读写 `/tmp/migration/`，归档副本仅作留存；重跑时改 `OUT`/路径即可。
`keys.txt`（约 200KB 导出的 doc key 明细）可用 `collect.py` + `collect_keys.sql` 重新生成，未入库。

## 执行结果（实测）

| 项 | 结果 |
|---|---|
| 平铺表数 | **44**（✅21 全平铺 + 🔶23 部分平铺） |
| 加列 | **455 列**，0 错误；抽查列数与预期完全吻合 |
| 同名列回填 | 455 条 UPDATE，0 错误 |
| 语义映射回填 | 24 条 UPDATE，0 错误；抽查值与 doc 完全一致 |
| 索引 | **44 条**，0 错误；库内现存索引 491 个（本目录 44 + 既有 btree 447） |

## 踩坑与注意事项

1. **方案文档末尾统计段有笔误**：写的"24/30/60"与 §3 表格实际内容（21/23/70=114）不符；
   正确结论是 **44 张表需扁平化**。本文档结论以 §3 表格实测为准。
2. **openGauss 不支持 `ALTER TABLE ADD COLUMN IF NOT EXISTS`**（首次执行因此全失败），
   必须用 DO 块查 `information_schema.columns` 判断。
3. **doc 字段名与列名不是简单同名**：doc 是早期 Mongo 原始字段名，存在别名差
   （`login_name←username`、`organizations.name←org_name`、`chat_sessions.owner_user_id←user_id`、
   `skills.data←config`、`pii_policies.rules←strategy` 等）。机械按列名回填只填中同名字段，
   剩余 107 列经候选映射补齐了 24 列高/中置信度。
4. **部分唯一索引遇留空列不冲突**：标准 SQL 中唯一索引的多个 NULL 视为互异，故
   `org_quota_policies.org_id`、`end_user_position_roles.position_id`、`autonomy_matrix.*`
   等留空列上的部分唯一索引可正常创建。
5. **回填可重跑**：全部 `UPDATE ... WHERE doc->>'key' IS NOT NULL` 形式，重复执行结果一致。
   但注意：若应用随后通过 `doc` 写入新值，重跑回填会用旧 doc 值覆盖列值。

## 遗留项（未映射列保持 NULL）

约 83 列留空，待兼容层 `COLUMN_MAP`（方案 §5）实现后由应用双写填充：

- **doc 结构完全不同的表**：`autonomy_matrix`（doc 仅 cell/risk/level/decision）、
  `gatekeeper_rules`（仅 kind/mode 等）；
- **doc 无对应字段**：`tenants`/`organizations` 的 description/contact_*/address/logo_url/settings、
  各表的 avatar_url/password_algorithm/failed_login_count/locked_at/last_login_ip/mfa_enabled 等；
- **低置信度**：`skills.status ← is_active`（bool → TEXT 语义接近但不同，未采纳）。
- `external_search_configs.api_key_encrypted`/`endpoint`：doc 中在 `config` 对象内，平铺列取不到。

明细见 `candidate_mapping.md`。
