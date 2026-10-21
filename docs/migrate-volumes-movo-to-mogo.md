# 数据卷迁移：movo_* → mogo_*

品牌迁移收尾后，`MOGO_VOLUME_PREFIX` 的默认值已从 `movo` 改为 `mogo`（`docker-compose.yml`
`volumes:` 段统一为 `name: ${MOGO_VOLUME_PREFIX:-mogo}_<suffix>`），compose 生成的卷名随之从
`movo_mongo-data` 等变为 `mogo_mongo-data` 等。**存量部署升级前必须先迁移数据卷**，否则新容器
会挂到空的新卷上，表现为“数据全丢了”（实际旧卷完好，只是没挂上）。

> compose 声明 11 个具名卷（见 `docker-compose.yml` `volumes:` 段）：
> deployment-secrets / mongo-data / redis-data / weaviate-data /
> dsh-runtime-data(-1/-2/-3) / askai-storage / knowledge-storage / admin-static。
> `dsh-runtime-data-1/-2/-3` 仅在被 dsh-runtime-host 扩到多副本时才会真正创建，
> 单副本部署主机上不存在，迁移脚本会自动跳过。
>
> `MOVO_VOLUME_PREFIX` 已**不再被读取**（不再是回退，写了也会被忽略），必须改名或删掉。

## 迁移前实测基线（2026-10-21，本机 mogo 项目，OrbStack）

| 旧卷 | 项数 | 体积 | 挂载方（容器内路径） |
| --- | --- | --- | --- |
| `movo_deployment-secrets` | 1 | 4.0K | 所有后端（`/run/askai-secrets`） |
| `movo_mongo-data` | 495 | 443.5M | mongo（`/data/db`） |
| `movo_redis-data` | 2 | 1.9M | redis（`/data`） |
| `movo_weaviate-data` | 8 | 388.0K | weaviate（`/var/lib/weaviate`） |
| `movo_dsh-runtime-data` | 162 | 4.6M | dsh-runtime-host（`/data/dsh-runtime`） |
| `movo_askai-storage` | 2 | 172.0K | chat-api（`/app/storage`） |
| `movo_knowledge-storage` | 1 | 5.1M | chat-api / admin-api / document-*（`/data/knowledge-documents`） |
| `movo_admin-static` | 0 | 0 | admin-api（`/data/admin-static`） |

主机上还观察到一个**空**的 `mogo_deployment-secrets`（早前误建，0 项）。克隆流程会直接复用它，
但升级后应确认其内容非空，否则内部令牌会被重新生成。（本次迁移已复用它，克隆后 1 个条目。）

## 本次迁移执行记录（2026-10-21，本机 mogo 项目）

品牌迁移收尾提交（`48b1f31` … `41b272c`）完成后，本机按下面的方案 A 实际执行了迁移并滚动重启，
过程与结果记录如下，可作为其他存量部署的参照。

1. `./mogo build` 重建全部 7 个镜像 → tag `v0.2.4-19-g41b272c`（admin-api / admin-web / chat-api /
   document-parser / dsh-runtime-host / gateway / user-web）。
2. `docker compose -f docker-compose.yml -f docker-compose.build.yml down`（停机，卷保留）。
3. 8 个 `movo_<suffix>` 卷逐卷 `cp -a` 克隆为 `mogo_<suffix>`（脚本见下方方案 A），
   校验项数/字节数/属主完全一致：

   | 卷 | 项数 | 字节数 | 属主 |
   | --- | --- | --- | --- |
   | `mogo_deployment-secrets` | 1 | 1698 | 0:0 |
   | `mogo_mongo-data` | 495 | 465545326 | 999:0, 999:999 |
   | `mogo_redis-data` | 2 | 2000584 | 999:1000 |
   | `mogo_weaviate-data` | 8 | 354769 | 0:0 |
   | `mogo_dsh-runtime-data` | 162 | 3952418 | 1000:1000 |
   | `mogo_askai-storage` | 2 | 114962 | 10001:10001 |
   | `mogo_knowledge-storage` | 1 | 5247888 | 10001:10001 |
   | `mogo_admin-static` | 0 | 0 | — |

