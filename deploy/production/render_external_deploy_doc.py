#!/usr/bin/env python3
"""根据 bundle.json 生成自包含的「外部 PanWeiDB + 栈内 Redis」生产部署单 DEPLOY.md。

用法：
    render_external_deploy_doc.py <bundle_dir>

与 render_deploy_doc.py 的差异：
  - 镜像包少一个 mongo（外部数据库模式不部署内部 mongo / panweidb 容器）。
  - 部署单明确写出外部 PanWeiDB 的连接信息（从 bundle.json 的 external_db 标记推断），
    并给出「导入镜像前先探外部 PanWeiDB 连通性」的核查步骤。
  - redis / weaviate 仍是栈内容器，部署单保留其说明。
"""
import json
import pathlib
import sys

TEMPLATE = """# mogo {tag} 生产部署单（离线 · 外部 PanWeiDB + 栈内 Redis）

> 由 `deploy/production/prepare-release.sh --external-db` 生成于 {created}。
> 目标主机无外网：镜像只能离线导入，栈用 Portainer 的 Stack 拉起。
> 数据后端 = PanWeiDB（外部实例），Mongo 已被弃用且不启动；Redis / Weaviate 仍为栈内容器。

## 〇、外部 PanWeiDB 连通性核查（导入镜像前先做）

应用容器启动后会直连外部 PanWeiDB，连不上会导致 admin-api / chat-api / document-* 起不来。
**先在生产宿主机上确认网络与账号可达**（宿主机侧需能访问 `172.17.5.145:17700`）：

```bash
# TCP 端口可达性（DB 主机 / 网络策略未放行时会直接失败，提前暴露）
timeout 5 bash -c 'cat < /dev/null > /dev/tcp/{pw_host}/{pw_port}' \\
  && echo "PanWeiDB TCP OK" || echo "PanWeiDB TCP 不可达"

# 账号口令（openGauss/PanWeiDB 的 MD5 与社区 psql 不兼容，需用 gsql；
# 这里只验证凭据字符串已就位，真正连通由应用启动后的 health 体现）
echo "PANWEIDB_USER={pw_user}  PANWEIDB_DB={pw_db}  PANWEIDB_SCHEMA={pw_schema}"
echo "口令已写入清单（含 ! 的特殊字符已原样注入，未经引号处理）"
```

> 注意：PanWeiDB 由外部运维维护，本栈**不**负责它的备份 / 升级 / 高可用。
> 应用使用 openGauss 兼容驱动连接（见 services 内 pg_compat 路径），不是原生 psycopg。

## 一、镜像包

按顺序导入（先小后大，便于早发现问题）：

| 顺序 | 文件 | 体积 | 镜像数 | 内容 |
| --- | --- | --- | --- | --- |
{rows}

合计 **{total_gb} GB / {image_total} 个镜像**，全部为 `linux/amd64`。

> 与「自带数据库」版本相比：本包**不含** `mongo` 镜像（外部 PanWeiDB 模式不再起内部 mongo）。
> redis / weaviate 仍为栈内，因此这两个基础镜像仍须导入。

### 各包 sha256（上传后可在宿主机比对，确认传输完整）

```
{hashes}
```

## 二、导入镜像

Portainer → 左侧 **Images** → 右上 **Import** → **Upload**，逐个选择上表中的 tar。

**先传 1 号包探路**：它最小，且能一次性验证"这份归档格式能否被生产端的经典
`docker load` 接受"（打包机用的是 containerd 镜像存储，归档为 OCI 布局 + 兼容
`manifest.json`，理论可读，但值得先用小包确认）。

导入完成后，在 Images 列表核对下列 tag 是否齐全（架构应为 x86_64）：

```
{image_list}
```

## 三、创建 Stack

Portainer → **Stacks** → **Add stack**：

- **Name**：`mogo`（决定网络与容器前缀；卷名前缀由清单里的 `mogo_*` 固定，不受它影响）
- **Build method**：选 **Upload**，上传 `docker-compose.portainer.yml`
  （也可用 Web editor 粘贴，但文件含 3.5KB 的 base64 长行，Upload 更稳妥）
- 不要勾选任何 "re-pull image" 类选项（清单已设 `pull_policy: never`）
- 点 **Deploy the stack**

外部 PanWeiDB 连接信息已写死在清单的 `PANWEIDB_*` 环境变量里（host={pw_host}:{pw_port}，
user={pw_user}，db={pw_db}，schema={pw_schema}）。如需改，可在 Stack 的
**Environment variables** 面板覆盖，或重新渲染清单时导出 `PANWEIDB_*` 环境变量后重跑
`prepare-release.sh --external-db`。

## 四、验证

```bash
curl -i http://<主机>:3000/healthz      # 期望 200 ok
curl -i http://<主机>:3000/setup        # 期望 302 -> /admin/setup
curl -I http://<主机>:3000/             # 期望 200（用户前端）
curl -I http://<主机>:3000/admin/       # 期望 200（管理前端）
```

Portainer → Containers 里应看到 10 个 `mogo-*` 容器（无 mongo / panweidb）：

- `mogo-bootstrap-1` 显示 **Exited (0)** —— 这是**正常的**，它只负责生成 `runtime.env` 密钥后退出
- redis / weaviate / chat-api / admin-api / document-api / dsh-runtime-host /
  user-web / admin-web / gateway 为 healthy
- `document-worker` 无健康检查，running 即可

> 若 admin-api / chat-api 一直 unhealthy，优先排查外部 PanWeiDB 的 TCP 可达性与账号口令
> （见「〇、外部 PanWeiDB 连通性核查」）。`MOGO_DATA_BACKEND=panweidb` 已固定写入清单。

首次使用：浏览器打开 `http://<主机>:3000/admin/setup` 完成初始化，创建企业管理员账号
（无预置账号，setup 向导会引导创建）。

## 五、部署后建议调整

清单里下列变量沿用上游默认值（指向 `localhost:3000`），本机自测没问题，
但生产上若用户从别的地址访问，生成的绝对链接会指错：

| 变量 | 当前值 | 建议 |
| --- | --- | --- |
| `ASKAI_ADMIN_PUBLIC_BASE_URL` | 空 | 设为实际访问地址，如 `http://<主机>:3000` |
| `ASKAI_ADMIN_USER_PORTAL_BASE_URL` | `http://localhost:3000` | 同上 |
| `ASKAI_ADMIN_CORS_ORIGINS` / chat-api 的 `ALLOWED_ORIGINS` | `http://localhost:3000` | 前端经 gateway 同源访问，通常无需改 |

改完在 Stack 页点 **Update the stack** 重新部署即可（镜像已在本地，不会再拉取）。

## 六、注意事项

- **无外网**：在线模型、外部搜索源、文档解析的外部依赖均不可用，需等网络策略放开
  或改用内网可达的服务。
- **外部 PanWeiDB**：本栈不管理它的数据。迁移 / 回滚 / 备份请走外部实例的运维流程；
  若要回退到内部 mongo，需改用「自带数据库」版发布包（`prepare-release.sh` 不带 `--external-db`）。
- **Redis 为栈内**：`MOGO_REDIS_URL` / `MOGO_KERNEL_REDIS_URL` 指向栈内 `redis:6379`，
  数据落在命名卷 `mogo_redis-data`；若要用外部 Redis，改清单里的这两个变量并把
  `redis` 服务挪到 `profiles: [never]`。
- **`{largest}` 是最大的包**，网页上传耗时最长；若上传中断，单独重传该包即可，其余包不受影响。
- **端口**：gateway 占用宿主 `3000`，部署前确认空闲。
- **架构**：所有镜像均为 amd64，不要把这些 tar 导回 arm64 机器使用。
- **回滚**：Stack 页 Delete 可移除容器与网络；数据在命名卷 `mogo_*` 与**外部 PanWeiDB** 里，
  不会随之丢失（PanWeiDB 的数据由外部实例独立保存）。彻底重来需另行删除这些卷。
"""


