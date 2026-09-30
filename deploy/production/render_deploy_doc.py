#!/usr/bin/env python3
"""根据 bundle.json 生成自包含的生产部署单 DEPLOY.md。

用法：
    render_deploy_doc.py <bundle_dir>

生成的文档面向"拿到这个包去导入镜像的人"，包含实测体积、sha256、导入顺序、
Stack 创建步骤、验证命令与注意事项，不依赖仓库里的其它文件。
"""
import json
import pathlib
import sys

TEMPLATE = """# mogo {tag} 生产部署单（离线）

> 由 `deploy/production/prepare-release.sh` 生成于 {created}。
> 目标主机无外网：镜像只能离线导入，栈用 Portainer 的 Stack 拉起。

## 一、镜像包

按顺序导入（先小后大，便于早发现问题）：

| 顺序 | 文件 | 体积 | 镜像数 | 内容 |
| --- | --- | --- | --- | --- |
{rows}

合计 **{total_gb} GB / {image_total} 个镜像**，全部为 `linux/amd64`。

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

- **Name**：`mogo`（决定网络与容器前缀；卷名前缀由清单里的 `movo_*` 固定，不受它影响）
- **Build method**：选 **Upload**，上传 `docker-compose.portainer.yml`
  （也可用 Web editor 粘贴，但文件含 3.5KB 的 base64 长行，Upload 更稳妥）
- 不要勾选任何 "re-pull image" 类选项（清单已设 `pull_policy: never`）
- 点 **Deploy the stack**

## 四、验证

```bash
curl -i http://<主机>:3000/healthz      # 期望 200 ok
curl -i http://<主机>:3000/setup        # 期望 302 -> /admin/setup
curl -I http://<主机>:3000/             # 期望 200（用户前端）
curl -I http://<主机>:3000/admin/       # 期望 200（管理前端）
```

Portainer → Containers 里应看到 12 个 `mogo-*` 容器：

- `mogo-bootstrap-1` 显示 **Exited (0)** —— 这是**正常的**，它只负责生成 `runtime.env` 密钥后退出
- mongo / redis / weaviate / chat-api / admin-api / document-api / dsh-runtime-host /
  user-web / admin-web / gateway 为 healthy
- `document-worker` 无健康检查，running 即可

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
- **`{largest}` 是最大的包**，网页上传耗时最长；若上传中断，单独重传该包即可，其余包不受影响。
- **端口**：gateway 占用宿主 `3000`，部署前确认空闲。
- **架构**：所有镜像均为 amd64，不要把这些 tar 导回 arm64 机器使用。
- **回滚**：Stack 页 Delete 可移除容器与网络；数据在命名卷 `movo_*` 里，不会随之丢失。
  彻底重来需另行删除这些卷。
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

    doc = TEMPLATE.format(
        tag=plan.get("tag", "(unknown)"),
        created=plan.get("created", "(unknown)"),
        rows="\n".join(rows),
        total_gb=f"{plan.get('total_size', 0) / 1024 ** 3:.2f}",
        image_total=len(image_list),
        hashes="\n".join(hashes),
        image_list="\n".join(sorted(image_list)),
        largest=largest["file"],
    )

    out = bundle / "DEPLOY.md"
    out.write_text(doc)
    print(f"  ✅ 已生成 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
