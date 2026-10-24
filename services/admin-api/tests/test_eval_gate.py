"""032-eval-gate: unit tests for the publish-time eval gate.

Coverage (see specs/032-eval-gate/tasks.md):
- T007 policy resolution (skill -> tenant -> defaults), save/coerce
- T008/T009/T010 test-set CRUD + validation + limits
- T011 judges (refusal / citation / task), aggregate denominators
- T012 executor NDJSON assembly
- T014 gate fail-closed (no test set, insufficient samples, LLM timeout)
- T015 threshold boundary (equality passes)
- T016 audit gate_events + skill_eval_runs persistence
- T017 publish hook placement
- T018 route mapping (publish -> 409, dry-run non-blocking)
- T020 policy cannot be globally disabled
"""

from __future__ import annotations

import asyncio
import datetime

import pytest

from app.services import eval_gate as eval_gate_module
from app.services.eval_gate.executor import _assemble_ndjson
from app.services.eval_gate.gate import EvalGateBlocked, run_gate
from app.services.eval_gate.judges import (
    aggregate,
    citation_supported,
    is_refusal,
    judge_case,
    task_successful,
)
from app.services.eval_gate.models import DEFAULT_MIN_CASES, Metrics
from app.services.eval_gate.policies import get_policy, save_policy
from app.services.eval_gate.test_sets import (
    EvalCaseLimitError,
    EvalCaseValidationError,
    create_case,
    delete_case,
    list_cases,
    update_case,
)
from app.services import skill_lifecycle as skill_lifecycle_module
from app.services.skill_lifecycle import OrganizationSkillLifecycle


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------
def _matches(row, query):
    for key, value in query.items():
        if isinstance(value, dict) and "$in" in value:
            if row.get(key) not in value["$in"]:
                return False
        elif row.get(key) != value:
            return False
    return True


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction):
        self.rows.sort(key=lambda row: row.get(key), reverse=direction < 0)
        return self

    def limit(self, value):
        self.rows = self.rows[:value]
        return self

    async def to_list(self, length):
        return [dict(row) for row in self.rows[:length]]