4. **密钥键归一**（本次新增的必要步骤）：旧 `runtime.env` 里是 `MOVO_DOC_PROCESSING_*` 键，新代码
   只认 `MOGO_DOC_PROCESSING_*`，而 bootstrap 只在文件缺失/为空时才重写 —— 直接克隆会让
   document-parser 读到空令牌。因此按原值补齐 `MOGO_` 键并删除 `MOVO_` 行（**值不变，不轮换令牌**，
   已用 sha256 比对确认与旧卷逐字节一致）。

   ```bash
   docker run --rm -v mogo_deployment-secrets:/v alpine:3.21 sh -c '
     f=/v/runtime.env
     for k in SERVICE_TOKEN CALLBACK_TOKEN ADMIN_JWT_SECRET; do
       v=$(sed -n "s/^MOVO_DOC_PROCESSING_${k}=//p" "$f" | head -n1)
       [ -n "$v" ] && ! grep -q "^MOGO_DOC_PROCESSING_${k}=" "$f" \
         && echo "MOGO_DOC_PROCESSING_${k}=$v" >> "$f"
     done
     sed -i "/^MOVO_DOC_PROCESSING_/d" "$f"; chmod 644 "$f"'
   ```

5. `MOGO_VERSION=v0.2.4-19-g41b272c ./mogo up -d` → 11 个容器全部 Up，除无 healthcheck 的
   `mogo-document-worker-1` 外全部 healthy。

**迁移后验证（全部通过）**：

- `mongo` / `mogo_dev` 两库**每个集合的文档数**与迁移前快照逐行比对：**0 处差异**。
- document-parser 服务令牌链路实测：`Authorization: Bearer <MOGO_DOC_PROCESSING_SERVICE_TOKEN>`
    → `422`（鉴权通过，仅 body 校验失败）；错误令牌 → `403`；无令牌 → `401`。
- `/api/health` 返回 `{"service":"mogo-document-processing-service","backend":"panweidb",…,"reachable":true}`，
   `/api/ready` 200；weaviate 原有 class `AskAIKnowledgeChunks` 仍在。
- 网关 `http://localhost:3000/`、`/health`、`/admin/` 均 200；前端产物内 `movo` 出现次数为 0，
  引用的是 `mogo-logo.png`（`/mogo-logo.png` 200，`/movo-logo.png` 落到 SPA 回退返回 HTML）。

**回滚路径**：迁移刚完成时旧卷 `movo_*` 8 个与旧镜像 tag（`60eff81`）都保留未动，可随时回滚。
验证稳定后已按用户要求清理（见下）：回滚能力随之消失 —— 如需回到迁移前状态，只能用迁移前的
代码重新构建镜像，并把现有 `mogo_*` 卷内容按同样的 `cp -a` 方式反向克隆。

**清理记录（2026-10-21，用户确认后执行）**：

```bash
# 旧数据卷（删除前逐一确认 0 容器引用、且 mogo_<suffix> 已就绪）
docker volume rm movo_admin-static movo_askai-storage movo_deployment-secrets \
                 movo_dsh-runtime-data movo_knowledge-storage movo_mongo-data \
                 movo_redis-data movo_weaviate-data
# 旧镜像（迁移前运行中的 tag）
docker rmi admin-api:60eff81 admin-web:60eff81 chat-api:60eff81 document-parser:60eff81 \
           dsh-runtime-host:60eff81 gateway:60eff81 user-web:60eff81
```

效果：镜像占用 28.78GB → 17.47GB，本地卷 1.269GB → 792.3MB；11 个容器全程未受影响
（删除后复检仍全部 healthy）。

## 方案 A：克隆迁移（推荐，旧卷保留作回滚）

```bash
# 0) 停机（保留卷）：compose 文件名需与本机一致
docker compose -f docker-compose.yml -f docker-compose.build.yml down

# 1) 逐卷克隆（示例：mongo-data）
docker volume create mogo_mongo-data                     # 已存在则为幂等空操作
docker run --rm -v movo_mongo-data:/from:ro -v mogo_mongo-data:/to alpine:3.21 \
  sh -c 'cp -a /from/. /to/ && sync'                     # cp -a 保留属主/权限，不要吞错误

# 2) 起来验证
MOGO_VERSION=<本地镜像 tag> ./mogo up -d
docker compose ps                                        # 全 healthy 后逐项验证
```

8 个实际存在的卷可脚本化（幂等，可重复执行）：

