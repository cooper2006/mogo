# 开发期 TCP 转发（R1/R2 实测与切换验证用）

`mogo_backend` 是 `internal=true` 网络：容器既无外网也发布不了端口，
所以宿主机无法直连栈内 MongoDB。本目录用一个纯 stdlib 的 Python 转发容器
（双网络：默认 bridge 发布端口 + `mogo_backend` 连栈内服务）绕开这个限制。

## 用法（需要能访问 docker CLI 的终端）

```bash
# 1) 构建
docker build -t mogo-pg-fwd scripts/pg/dev-forward

# 2) 启动（在 mogo 项目目录下，-p 发布端口，--network 双接入）
docker run -d --rm --name mogo-mongo-fwd \
  --network mogo_default --network mogo_backend \
  -p 27018:27018 mogo-pg-fwd 27018 mogo-mongo 27017

# 3) 宿主机现在可达
#    mongodb://127.0.0.1:27018   （栈内 MongoDB）
```

> 网络名取决于 compose 项目名（默认 `mogo_default` / `mogo_backend`，
> 前缀随 `MOGO_VOLUME_PREFIX` 等变量变化，`docker network ls | grep mogo` 确认）。

## 注意

- 转发容器是纯 stdlib（`socket` + `threading`），不依赖任何外部库。
- 停止：`docker rm -f mogo-mongo-fwd`。