class _Result:
    """Attribute-accessible result object mimicking pymongo UpdateResult etc."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class Collection:
    def __init__(self, rows=None):
        self.rows = {row["_id"]: row for row in (rows or [])}

    async def find_one(self, query, projection=None):
        return next((dict(row) for row in self.rows.values() if _matches(row, query)), None)

    def find(self, query):
        return Cursor([dict(row) for row in self.rows.values() if _matches(row, query)])

    async def count_documents(self, query):
        return sum(1 for row in self.rows.values() if _matches(row, query))

    async def insert_one(self, doc):
        doc = dict(doc)
        # MongoDB assigns ``_id`` itself when the document omits it (audit
        # events key on ``event_id`` instead), so the fake must too.
        doc.setdefault("_id", f"auto-{len(self.rows) + 1}")
        self.rows[doc["_id"]] = doc
        return doc

    async def replace_one(self, query, doc, upsert=False):
        for row in self.rows.values():
            if _matches(row, query):
                doc = dict(doc)
                self.rows[row["_id"]] = doc
                return _Result(modified_count=1, upserted_id=None)
        if upsert:
            doc = dict(doc)
            self.rows[doc["_id"]] = doc
            return _Result(modified_count=0, upserted_id=doc["_id"])
        return _Result(modified_count=0, upserted_id=None)

    async def update_one(self, query, update, upsert=False):
        for _id, row in list(self.rows.items()):
            if _matches(row, query):
                self.rows[_id] = {**row, **update.get("$set", {})}
                return _Result(matched_count=1)
        return _Result(matched_count=0)

    async def delete_one(self, query):
        for _id, row in list(self.rows.items()):
            if _matches(row, query):
                del self.rows[_id]
                return _Result(deleted_count=1)
        return _Result(deleted_count=0)

    def create_index(self, *args, **kwargs):
        return "fake_index"


def _case(_id, input="问题A", expectations=None, expected_refs=None, expect_refusal=False, agent_tag="default"):
    return {
        "_id": _id,
        "tenant_id": "t1",
        "skill_id": "s1",
        "input": input,
        "expectations": expectations or ["结论X"],
        "expected_refs": expected_refs or [],
        "expect_refusal": expect_refusal,
        "agent_tag": agent_tag,
        "created_at": datetime.datetime.now(datetime.timezone.utc),
        "updated_at": datetime.datetime.now(datetime.timezone.utc),
    }


def _db(cases=None, policies=None, runs=None, skills=None, releases=None):
    """Fake DB that supports both `db["collection"]` and `db.collection`.

    The eval-gate module uses dict-style indexing while skill_lifecycle uses
    attribute access; a single dual-interface fake keeps tests uniform.
    """

    class DB:
        def __init__(self):
            self._c = {}

        def __getitem__(self, key):
            return self._c.setdefault(key, Collection())

        def __setitem__(self, key, value):
            self._c[key] = value

        def __getattr__(self, name):
            return self._c.setdefault(name, Collection())

        @property
        def collections(self):
            return self._c

    db = DB()
    if cases:
        db._c["skill_eval_cases"] = Collection(list(cases))
    if policies:
        db._c["skill_eval_policies"] = Collection(list(policies))
    if runs:
        db._c["skill_eval_runs"] = Collection(list(runs))
    db._c["gate_events"] = Collection()
    db._c["skills"] = Collection([{"_id": "s1", "tenant_id": "t1", "name": "S1"}])
    db._c["organization_skill_releases"] = Collection(list(releases or []))
    return db


def _patch_db(monkeypatch, db):
    """Patch ``get_db`` in each module that bound it at import time."""
    for mod in (
        eval_gate_module.policies,
        eval_gate_module.test_sets,
        eval_gate_module.gate,
        skill_lifecycle_module,
    ):
        monkeypatch.setattr(mod, "get_db", lambda _db=db: _db)


SKILL_DRAFT = {
    "name": "S1",
    "description": "desc",
    "scenario": "scenario",
    "type": "tool",
    "config": {"foo": "bar"},
}


# ---------------------------------------------------------------------------
# judges (T011)
# ---------------------------------------------------------------------------
def test_judge_refusal_correct():
    case = _case("c1", expect_refusal=True, expectations=[], expected_refs=[])
    r = judge_case(case, "抱歉，我无法回答这个问题")
    assert r.refusal_accuracy is True


def test_judge_refusal_wrong_answer():
    case = _case("c1", expect_refusal=True, expectations=[], expected_refs=[])
    r = judge_case(case, "这是一份详细资料，内容如下……")
    assert r.refusal_accuracy is False


def test_judge_citation_and_task():
    case = _case("c2", expected_refs=["doc-A"], expectations=["引用来源A", "结论X"])
    r = judge_case(case, "根据文档doc-A，结论X正确")
    assert r.citation_support is True
    assert r.task_success is False  # 引用来源A 未出现 -> 期望关键词未全覆盖


def test_judge_citation_missing_ref():
    case = _case("c2", expected_refs=["doc-A"], expectations=["结论X"])
    r = judge_case(case, "结论X")
    assert r.citation_support is False


def test_judge_empty_expected_refs_excluded_from_citation_denominator():
    # 空期望引用不参与支撑率分母 (boundary 已定决策 #11)
    case = _case("c3", expected_refs=[], expectations=["结论X"])
    r = judge_case(case, "结论X")
    assert r.citation_support is None


def test_aggregate_denominator_rules():
    # refusal case 只计入拒答正确率分母
    ref_ok = judge_case(_case("c1", expect_refusal=True, expectations=[], expected_refs=[]), "抱歉，无法回答")
    ref_bad = judge_case(_case("c2", expect_refusal=True, expectations=[], expected_refs=[]), "回答内容……")
    task_ok = judge_case(_case("c3", expected_refs=["doc-A"], expectations=["结论X"]), "根据文档doc-A，结论X正确")
    task_no_ref = judge_case(_case("c4", expected_refs=[], expectations=["结论X"]), "结论X")
    task_bad = judge_case(_case("c5", expected_refs=[], expectations=["结论X"]), "胡说")
    agg = aggregate([ref_ok, ref_bad, task_ok, task_no_ref, task_bad])
    assert agg["refusal_accuracy"] == 0.5            # 1/2
    assert agg["citation_support"] == 1.0            # 1/1 (task_no_ref 不参与)
    assert agg["task_success"] == pytest.approx(2 / 3)  # task_ok + task_no_ref 全期望命中；refusal 不参与分母


def test_is_refusal_and_citation_helpers():
    assert is_refusal("抱歉，我无法回答") is True
    assert is_refusal("I cannot help with that.") is True
    assert is_refusal("正常回答") is False
    assert citation_supported("提到 doc-A", ["doc-A"]) is True
    assert citation_supported("无引用", ["doc-A"]) is False
    assert citation_supported("无引用", []) is None
    assert task_successful("包含结论X", ["结论X"]) is True
    assert task_successful("", ["结论X"]) is False
    assert task_successful("", []) is None


# ---------------------------------------------------------------------------
# metrics boundary (T015)
# ---------------------------------------------------------------------------
def test_metrics_below_only_strictly_below():
    m = Metrics(citation_support=0.6, refusal_accuracy=0.5, task_success=0.7)
    thr = Metrics(citation_support=0.6, refusal_accuracy=0.6, task_success=0.7)
    assert m.below(thr) == ["refusal_accuracy"]  # 等于阈值判通过


# ---------------------------------------------------------------------------
# policy (T007 / T020)
# ---------------------------------------------------------------------------
def test_policy_defaults_and_resolution(monkeypatch):
    _patch_db(monkeypatch, _db())
    policy = asyncio.run(get_policy(tenant_id="t1", skill_id="s1"))
    assert policy["min_cases"] == DEFAULT_MIN_CASES
    assert "enabled" not in policy  # get_policy 返回原始 snake_case 配置；enabled 仅在 view() 中出现


def test_policy_tenant_fallback(monkeypatch):
    db = _db()
    # skill-level policy exists -> takes precedence
    db["skill_eval_policies"] = Collection([
        {"_id": "p-skill", "tenant_id": "t1", "skill_id": "s1", "min_cases": 3,
         "min_citation_support": 0.5, "min_refusal_accuracy": 0.5, "min_task_success": 0.5,
         "timeout_seconds": 120, "max_cases": 10, "created_at": None, "updated_at": None},
    ])
    _patch_db(monkeypatch, db)
    policy = asyncio.run(get_policy(tenant_id="t1", skill_id="s1"))
    assert policy["min_cases"] == 3


def test_save_policy_coerce_and_no_disable(monkeypatch):
    db = _db()
    _patch_db(monkeypatch, db)
    saved = asyncio.run(save_policy(tenant_id="t1", skill_id="s1", payload={
        "min_cases": "7", "max_cases": "25", "timeout_seconds": "120",
        "min_citation_support": "0.7", "min_refusal_accuracy": 0.8, "min_task_success": 0.9,
        "enabled": False,  # 门禁不可整体关闭 -> 应被忽略
    }))
    assert saved["min_cases"] == 7
    assert "enabled" not in saved  # 决策 #2: 门禁不可关闭，save 不接受 enabled


# ---------------------------------------------------------------------------
# test sets (T008 / T009 / T010)
# ---------------------------------------------------------------------------
def test_create_case_and_list(monkeypatch):
    db = _db()
    _patch_db(monkeypatch, db)
    created = asyncio.run(create_case(tenant_id="t1", skill_id="s1", payload={
        "input": "问题A", "expectations": ["结论X"], "expected_refs": ["doc-A"], "expect_refusal": False,
    }))
    rows = asyncio.run(list_cases(tenant_id="t1", skill_id="s1"))
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"]
    assert rows[0]["expectedRefs"] == ["doc-A"]


def test_create_case_validation(monkeypatch):
    _patch_db(monkeypatch, _db())
    with pytest.raises(EvalCaseValidationError):
        asyncio.run(create_case(tenant_id="t1", skill_id="s1", payload={"input": "", "expectations": ["X"], "expect_refusal": False}))
    with pytest.raises(EvalCaseValidationError):
        # 非拒答用例必须提供期望
        asyncio.run(create_case(tenant_id="t1", skill_id="s1", payload={"input": "Q", "expectations": [], "expect_refusal": False}))


def test_case_limit(monkeypatch):
    rows = [_case(f"c{i}") for i in range(3)]
    _patch_db(monkeypatch, _db(cases=rows))
    with pytest.raises(EvalCaseLimitError) as ei:
        asyncio.run(create_case(tenant_id="t1", skill_id="s1", payload={
            "input": "Q", "expectations": ["X"], "expect_refusal": False}, max_cases=3))
    assert ei.value.limit == 3


def test_update_and_delete_case(monkeypatch):
    row = _case("c1")
    db = _db(cases=[row])
    _patch_db(monkeypatch, db)
    updated = asyncio.run(update_case(tenant_id="t1", skill_id="s1", case_id="c1", payload={
        "input": "新问题", "expectations": ["新期望"], "expect_refusal": False}))
    assert updated["input"] == "新问题"
    assert updated["id"] == "c1"
    deleted = asyncio.run(delete_case(tenant_id="t1", skill_id="s1", case_id="c1"))
    assert deleted["deleted"] is True
    assert asyncio.run(list_cases(tenant_id="t1", skill_id="s1")) == []


# ---------------------------------------------------------------------------
# executor NDJSON assembly (T012)
# ---------------------------------------------------------------------------
def test_assemble_ndjson_mixed_events():
    # Mirrors chat-api model gateway contract (text-delta / finish / error).
    raw = "\n".join([
        '{"type":"text-delta","text":"结论X"}',
        '{"type":"text-delta","text":"完成"}',
        '{"type":"finish","reason":{"kind":"stop"}}',
        "",
    ])
    assert _assemble_ndjson(raw) == "结论X完成"


def test_assemble_ndjson_error_only_raises():
    raw = '{"type":"error","error":{"code":"boom","message":"model boom","retryable":true}}\n'
    with pytest.raises(RuntimeError):
        _assemble_ndjson(raw)


def test_assemble_ndjson_empty_raises():
    with pytest.raises(RuntimeError):
        _assemble_ndjson("")


# ---------------------------------------------------------------------------
# gate (T014 / T016)
# ---------------------------------------------------------------------------
def _stub_llm(outputs):
    """Build a stub llm_call that returns canned outputs in order."""
    state = {"i": 0}

    async def _llm(prompt, **kwargs):
        idx = state["i"]
        state["i"] += 1
        return outputs[min(idx, len(outputs) - 1)]

    return _llm


def test_gate_blocks_when_no_test_set(monkeypatch):
    db = _db(cases=[])
    _patch_db(monkeypatch, db)
    with pytest.raises(EvalGateBlocked) as ei:
        asyncio.run(run_gate(tenant_id="t1", skill_id="s1", version="1.0.0", skill_draft=SKILL_DRAFT, llm_call=_stub_llm(["ok"])))
    assert ei.value.status_code == 409
    assert "尚未配置" in ei.value.reason
    # 审计记录应落库 (fail-closed)
    assert len(db["gate_events"].rows) >= 1


def test_gate_blocks_when_insufficient_samples(monkeypatch):
    rows = [_case(f"c{i}") for i in range(DEFAULT_MIN_CASES - 1)]
    db = _db(cases=rows)
    _patch_db(monkeypatch, db)
    with pytest.raises(EvalGateBlocked) as ei:
        asyncio.run(run_gate(tenant_id="t1", skill_id="s1", version="1.0.0", skill_draft=SKILL_DRAFT, llm_call=_stub_llm(["ok"])))
    assert "样本不足" in ei.value.reason


def test_gate_blocks_when_llm_timeout(monkeypatch):
    rows = [_case(f"c{i}", expectations=[], expected_refs=[]) for i in range(DEFAULT_MIN_CASES)]
    db = _db(cases=rows)

    async def _timeout(prompt, **kwargs):
        raise TimeoutError("llm timeout")

    _patch_db(monkeypatch, db)
    with pytest.raises(EvalGateBlocked) as ei:
        asyncio.run(run_gate(tenant_id="t1", skill_id="s1", version="1.0.0", skill_draft=SKILL_DRAFT, llm_call=_timeout))
    assert ei.value.status_code in (409, 502)
    # 失败的 run 也应记录
    assert len(db["skill_eval_runs"].rows) >= 1


def test_gate_blocks_when_metrics_below_threshold(monkeypatch):
    # 5 个用例，全部期望结论X，期望引用 doc-A；LLM 输出不含 doc-A -> citation_support=0
    rows = [
        _case(f"c{i}", expected_refs=["doc-A"], expectations=["结论X"])
        for i in range(DEFAULT_MIN_CASES)
    ]
    db = _db(cases=rows)
    _patch_db(monkeypatch, db)
    with pytest.raises(EvalGateBlocked) as ei:
        asyncio.run(run_gate(tenant_id="t1", skill_id="s1", version="1.0.0", skill_draft=SKILL_DRAFT, llm_call=_stub_llm(["结论X"])))
    assert ei.value.status_code == 409
    assert ei.value.metrics["citation_support"] == 0.0
    # 审计事件类型应为 blocked
    events = list(db["gate_events"].rows.values())
    assert any(e.get("event_type") == "eval_gate.blocked" for e in events)


def test_gate_passes_when_above_threshold_and_writes_audit(monkeypatch):
    rows = [
        _case(f"c{i}", expected_refs=["doc-A"], expectations=["结论X"])
        for i in range(DEFAULT_MIN_CASES)
    ]
    db = _db(cases=rows)
    _patch_db(monkeypatch, db)
    report = asyncio.run(run_gate(tenant_id="t1", skill_id="s1", version="1.0.0", skill_draft=SKILL_DRAFT,
                                   llm_call=_stub_llm(["根据文档doc-A，结论X正确"])))
    assert report["passed"] is True
    assert len(report["caseResults"]) == DEFAULT_MIN_CASES
    events = list(db["gate_events"].rows.values())
    assert any(e.get("event_type") == "eval_gate.passed" for e in events)
    assert len(db["skill_eval_runs"].rows) == 1


def test_gate_dry_run_never_writes_audit(monkeypatch):
    rows = [_case(f"c{i}") for i in range(DEFAULT_MIN_CASES)]
    db = _db(cases=rows)
    _patch_db(monkeypatch, db)
    report = asyncio.run(run_gate(tenant_id="t1", skill_id="s1", version="1.0.0", skill_draft=SKILL_DRAFT, dry_run=True,
                                   llm_call=_stub_llm(["ok"])))
    assert report["dryRun"] is True
    assert db["gate_events"].rows == {}   # dry-run 不落阻断审计 (决策 #9)


# ---------------------------------------------------------------------------
# publish hook (T017) + route mapping (T018)
# ---------------------------------------------------------------------------
def test_publish_hooks_gate_before_release_insert(monkeypatch):
    """Gate 阻断时 release 不应被插入."""
    db = _db(cases=[])  # 无测试集 -> gate blocks
    _patch_db(monkeypatch, db)
    # gate 内 get_db 已 patch；skill_lifecycle 里 run_gate 会走 gate 内 patch
    service = OrganizationSkillLifecycle()
    # 让 publish 走真实流程
    with pytest.raises(EvalGateBlocked):
        asyncio.run(service.publish(tenant_id="t1", skill_id="s1"))
    assert len(db["organization_skill_releases"].rows) == 0


def test_publish_succeeds_when_gate_passes(monkeypatch):
    rows = [
        _case(f"c{i}", expected_refs=["doc-A"], expectations=["结论X"])
        for i in range(DEFAULT_MIN_CASES)
    ]
    db = _db(cases=rows)
    _patch_db(monkeypatch, db)

    async def _fake_gateway(prompt, *, tenant_id=None, model=None, timeout=None, retries=2):
        return "根据文档doc-A，结论X正确"

    from app.services.eval_gate import executor as executor_module
    monkeypatch.setattr(executor_module, "_call_gateway", _fake_gateway)
    service = OrganizationSkillLifecycle()
    doc, release = asyncio.run(service.publish(tenant_id="t1", skill_id="s1"))
    assert release["version"] == "1.0.0"
    assert len(db["organization_skill_releases"].rows) == 1


def test_metrics_equal_threshold_passes(monkeypatch):
    """等于阈值判通过 (决策 #11 边界)."""
    rows = [
        _case(f"c{i}", expected_refs=["doc-A"], expectations=["结论X"])
        for i in range(DEFAULT_MIN_CASES)
    ]
    db = _db(cases=rows)
    _patch_db(monkeypatch, db)
    # LLM 输出引用 doc-A 并包含结论X -> citation_support=1.0, task_success=1.0, refusal 不计
    report = asyncio.run(run_gate(tenant_id="t1", skill_id="s1", version="1.0.0", skill_draft=SKILL_DRAFT,
                                   llm_call=_stub_llm(["根据文档doc-A，结论X正确"])))
    assert report["metrics"]["citation_support"] == pytest.approx(1.0)
    assert report["passed"] is True

# ---------------------------------------------------------------------------
# T012b / R-12: chat-api 模型网关契约（Bearer HMAC 令牌 + ModelGatewayRequest）
# ---------------------------------------------------------------------------


def _gw_secret(monkeypatch, secret: str = "unit-test-gateway-secret-0123456789"):
    from app.core.config import settings

    monkeypatch.setattr(settings, "dsh_model_gateway_signing_secret", secret, raising=False)
    return secret


def test_gateway_token_roundtrip_matches_chat_api_algorithm(monkeypatch):
    """签发的令牌必须能通过 chat-api token.py 的校验（算法逐字节一致）."""
    import base64
    import hashlib
    import hmac
    import json

    secret = _gw_secret(monkeypatch)
    from app.services.eval_gate.gateway_auth import issue_model_gateway_token

    token = issue_model_gateway_token(
        tenant_id="t1", profile_version="eval-gate", model_instance_id="inst-1"
    )
    body_b64, sig_b64 = token.split(".")

    def _pad(raw: str) -> bytes:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))

    body = _pad(body_b64)
    expected = hmac.new(hashlib.sha256(secret.encode()).digest(), body, hashlib.sha256).digest()
    assert hmac.compare_digest(_pad(sig_b64), expected), "签名与 chat-api 侧算法不一致"

    claims = json.loads(body)
    assert claims["aud"] == "askai-model-gateway"
    assert claims["tenant_id"] == "t1"
    assert claims["profile_version"] == "eval-gate"
    assert claims["model_instance_id"] == "inst-1"
    assert claims["exp"] - claims["iat"] == 900
    assert claims["jti"]


