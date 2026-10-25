"""023 T001/T002/T003 — 三服务共享可观测性基座（权威源）。

> **vendored 副本纪律**：本文件的权威源在 `services/common/observability_base.py`；
> 各服务镜像按服务目录构建（`docker-compose.build.yml` 的 context 是
> `services/<svc>/`），`services/common/` 不在构建上下文内，因此每个服务持有一份
> **逐字节相同**的副本 `services/<svc>/app/common/observability_base.py`。
> `scripts/check_common_sync.py`（CI，quality-gate backend-quality）校验副本与权威
> 源一致——漂移即失败。修改必须先改权威源，再 `cp` 到三个服务，禁止只改副本。
> 同一纪律适用于 `dependency_guard.py` 与 `slo.py`。

范围（spec.md FR-1~FR-13，Clarify 决策 2026-10-24：Loki / Tempo / pybreaker）：
- T001 结构化日志基类：structlog 配置 + 字段约定 + trace_id 上下文变量。
- T002 追踪基类：OpenTelemetry SDK 初始化（TracerProvider / Sampler / OTLP Exporter）。
- T003 指标基类：Prometheus client 初始化（CollectorRegistry + ASGI HTTP adapter）。

设计约束：
- **零默认成本**：未显式 `configure_logging/init_tracing/init_metrics` 时不产生任何
  副作用，服务保持既有行为（渐进接线，Phase 2/3/4 各故事分别接入）。
- OTLP 端点未配置（`MOGO_OTEL_EXPORTER_ENDPOINT` 为空）时，tracing 只装配
  parent-based sampler + 空 exporter 的本地 provider，不建外连。
- 日志字段约定（FR-3 / checklist CHK 口径）：`ts`（ISO8601 本地时区）、`level`、
  `service`、`message`，可选 `trace_id` / `span_id` / `tenant_id` / `user_id`。
"""
from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from typing import Any, Callable, Mapping

# ─────────────────────────── T001 结构化日志基类 ───────────────────────────

#: 请求级 trace_id 上下文变量（FR-4：错误日志含完整上下文；与 025 trace_id 中间件
#: 共享同一语义值，由服务的中间件在请求进入时 set/reset）。
trace_id_var: ContextVar[str] = ContextVar("mogo_trace_id", default="")
span_id_var: ContextVar[str] = ContextVar("mogo_span_id", default="")
tenant_id_var: ContextVar[str] = ContextVar("mogo_tenant_id", default="")
user_id_var: ContextVar[str] = ContextVar("mogo_user_id", default="")

LOG_FIELD_ORDER = (
    "ts",
    "level",
    "service",
    "message",
    "trace_id",
    "span_id",
    "tenant_id",
    "user_id",
)


def current_trace_context() -> dict[str, str]:
    """当前上下文中的追踪字段（仅非空值），供日志绑定与响应体共用。"""
    out: dict[str, str] = {}
    for key, var in (
        ("trace_id", trace_id_var),
        ("span_id", span_id_var),
        ("tenant_id", tenant_id_var),
        ("user_id", user_id_var),
    ):
        value = var.get()
        if value:
            out[key] = value
    return out


def _add_trace_context(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    for key, value in current_trace_context().items():
        event_dict.setdefault(key, value)
    return event_dict


def configure_logging(
    service_name: str,
    *,
    level: str | None = None,
    json_output: bool | None = None,
) -> None:
    """把 root logger 接到 structlog 的 JSON renderer（FR-1）。

    - `level` 缺省读 `LOG_LEVEL` 环境变量，再缺省 `INFO`；运行时切换由服务的
      `/admin/log-level` 端点调 `logging.getLogger().setLevel()` 完成（FR-2）。
    - `json_output` 缺省读 `MOGO_LOG_JSON`（默认 true；本地开发可设 false 走
      console renderer）。生产必须 JSON——非 JSON 时本函数会告警一次。
    - 幂等：重复调用只重配一次。
    """
    import structlog

    resolved_level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    if json_output is None:
        json_output = os.environ.get("MOGO_LOG_JSON", "true").strip().lower() not in {
            "0",
            "false",
            "no",
        }
    if not json_output and resolved_level in {"WARNING", "ERROR", "CRITICAL"}:
        # 允许，但提示：生产语义要求 JSON（FR-1 验收是 JSON 字段稳定）。
        logging.warning("MOGO_LOG_JSON=false 下日志非 JSON，仅适合本地开发")

    shared_processors: list[Callable[..., dict]] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        _add_trace_context,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Callable = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if json_output
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(getattr(logging, resolved_level, logging.INFO))
    # 服务名注入所有记录（FR-3 字段约定）
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str) -> Any:
    """返回 structlog bound logger（未 configure 时也可用：structlog 默认 no-op 链）。"""
    import structlog

    return structlog.get_logger(name)