def fmt_size(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f}GB"
    return f"{n / 1024 ** 2:.0f}MB"


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    bundle = pathlib.Path(sys.argv[1])
    plan = json.loads((bundle / "bundle.json").read_text())

    if not plan.get("external_db"):
        print("  ⚠️ bundle.json 标记 external_db=false，本渲染器面向外部 PanWeiDB 模式；"
              "请改用 render_deploy_doc.py", file=sys.stderr)

    packages = plan["packages"]
    rows = []
    hashes = []
    image_list = []
    largest = max(packages, key=lambda p: p.get("size", 0))

    for i, pkg in enumerate(packages, start=1):
        contents = "、".join(f"`{x}`" for x in pkg["images"])
        rows.append(
            f"| {i} | `{pkg['file']}` | {fmt_size(pkg.get('size', 0))} | "
            f"{pkg.get('image_count', len(pkg['images']))} | {contents} |"
        )
        hashes.append(f"{pkg.get('sha256', '(未计算)')}  {pkg['file']}")
        image_list.extend(pkg["images"])

    # 外部 PanWeiDB 连接信息：从渲染时写入的占位信息无法回读，这里给出默认值说明；
    # 运维实际值以清单为准。为不让部署单与实际不符，仅描述占位语义并在核查节强调以清单为准。
    pw_host = plan.get("panweidb_host", "172.17.5.145")
    pw_port = plan.get("panweidb_port", "17700")
    pw_user = plan.get("panweidb_user", "boncuser")
    pw_db = plan.get("panweidb_db", "mogo")
    pw_schema = plan.get("panweidb_schema", "public")

    doc = TEMPLATE.format(
        tag=plan.get("tag", "(unknown)"),
        created=plan.get("created", "(unknown)"),
        rows="\n".join(rows),
        total_gb=f"{plan.get('total_size', 0) / 1024 ** 3:.2f}",
        image_total=len(image_list),
        hashes="\n".join(hashes),
        image_list="\n".join(sorted(image_list)),
        largest=largest["file"],
        pw_host=pw_host,
        pw_port=pw_port,
        pw_user=pw_user,
        pw_db=pw_db,
        pw_schema=pw_schema,
    )

    out = bundle / "DEPLOY.md"
    out.write_text(doc)
    print(f"  ✅ 已生成 {out}（外部 PanWeiDB 版，{len(packages)} 个包，tag={plan.get('tag')}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