```bash
for suffix in deployment-secrets mongo-data redis-data weaviate-data \
              dsh-runtime-data askai-storage knowledge-storage admin-static; do
  old="movo_${suffix}"; new="mogo_${suffix}"
  docker volume inspect "$old" >/dev/null 2>&1 || { echo "skip $old (不存在)"; continue; }
  docker volume create "$new" >/dev/null
  docker run --rm -v "$old":/from:ro -v "$new":/to alpine:3.21 \
    sh -c 'cp -a /from/. /to/ && sync' || { echo "FAILED $old"; exit 1; }
  echo "migrated $old -> $new"
done
```

**不要**对 `mongo-data` / `redis-data` / `weaviate-data` 执行 `chown -R 10001:10001`：这些官方镜像
以自己的内置 UID 运行（mongodb 999 / redis 999 / weaviate 1000），`cp -a` 已保留原属主，强行 chown
反而会让它们无法读写自己的数据目录。只有确实需要时才按需 chown（先 `find -printf '%u:%g'` 比对）。

### 迁移后校验（必须做）

```bash
for suffix in deployment-secrets mongo-data redis-data weaviate-data \
              dsh-runtime-data askai-storage knowledge-storage admin-static; do
  old="movo_${suffix}"; new="mogo_${suffix}"
  docker volume inspect "$old" >/dev/null 2>&1 || continue
  o=$(docker run --rm -v "$old":/v:ro alpine:3.21 sh -c 'ls -A /v | wc -l')
  n=$(docker run --rm -v "$new":/v:ro alpine:3.21 sh -c 'ls -A /v | wc -l')
  ou=$(docker run --rm -v "$old":/v:ro alpine:3.21 sh -c 'find /v -printf "%u:%g\n" | sort -u | tr "\n" " "')
  nu=$(docker run --rm -v "$new":/v:ro alpine:3.21 sh -c 'find /v -printf "%u:%g\n" | sort -u | tr "\n" " "')
  [ "$o" = "$n" ] && [ "$ou" = "$nu" ] && echo "OK   $new (项数=$n 属主=$nu)" \
                                   || echo "DIFF $old/$new (项数 $o vs $n / 属主 $ou vs $nu)"
done
```

项数或属主不一致时**不要**起容器：旧卷没被改动，重新克隆即可。

### 起容器时的版本坑

`./mogo up -d`（不带 `--build`）会用 `./mogo` 从 `git describe --tags --always` 推出的版本号去找
本地镜像（如 `chat-api:<当前 HEAD>`），并调用 `mogo_require_local_images` 校验，找不到就中止。
复用现有本地镜像时必须显式钉住 tag：

```bash
MOGO_VERSION=v0.2.4-19-g41b272c ./mogo up -d   # 本次迁移实际使用的、由 ./mogo build 产出的 tag
```

要连镜像一起更新（含前端 logo / DOM id 等品牌资源）则用 `./mogo up --build`。本次迁移走的是
「先 `./mogo build` 再 `MOGO_VERSION=<新 tag> ./mogo up -d`」这条路径。

## 方案 B：不改卷名（零迁移，显式钉住旧前缀）

不想动卷的话，在 `.env` 里显式设置即可，行为与旧版一致：

```env
MOGO_VOLUME_PREFIX=movo
```

这是**显式取值**，不是回退链：`MOVO_VOLUME_PREFIX` 不会再被读取。

## 方案 C：`docker volume clone`（Docker ≥ 23.0，更快）

```bash
docker volume clone movo_mongo-data mogo_mongo-data
```

同样必须停机执行；克隆完成后按上面的校验清单比对项数与属主。

## 注意事项

- **deployment-secrets** 卷里是 bootstrap 生成的内部令牌文件。克隆旧内容（推荐）会让现有令牌继续
  有效；删卷重生成会轮换全部内部令牌，必须让所有服务一起重启。
- **mongo-data / panweidb**：务必停机（容器释放文件锁）后再克隆。本机另有独立容器 `panweidb`
  不在本 compose 内，迁移卷不影响它。
- OrbStack 与 Docker Desktop 对 VM 内卷的复制均按上面的命令执行即可。
- 迁移期间 `.env` 里所有 `MOVO_*` 键应顺手改名为 `MOGO_*`（`MOVO_PORT`→`MOGO_PORT`、
  `MOVO_VERSION`→`MOGO_VERSION` 等）；旧键升级后会被**静默忽略**并落回默认值。
- 旧卷 `movo_*` 在验证稳定后再清理（`docker volume rm` 逐个确认，删除前确认 0 容器引用）；
  本仓库约定不主动删除数据卷，必须由使用者在确认迁移无误后显式要求。本机已于 2026-10-21 清理完毕。