# ─────────────────────────── T002 追踪基类 ───────────────────────────

_tracing_initialized = False


def init_tracing(
    service_name: str,
    *,
    otlp_endpoint: str | None = None,
    sampler_ratio: float | None = None,
) -> bool:
    """OpenTelemetry TracerProvider 初始化（FR-7/FR-8，决策 OQ-2：Tempo via OTLP）。

    返回是否真正装配了 exporter。端点解析顺序：显式参数 →
    `OTEL_EXPORTER_OTLP_ENDPOINT` 环境变量；两者皆空 → 本地 provider（无外连，
    返回 False）。采样率：显式 → `OTEL_SAMPLER_PROBABILITY` → 默认 0.1。
    """
    global _tracing_initialized
    if _tracing_initialized:
        return False

    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    endpoint = otlp_endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if sampler_ratio is None:
        raw = os.environ.get("OTEL_SAMPLER_PROBABILITY", "0.1")
        try:
            sampler_ratio = max(0.0, min(1.0, float(raw)))
        except ValueError:
            sampler_ratio = 0.1

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(
        resource=resource, sampler=ParentBased(TraceIdRatioBased(sampler_ratio))
    )

    exporter_attached = False
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
                endpoint=endpoint, insecure=not endpoint.startswith("https"),
            )))
            exporter_attached = True
        except Exception:
            # exporter 装配失败不阻断启动（可观测性自身不得成为故障源，FR-13 容错
            # 原则的反向应用）；降级为本地 provider + 服务端日志告警。
            logging.getLogger(__name__).exception(
                "OTLP exporter init failed; falling back to local-only tracing"
            )

    trace.set_tracer_provider(provider)
    _tracing_initialized = True
    return exporter_attached


def get_tracer(name: str = "mogo") -> Any:
    from opentelemetry import trace

    return trace.get_tracer(name)


def traced(task: Callable, *, span_name: str | None = None) -> Callable:
    """把可调用包一层 span（依赖级追踪的最小原语，US2 任务会广泛使用）。"""
    import functools

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        tracer = get_tracer()
        with tracer.start_as_current_span(span_name or getattr(task, "__name__", "span")):
            return task(*args, **kwargs)

    return functools.wraps(task)(wrapper)


# ───────────────── T032 FastAPI/HTTPX Instrumentor 集成 ─────────────────

_instrumentor_holder: dict[str, Any] = {}


def instrument_fastapi(app: Any) -> bool:
    """T032 — FastAPI 自动插桩（HTTP server span）。

    幂等：重复调用同一 app 只 instrument 一次。
    失败不阻断启动（可观测性自身不得成为故障源，FR-13）。
    """
    if id(app) in _instrumentor_holder:
        return False
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        _instrumentor_holder[id(app)] = True
        return True
    except Exception:
        logging.getLogger(__name__).exception(
            "FastAPIInstrumentor init failed; app runs without tracing"
        )
        return False


def instrument_httpx() -> bool:
    """T032 — HTTPX 自动插桩（HTTP client span，下游调用追踪）。

    幂等：重复调用只 instrument 一次。
    失败不阻断启动。
    """
    if "httpx" in _instrumentor_holder:
        return False
    try:
        from opentelemetry.instrumentation.httpx import HTTPXInstrumentor
        HTTPXInstrumentor().instrument()
        _instrumentor_holder["httpx"] = True
        return True
    except Exception:
        logging.getLogger(__name__).exception(
            "HTTPXInstrumentor init failed; downstream calls without tracing"
        )
        return False


# ─────────────────────────── T003 指标基类 ───────────────────────────

_registry_holder: dict[str, Any] = {}


