"""023 T038 — Celery task trace_id 传递。

在 Celery task 执行时注入 trace_id，使异步任务的日志和 span 与触发请求关联。
"""
from __future__ import annotations

from celery import Task

from app.common.observability_base import trace_id_var


class TracedTask(Task):
    """Celery Task 基类：在执行前注入 trace_id。"""

    def __call__(self, *args, **kwargs):
        # 从 task 参数中提取 trace_id（可选）
        trace_id = kwargs.pop("_trace_id", None)
        if trace_id:
            trace_id_var.set(trace_id)
        return self.run(*args, **kwargs)

    def apply_async(self, args=None, kwargs=None, **options):
        # 在发送时注入当前 trace_id
        if kwargs is None:
            kwargs = {}
        kwargs.setdefault("_trace_id", trace_id_var.get())
        return super().apply_async(args=args, kwargs=kwargs, **options)
