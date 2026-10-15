#!/bin/sh
set -eu

secret_file="${ASKAI_RUNTIME_SECRETS_FILE:-/run/askai-secrets/runtime.env}"
if [ -r "$secret_file" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$secret_file"
  set +a
fi

runtime_token="${DSH_RUNTIME_HOST_TOKEN:-}"
if [ "${#runtime_token}" -lt 32 ]; then
  echo "DSH_RUNTIME_HOST_TOKEN is missing or too short." >&2
  exit 1
fi

# 022 US3 (T027): the image declares `USER node`, so the container already
# starts unprivileged and there is nothing left to drop. The root branch is kept
# for callers that force uid 0 (e.g. `docker run -u 0`) and for images built
# before the hardening; there gosu still hands the process to `node`.
#
# Both branches matter for the volume ownership: on a fresh dsh-runtime-data
# volume Docker copies the owner from the image (node), so the root branch is
# only a safety net. It must stay conditional — running `chown` as a non-root
# user would fail and `set -eu` would abort the start-up.
if [ "$(id -u)" = "0" ]; then
  mkdir -p /data/dsh-runtime
  chown -R node:node /data/dsh-runtime
  exec gosu node "$@"
fi

if [ "${DSH_WEB_MODE:-0}" = "1" ]; then
  # 官方 DSH web 模式：额外启动 `dsh --profile web`，把官方 Web GUI 暴露出来。
  # 与 headless host（8101）共用同一个 $HOME/.dsh（持久化在 dsh-runtime-data
  # 卷里），无需预置 profile。
  #
  # 绑定策略：dsh CLI 有意拒绝 `--host 0.0.0.0`（web 模式下会把远程代码执行面
  # 暴露到网络，属官方安全设计，见 dsh-web-app 的 startup.js 校验）。容器内
  # 统一绑定 127.0.0.1，由 mogo-gateway nginx 的反代 location（/dsh-web/，
  # 见 deploy/nginx/nginx.conf）把浏览器请求转发进来，不需要 0.0.0.0，也
  # 不需要 docker 端口映射（那种映射转发到的是容器网桥 IP，而非容器内
  # loopback，对 127.0.0.1 绑定无效，已实测确认走不通）。
  #
  # 浏览器访问的是 gateway 的域名/主机（Host 头保留浏览器视角，nginx 的
  # proxy_set_header Host $http_host），dsh 的 browser-trust fence 会校验该
  # authority 是否为 loopback 或在 trustedHosts 里。localhost/127.0.0.1 是
  # loopback，永远放行，无需额外配置；部署到公网域名或内网主机名后，需要
  # 通过 DSH_WEB_TRUSTED_HOST 追加 authority（逗号分隔），entrypoint 会转成
  # 对应的 --trusted-host 参数传给 dsh。
  web_host="${DSH_WEB_HOST:-127.0.0.1}"
  web_port="${DSH_WEB_PORT:-3080}"
  web_internal_port=$((web_port + 1))
  echo "[askai-dsh-runtime] starting official dsh web profile on ${web_host}:${web_internal_port}"
  # trusted-host 列表按空格转 CLI 参数（sh 没有 IFS 词分割的简单数组写法）
  trusted_args=""
  if [ -n "${DSH_WEB_TRUSTED_HOST:-}" ]; then
    old_ifs="$IFS"; IFS=","; set -- ${DSH_WEB_TRUSTED_HOST}; IFS="$old_ifs"
    for h in "$@"; do
      h="$(printf '%s' "$h" | tr -d ' ')"
      [ -n "$h" ] && trusted_args="$trusted_args --trusted-host $h"
    done
  fi
  # shellcheck disable=SC2086
  node_modules/.bin/dsh --profile web --host "${web_host}" --port "${web_internal_port}" --no-open ${trusted_args} > /tmp/dsh-web.log 2>&1 &
  web_pid=$!
  # 给 web profile 一点时间完成绑定（它会在打印 URL 后常驻运行）；绑定
  # 失败（进程提前退出）则让容器启动失败，不静默吞掉。
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ! kill -0 "${web_pid}" 2>/dev/null; then
      echo "[askai-dsh-runtime] web profile exited during startup." >&2
      cat /tmp/dsh-web.log >&2
      exit 1
    fi
    sleep 1
  done
  # 从 dsh 输出中提取 token（dsh web: http://127.0.0.1:PORT/?token=XXX）
  web_token="$(grep -o 'token=[A-Za-z0-9_-]*' /tmp/dsh-web.log | head -1 | cut -d= -f2)"
  if [ -z "${web_token}" ]; then
    echo "[askai-dsh-runtime] WARNING: could not extract web token from dsh output" >&2
  else
    echo "[askai-dsh-runtime] extracted web token (${#web_token} chars)"
  fi
  # dsh web profile 只绑 127.0.0.1（官方安全设计，拒绝 0.0.0.0），网关 nginx
  # 的 proxy_pass http://dsh-runtime-host:3080 解析到容器网桥 IP，连不上 loopback。
  # 在容器内起一个 HTTP 反向代理：0.0.0.0:${web_port} → 127.0.0.1:${web_internal_port}，
  # 自动追加 token（dsh 的 browser-trust fence 要求 GET / 时必须有 ?token=）。
  echo "[askai-dsh-runtime] starting HTTP reverse proxy :${web_port} -> 127.0.0.1:${web_internal_port}"
  node -e '
    const http = require("http");
    const url = require("url");
    const port = Number(process.argv[1]);
    const targetPort = Number(process.argv[2]);
    const token = process.argv[3] || "";
    const targetHost = "127.0.0.1";

    const proxy = http.createServer((req, res) => {
      // 解析原始 URL，仅在没有 token 且没有 cookie 时追加 token
      // （dsh browser-trust fence 要求 GET / 时必须有 ?token=，已有 cookie 则无需）
      let path = req.url;
      const hasToken = path.includes("token=");
      const hasCookie = req.headers["cookie"] && req.headers["cookie"].indexOf("dsh-auth-") !== -1;
      if (token && !hasToken && !hasCookie && (path === "/" || path === "")) {
        const sep = path.includes("?") ? "&" : "?";
        path = path + sep + "token=" + token;
      }
      const opts = {
        hostname: targetHost,
        port: targetPort,
        path: path,
        method: req.method,
        headers: req.headers
      };
      const upstream = http.request(opts, (upRes) => {
        res.writeHead(upRes.statusCode, upRes.headers);
        upRes.pipe(res);
      });
      upstream.on("error", (e) => { res.writeHead(502); res.end("Bad Gateway"); });
      req.pipe(upstream);
    });
    // WebSocket 转发：dsh Web GUI 通过 /api/remote.mux 的 WebSocket 做远程
    // 控制。没有 upgrade 监听器时，Node 会在升级握手到达时直接销毁 socket，
    // 于是浏览器端报 "WebSocket is closed before the connection is established"。
    // 这里把 upgrade 请求原样转发给内部 dsh（保留原始 path 与请求头，让 dsh
    // 的 browser-trust fence 用 cookie / ?token= 照常鉴权），并双向 pipe 字节流。
    proxy.on("upgrade", (req, clientSocket, head) => {
      // 与普通请求一致的 token 补丁：浏览器对 WebSocket 也带同样的 cookie，
      // 已有 cookie 时无需追加；仅无 token 无 cookie 的裸 GET / 才补 token。
      let wsPath = req.url;
      const hasToken = wsPath.includes("token=");
      const hasCookie = req.headers["cookie"] && req.headers["cookie"].indexOf("dsh-auth-") !== -1;
      if (token && !hasToken && !hasCookie && (wsPath === "/" || wsPath === "")) {
        const sep = wsPath.includes("?") ? "&" : "?";
        wsPath = wsPath + sep + "token=" + token;
      }
      const upstream = http.request({
        hostname: targetHost,
        port: targetPort,
        path: wsPath,
        method: req.method,
        headers: req.headers,
      });
      upstream.on("upgrade", (upRes, upstreamSocket, upstreamHead) => {
        // 把服务端 101 响应头回写给浏览器，再打通双向流。
        clientSocket.write(
          "HTTP/1.1 101 Switching Protocols\r\n" +
          Object.entries(upRes.headers)
            .map(([k, v]) => k + ": " + v)
            .join("\r\n") +
          "\r\n\r\n"
        );
        if (upstreamHead && upstreamHead.length) upstreamSocket.unshift(upstreamHead);
        if (head && head.length) clientSocket.unshift(head);
        upstreamSocket.pipe(clientSocket);
        clientSocket.pipe(upstreamSocket);
        const onError = () => { try { clientSocket.destroy(); } catch {} try { upstreamSocket.destroy(); } catch {} };
        upstreamSocket.on("error", onError);
        clientSocket.on("error", onError);
      });
      upstream.on("response", (upRes) => {
        // 非升级响应（如鉴权 401）：原样回写，避免浏览器端连接悬空。
        const chunks = [];
        upRes.on("data", (c) => chunks.push(c));
        upRes.on("end", () => {
          try {
            clientSocket.write(
              "HTTP/1.1 " + upRes.statusCode + " " + (upRes.statusMessage || "") + "\r\n" +
              Object.entries(upRes.headers).map(([k, v]) => k + ": " + (Array.isArray(v) ? v.join(", ") : v)).join("\r\n") +
              "\r\n\r\n" + Buffer.concat(chunks).toString("binary")
            );
            clientSocket.end();
          } catch {}
        });
      });
      upstream.on("error", () => { try { clientSocket.destroy(); } catch {} });
      // http.request 会按 {method, path, headers} 自动发出请求行与头（已含
      // Upgrade/Connection/Sec-WebSocket-*），无需手动写 socket。升级请求无
      // body，调用 end() 真正发出握手。
      upstream.end();
    });
    proxy.listen(port, "0.0.0.0", () =>
      console.log("[askai-dsh-runtime] HTTP reverse proxy listening on 0.0.0.0:" + port + " -> " + targetHost + ":" + targetPort)
    );
  ' "${web_port}" "${web_internal_port}" "${web_token}" &
  relay_pid=$!
fi

exec "$@"