def init_metrics(service_name: str) -> Any:
    """返回服务专属 CollectorRegistry，并登记黄金信号基础指标（FR-9/FR-10）。

    四类指标（延迟/流量/错误率/饱和度）中，延迟+流量+错误率由本函数的 HTTP
    指标承担（服务在中间件里 observe），饱和度由进程指标（process collector）
    + 依赖层直方图承担。label 白名单（FR-12 基数受控）：
    `method` / `path_template` / `status_class`（而非完整 status/path 原值）。
    """
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

    registry = CollectorRegistry()
    _registry_holder[service_name] = registry

    metrics = {
        "http_request_duration_seconds": Histogram(
            "mogo_http_request_duration_seconds",
            "HTTP request latency seconds",
            ["method", "path_template", "status_class"],
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
            registry=registry,
        ),
        "http_requests_total": Counter(
            "mogo_http_requests_total",
            "HTTP requests total",
            ["method", "path_template", "status_class"],
            registry=registry,
        ),
        "http_errors_total": Counter(
            "mogo_http_errors_total",
            "HTTP 5xx responses total",
            ["method", "path_template"],
            registry=registry,
        ),
        "inflight_requests": Gauge(
            "mogo_http_inflight_requests",
            "In-flight HTTP requests (saturation proxy)",
            ["method"],
            registry=registry,
        ),
    }
    try:
        from prometheus_client.process_collector import ProcessCollector

        ProcessCollector(registry=registry)
    except Exception:  # pragma: no cover - platform specific
        pass
    return metrics


def get_registry(service_name: str) -> Any:
    """取回 `init_metrics(service_name)` 建立的 CollectorRegistry。

    服务层 `observability/metrics.py` 的业务指标注册需要 registry 对象
    （`init_metrics` 返回的是指标字典，不含 registry），故经此函数获取。
    """
    if service_name not in _registry_holder:
        raise RuntimeError(f"init_metrics({service_name!r}) must run before get_registry")
    return _registry_holder[service_name]


def metrics_asgi_app(service_name: str) -> Any:
    """`/metrics` ASGI 子应用（FR-11 暴露）。未 init_metrics 时抛错提示接线顺序。"""
    from prometheus_client import make_asgi_app

    if service_name not in _registry_holder:
        raise RuntimeError(f"init_metrics({service_name!r}) must run before /metrics mount")
    return make_asgi_app(registry=_registry_holder[service_name])


def status_class(status_code: int) -> str:
    """label 白名单收敛：具体状态码 → 类别（FR-12）。"""
    return f"{status_code // 100}xx"


# ─────────────────────────── T024 启动自检 ───────────────────────────

_selfcheck_results: dict[str, dict[str, Any]] = {}


def _check_mongo(uri: str, timeout: float = 2.0) -> dict[str, Any]:
    """MongoDB ping 自检。"""
    try:
        from pymongo import MongoClient
        client = MongoClient(uri, serverSelectionTimeoutMS=int(timeout * 1000))
        client.admin.command("ping")
        client.close()
        return {"ok": True, "detail": "ping ok"}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def _check_redis(url: str, timeout: float = 2.0) -> dict[str, Any]:
    """Redis ping 自检。"""
    try:
        import redis as _redis_mod
        client = _redis_mod.Redis.from_url(
            url, socket_timeout=timeout, socket_connect_timeout=timeout
        )
        client.ping()
        client.close()
        return {"ok": True, "detail": "ping ok"}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def _check_llm_provider(base_url: str, timeout: float = 2.0) -> dict[str, Any]:
    """LLM provider 连通性自检（HTTP GET /models 或根路径）。"""
    try:
        import urllib.request
        req = urllib.request.Request(base_url.rstrip("/") + "/v1/models", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"ok": resp.status < 400, "detail": f"HTTP {resp.status}"}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def _check_config_files(paths: list[str]) -> dict[str, Any]:
    """配置文件完整性自检（存在 + 可读）。"""
    results = {}
    for p in paths:
        try:
            with open(p, "r") as f:
                f.read(1)
            results[p] = {"ok": True, "detail": "readable"}
        except Exception as exc:
            results[p] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    all_ok = all(v["ok"] for v in results.values())
    return {"ok": all_ok, "detail": results}


