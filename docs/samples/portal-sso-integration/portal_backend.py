"""门户后端示例：签 022 服务令牌 → 调 chat-api portal-ticket → 返回一次性票据。

对应 spec 029 / docs/MOGO-Web应用集成方案.md §1.3.2「路径 1」。

流程：
  1. 用户已在本门户登录，取得其用户 id（= MOGO end_users._id，共享主键）。
  2. 用共享密钥 MOGO_PORTAL_TOKEN 签一枚 022 服务令牌（service_id=portal，
     scope=["portal.issue_ticket"]）。
  3. POST {MOGO_BASE_URL}/api/auth/portal-ticket，头带 X-MOVO-Service-Token，
     体带 {"user_id": ...}。
  4. 返回 {"portal_token": ...} 给前端，前端经 history.state 跳 user-web。

⚠️ 门户**不持有**票据签名密钥 PORTAL_SSO_SECRET——票据由 chat-api 签发。
⚠️ 服务令牌签名格式与 app/security/service_token.py 保持一致：
    v1|<b64url(json payload)>|<b64url(HMAC-SHA256(secret, "v1|payload"))>。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid

import requests

# ── 配置（门户后端环境变量）──────────────────────────────────────────────
MOGO_BASE_URL = os.environ.get("MOGO_BASE_URL", "https://mogo.example.com").rstrip("/")
# 与 chat-api 侧一致的 022 服务凭据（chat-api 用 build_issuer_from_env("portal") 读取同名变量）。
PORTAL_SERVICE_TOKEN = os.environ["MOGO_PORTAL_TOKEN"]

# 服务身份：必须与 chat-api EXPECTED_PORTAL_SERVICE_ID 一致。
PORTAL_SERVICE_ID = "portal"
# 权限码：必须与 chat-api gatekeeper 注册的 scope 一致。
PORTAL_ISSUE_TICKET_SCOPE = "portal.issue_ticket"
# 服务身份请求头：沿用 022 代码常量 SERVICE_TOKEN_HEADER（注意是 MOVO，非 MOGO）。
SERVICE_TOKEN_HEADER = "X-MOVO-Service-Token"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def sign_service_token(
    secret: str,
    *,
    service_id: str = PORTAL_SERVICE_ID,
    scope: list[str] | None = None,
    ttl_seconds: int = 60,
) -> str:
    """签一枚 022 服务令牌（形状对齐 app/security/service_token.py 的 issue()）。"""
    ts = int(time.time())
    payload = {
        "service_id": service_id,
        "audience": "chat-api",
        "tenant_id": "",
        "iat": ts,
        "exp": ts + ttl_seconds,
        "jti": str(uuid.uuid4()),
        "scope": scope or [PORTAL_ISSUE_TICKET_SCOPE],
    }
    unsigned = f"v1|{_b64url(json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8'))}"
    signature = hmac.new(secret.encode("utf-8"), unsigned.encode("utf-8"), hashlib.sha256).digest()
    return f"{unsigned}|{_b64url(signature)}"


def issue_portal_ticket(user_id: str, tenant_id: str = "") -> dict:
    """调 chat-api portal-ticket，为指定 MOGO 终端用户签发一次性票据。

    user_id 必须等于 MOGO end_users._id（共享主键）。匹配不到即 401（无 JIT）。
    单租户可传 tenant_id；多租户留空，由换票阶段走选租户挑战流程。
    """
    service_token = sign_service_token(PORTAL_SERVICE_TOKEN)
    body: dict = {"user_id": user_id}
    if tenant_id:
        body["tenant_id"] = tenant_id
    resp = requests.post(
        f"{MOGO_BASE_URL}/api/auth/portal-ticket",
        json=body,
        headers={SERVICE_TOKEN_HEADER: service_token},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"portal-ticket failed: {payload.get('message')}")
    return payload["data"]  # {"token": ..., "expiresAt": ..., "requiresTenantSelection"?: bool}


def build_entry_url(user_web_base: str) -> str:
    """返回 user-web 入口地址（票据**不**进 URL，由前端经 history.state 传递）。"""
    return user_web_base.rstrip("/")


if __name__ == "__main__":
    # 示例：为某门户用户签发票据并打印（实际应把 token 交给前端，见 entry.js）。
    data = issue_portal_ticket(user_id="665f1c0c0b1e2a3f4a5b6c7d")
    print("portal_token =", data["token"])
    print("expiresAt    =", data["expiresAt"])
    if data.get("requiresTenantSelection"):
        print("多租户用户：换票后将进入选租户流程")