def test_gateway_token_requires_usable_secret(monkeypatch):
    """密钥缺失/过短时必须显式失败，而不是发出一定被 401 的令牌."""
    _gw_secret(monkeypatch, "short")
    from app.services.eval_gate.gateway_auth import issue_model_gateway_token

    with pytest.raises(RuntimeError) as ei:
        issue_model_gateway_token(tenant_id="t1", profile_version="eval-gate", model_instance_id="i")
    assert "至少 16 字符" in str(ei.value)


def test_generate_request_scope_fields(monkeypatch):
    """extra='forbid'：只发白名单字段，且三个 scope 字段齐备."""
    from app.services.eval_gate.gateway_auth import build_generate_request

    body, profile, instance = build_generate_request(prompt="问", model="m1")
    assert body["provider"] == "askai-model-gateway"
    assert body["profileVersion"] == profile
    assert body["modelInstanceId"] == instance
    assert body["messages"] == [{"role": "user", "content": "问"}]
    assert "stream" not in body, "网关请求体不接受 stream 字段（extra=forbid）"
    assert set(body) == {"profileVersion", "modelInstanceId", "provider", "model", "messages"}


def test_call_gateway_blocking_sends_bearer_token_only(monkeypatch):
    """出站请求用 Bearer HMAC 令牌，不混入 v1|... 服务令牌头."""
    import json
    import urllib.request

    secret = _gw_secret(monkeypatch)
    from app.core.config import settings
    from app.services.eval_gate import executor as ex

    monkeypatch.setattr(settings, "backend_service_token", "v1|fake|fake", raising=False)
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"type":"text-delta","text":"ok"}\n{"type":"finish"}\n'

    def _fake_urlopen(request, timeout=None):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    out = ex._call_gateway_blocking("问", tenant_id="t1", model="m1", timeout=7)
    assert out == "ok"

    request = captured["request"]
    headers = {key.lower(): value for key, value in request.headers.items()}
    assert "x-mogo-service-token" not in headers, "网关不吃服务令牌头"
    auth = headers["authorization"]
    assert auth.startswith("Bearer ")
    token = auth[len("Bearer "):]
    assert token.count(".") == 1 and not token.startswith("v1|")

    # 令牌 claims 必须与请求体 scope 字段一致，否则 chat-api _validate_scope 拒绝
    import base64

    body_b64 = token.split(".")[0]
    claims = json.loads(base64.urlsafe_b64decode(body_b64 + "=" * (-len(body_b64) % 4)))
    payload = json.loads(request.data.decode("utf-8"))
    assert claims["profile_version"] == payload["profileVersion"]
    assert claims["model_instance_id"] == payload["modelInstanceId"]
    assert claims["tenant_id"] == "t1"
    assert captured["timeout"] == 7
