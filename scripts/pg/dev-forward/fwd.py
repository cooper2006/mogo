"""纯 stdlib TCP 转发：把双网络容器内的 mogo-mongo:27017 映射到宿主机发布端口。

前置：容器同时接入「默认 bridge」（发布端口）与 `mogo_backend`（internal，连栈内 mongo）。
docker run -d --name pg-mongo-fwd --network bridge --network mogo_backend -p 27018:27018 <image>
docker run -d --name pg-db-fwd --network bridge --network mogo_backend -p 27019:5432 <image> mogo-mongo
"""
import socket, threading, sys

LISTEN = int(sys.argv[1]) if len(sys.argv) > 1 else 27018
UPSTREAM_HOST = sys.argv[2] if len(sys.argv) > 2 else "mogo-mongo"
UPSTREAM_PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 27017

def pipe(a, b):
    try:
        while True:
            d = a.recv(65536)
            if not d:
                break
            b.sendall(d)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_WR)
            except OSError:
                pass

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", LISTEN))
srv.listen(128)
print(f"forward {LISTEN} -> {UPSTREAM_HOST}:{UPSTREAM_PORT}", flush=True)

def handle(c, _):
    try:
        u = socket.create_connection((UPSTREAM_HOST, UPSTREAM_PORT))
    except OSError as e:
        print("upstream connect failed:", e, flush=True)
        c.close()
        return
    threading.Thread(target=pipe, args=(c, u), daemon=True).start()
    threading.Thread(target=pipe, args=(u, c), daemon=True).start()

while True:
    c, _ = srv.accept()
    threading.Thread(target=handle, args=(c, None), daemon=True).start()
