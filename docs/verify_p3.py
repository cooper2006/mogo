import datetime, sys, importlib.util

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

svc = load("svc", "services/chat-api/app/services/session_sharing/service.py")
snap = load("snap", "services/chat-api/app/services/session_sharing/snapshot.py")

now = datetime.datetime(2026, 11, 1, tzinfo=datetime.timezone.utc)

# --- service.py ---
tok = svc.create_token()
assert len(tok) > 20, tok
assert svc.hash_token(tok) == svc.hash_token(tok)
try:
    svc.hash_token("")
    assert False, "empty token should raise"
except svc.SessionShareError:
    pass

issued = svc.issue_share({"user_id": "u1"}, now=now, expires_in_days=30)
assert issued["fields"]["share_token_hash"] == svc.hash_token(issued["token"])
assert issued["fields"]["share_expires_at"] > now
# 有效
assert svc.is_active({**issued["fields"]}, issued["token"], now) is True
# 错 token
assert svc.is_active({**issued["fields"]}, "wrong", now) is False
# 过期
expired_doc = {**issued["fields"], "share_expires_at": now - datetime.timedelta(days=1)}
assert svc.is_active(expired_doc, issued["token"], now) is False
# 撤销
revoked = svc.revoke_share(now=now)
assert revoked["share_token_hash"] is None
assert svc.is_active({**issued["fields"], **revoked}, issued["token"], now) is False
print("✅ session_sharing/service.py 全部断言通过")

# --- snapshot.py ---
rows = [
    {"role": "user", "content": "hi", "created_at": now, "user_id": "u1", "message_type": "text"},
    {"role": "assistant", "content": "hello", "created_at": now, "message_type": "text"},
    {"role": "system", "content": "sys", "message_type": "text"},
    {"role": "user", "content": "ctx", "message_type": "context_summary"},
]
authors = {"u1": {"display_name": "Alice"}}
msgs = snap.snapshot_messages(rows, authors=authors, owner_user_id="owner")
# 只保留 user/assistant，排除 context_summary/system
assert len(msgs) == 2, msgs
assert msgs[0]["author_name"] == "Alice"
assert msgs[1]["role"] == "assistant"
# snapshot_active
assert snap.snapshot_active({"expires_at": now + datetime.timedelta(hours=1)}, now) is True
assert snap.snapshot_active({"expires_at": now - datetime.timedelta(hours=1)}, now) is False
assert snap.snapshot_active({"expires_at": now + datetime.timedelta(hours=1), "revoked_at": now}, now) is False
print("✅ session_sharing/snapshot.py 全部断言通过")
