# Keepalived：宿主机 VIP 入口

跨 AZ 部署（`deploy/docker-compose.prod.yml`）里，应用副本分布在两个可用区，
但**入口**需要一个稳定的 VIP。本文给出自建方案；用云厂商 LB 的话直接跳过——
那通常是更省事的选择（见 `docs/runbooks/disaster-recovery.md` §8.3）。

## 为什么 VIP 放在宿主机而不是容器里

VIP（`ip addr add`）需要 `NET_ADMIN` + `host` 网络。把 Keepalived 塞进容器意味着
给容器改宿主机网络栈的权限，风险和收益不成比例：容器重启/重建期间 VIP 可能被
带走，反而多一个故障源。宿主机跑 Keepalived 是这一层最稳的做法。

## 拓扑

| 机器 | VIP 角色 | 说明 |
|---|---|---|
| `az-a-node-1` | MASTER（priority 150） | 正常情况下持有 VIP |
| `az-b-node-1` | BACKUP（priority 100） | MASTER 挂掉后接管 |

两台都跑 gateway 副本；VIP 指向**当前持有者**，后端仍是本机 gateway 端口。

> 容量提醒：只有一台机器持有 VIP 时，全部流量会打到这一台的 gateway。
> gateway 是无状态的反向代理，只要单机容量够就不是问题；不够就把 VIP 换成
> 云 LB，或在 VIP 后面再挂一层 LVS/nginx。

## `/etc/keepalived/keepalived.conf`（两台机器，只有 state/priority 不同）

```conf
global_defs {
    router_id mogo_az_a          # 另一台改成 mogo_az_b
    script_user root
    enable_script_security
}

vrrp_script check_gateway {
    script "/opt/mogo/deploy/keepalived/check_gateway.sh"
    interval 3
    timeout  2
    fall     3
    rise     2
    # 冷启动宽限：容器还没起来时别急着把 VIP 让出去
    weight   -20
}

vrrp_instance VI_MOGO {
    state MASTER                 # 另一台改成 BACKUP
    interface eth0               # 换成实际内网网卡（ip addr 查看）
    virtual_router_id 51         # 同一 L2 内唯一
    priority 150                 # 另一台改成 100
    advert_int 1
    authentication {
        auth_type PASS
        auth_pass <强口令，勿提交到仓库>
    }
    virtual_ipaddress {
        10.0.1.100/24            # 换成你的 VIP
    }
    track_script {
        check_gateway
    }
    # 网络抖动时不要抢占，避免 VIP 来回漂
    nopreempt
}
```

## 启用

```bash
sudo cp deploy/keepalived/check_gateway.sh /opt/mogo/deploy/keepalived/
sudo chmod 0755 /opt/mogo/deploy/keepalived/check_gateway.sh
sudo keepalived -t -f /etc/keepalived/keepalived.conf   # 先做配置检查
sudo systemctl enable --now keepalived
```

## 验证

```bash
# VIP 在谁身上
ip addr show eth0 | grep 10.0.1.100

# 健康检查脚本本身的行为（0=健康）
GATEWAY_HEALTH_URL=http://127.0.0.1:8080 bash deploy/keepalived/check_gateway.sh; echo "exit=$?"

# 演练：在 MASTER 上停 gateway，3×3s 后 VIP 应漂到 BACKUP
docker compose stop gateway
watch -n1 'ip addr show eth0 | grep 10.0.1.100 || echo "VIP 已漂走"'
docker compose start gateway
```

`check_gateway.sh` 用 `fall 3 / interval 3` 意味着最坏情况约 9 秒才判定故障，
这是**故意**的：VIP 漂移会切断所有在途连接，宁可多等几秒也不要误判。

## 与容器重启的关系

Keepalived 判故障后只是交出 VIP，**不会**重启 gateway。gateway 的自动恢复由
`deploy/docker-compose.prod.yml` 的 `restart_policy: any` 负责，两者分工不要混：
VIP 负责「流量去哪」，restart policy 负责「进程活着」。
