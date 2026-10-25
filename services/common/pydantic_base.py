"""025 QF-210 (T012)：Pydantic 未知字段策略统一基类。

契约默认 `extra='ignore'`（静默忽略未知字段，前向兼容，不破坏老客户端）；
需要严格校验的 schema 继承 `MogoStrictModel`（`extra='forbid'`），拒绝未知字段，
避免拼写错误或多余字段被静默吞掉。

本文件为共享模板（`services/common/`），三服务各自复制到
`services/<svc>/app/common/pydantic_base.py`。
"""

from pydantic import BaseModel, ConfigDict


class MogoModel(BaseModel):
    """默认契约模型：未知字段忽略（`extra='ignore'`）。"""

    model_config = ConfigDict(extra="ignore")


class MogoStrictModel(BaseModel):
    """严格契约模型：未知字段拒绝（`extra='forbid'`）。"""

    model_config = ConfigDict(extra="forbid")