def startup_selfcheck(
    *,
    mongo_uri: str | None = None,
    redis_url: str | None = None,
    llm_base_url: str | None = None,
    config_paths: list[str] | None = None,
    service_name: str = "unknown",
) -> dict[str, Any]:
    """T024 启动自检：依赖可达性 + 配置文件完整性。

    设计约束（FR-5 / T024）：
    - **自检失败不退出**：失败结果写入 `_selfcheck_results`，由 /ready 端点读取返回 503。
    - 幂等：重复调用只覆盖结果，不累积。
    - 零依赖：mongo/redis/llm 检查均懒加载 import，未配置时跳过。
    """
    global _selfcheck_results

    results: dict[str, Any] = {"service": service_name, "checks": {}}

    if mongo_uri:
        results["checks"]["mongodb"] = _check_mongo(mongo_uri)
    if redis_url:
        results["checks"]["redis"] = _check_redis(redis_url)
    if llm_base_url:
        results["checks"]["llm_provider"] = _check_llm_provider(llm_base_url)
    if config_paths:
        results["checks"]["config_files"] = _check_config_files(config_paths)

    all_ok = all(
        v.get("ok", False)
        for v in results["checks"].values()
        if isinstance(v, dict) and "ok" in v
    )
    results["ok"] = all_ok

    _selfcheck_results[service_name] = results
    return results


def get_selfcheck_results(service_name: str) -> dict[str, Any]:
    """获取指定服务的启动自检结果（/ready 端点读取用）。"""
    return _selfcheck_results.get(service_name, {})


# ─────────────────── FR-21 熔断/限流指标（T088）───────────────────

BREAKER_STATE_LABELS: tuple[str, ...] = ("closed", "open", "half_open")


def register_resilience_metrics(registry: Any, service_name: str) -> dict[str, Any]:
    """注册熔断器与限流/背压指标。

    * ``mogo_circuit_breaker_state{dependency,state}``：每依赖每状态一条，
      当前状态置 1、其余置 0。用「每状态一条 gauge」而不是「一条 gauge 带会
      变化的 state 标签」，因为 Prometheus 不能删除时序，标签变化会留下
      永不归零的旧序列（查询时 sum by 会出现两个 1）。
    * ``mogo_circuit_breaker_failure_count{dependency}``：连续失败计数，
      观察「离熔断还有多远」。
    * ``mogo_rate_limit_rejections_total{reason}`` / ``mogo_backpressure_rejections_total``：
      中间件拒绝计数（T087 的 on_reject 钩子）。
    """
    from prometheus_client import Counter, Gauge

    metrics: dict[str, Any] = {
        "circuit_breaker_state": Gauge(
            "mogo_circuit_breaker_state",
            "Circuit breaker state (1 = current)",
            ["dependency", "state"],
            registry=registry,
        ),
        "circuit_breaker_failure_count": Gauge(
            "mogo_circuit_breaker_failure_count",
            "Consecutive failures counted by the breaker",
            ["dependency"],
            registry=registry,
        ),
        "rate_limit_rejections_total": Counter(
            "mogo_rate_limit_rejections_total",
            "Requests rejected by the rate limiter",
            ["reason"],
            registry=registry,
        ),
        "backpressure_rejections_total": Counter(
            "mogo_backpressure_rejections_total",
            "Requests rejected because in-flight depth exceeded the limit",
            [],
            registry=registry,
        ),
    }
    metrics["service_name"] = service_name

    def sync_breakers(items: Any) -> None:
        """把 ``[(dependency, breaker), ...]`` 的当前状态刷进指标。"""
        for dependency, breaker in items:
            state = getattr(breaker, "state", None)
            state_name = type(state).__name__ if state is not None else ""
            if state_name == "CircuitOpenState":
                current = "open"
            elif state_name == "CircuitHalfOpenState":
                current = "half_open"
            else:
                current = "closed"
            for label in BREAKER_STATE_LABELS:
                metrics["circuit_breaker_state"].labels(
                    dependency=dependency, state=label
                ).set(1.0 if label == current else 0.0)
            count = getattr(breaker, "fail_counter", None)
            if count is None:
                count = getattr(breaker, "_failure_count", 0)
            metrics["circuit_breaker_failure_count"].labels(
                dependency=dependency
            ).set(float(count or 0))

    metrics["sync_breakers"] = sync_breakers
    return metrics
