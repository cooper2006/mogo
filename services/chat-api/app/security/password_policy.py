"""FR-1 (QF-521) 弱口令策略.

策略：长度 ≥ 12 且大写/小写/数字/特殊字符四类中至少三类。

判定是纯函数、无副作用、无数据库依赖，因此可以在登录/改密/注册链路上
任意位置调用，也可以在单元测试里逐字符验证。

对外只暴露一个稳定的拒绝文案（:data:`WEAK_PASSWORD_MESSAGE`）：不把
「缺大写」/「长度不足」逐条回显给客户端，避免口令策略成为口令强度探测的
可枚举 oracle（与 FR-22「错误不泄漏内部信息」同向）。细节只进
:class:`PasswordVerdict`，供服务端日志与审计使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
MIN_CLASSES = 3

# 四类字符集
UPPER_CLASS = "upper"
LOWER_CLASS = "lower"
DIGIT_CLASS = "digit"
SPECIAL_CLASS = "special"
ALL_CLASSES: tuple[str, ...] = (UPPER_CLASS, LOWER_CLASS, DIGIT_CLASS, SPECIAL_CLASS)

# 服务端唯一拒绝文案：不含任何可枚举细节
WEAK_PASSWORD_MESSAGE = "口令不符合安全策略：长度至少 12 位，且需包含大写字母、小写字母、数字、特殊字符中的至少三类。"

# 内部使用的细粒度原因码（仅进日志/审计，不回显给客户端）
REASON_TOO_SHORT = "too_short"
REASON_TOO_LONG = "too_long"
REASON_TOO_FEW_CLASSES = "too_few_classes"
REASON_EMPTY = "empty"
REASON_NOT_TEXT = "not_text"


def _is_upper(ch: str) -> bool:
    return ch.isupper() and ch.isalpha()


def _is_lower(ch: str) -> bool:
    return ch.islower() and ch.isalpha()


def _is_digit(ch: str) -> bool:
    # 不用 str.isdigit：它会接受 '²'、'٣' 等非 ASCII 数字，与「数字」的
    # 口令强度语义不符（且这些字符常被前端 trim/规范化掉，造成前后端判定漂移）。
    return "0" <= ch <= "9"


def classify(password: str) -> frozenset[str]:
    """返回口令命中的字符类别集合（FR-1）。空白字符不计入任何类别。"""
    classes: set[str] = set()
    for ch in password:
        if _is_upper(ch):
            classes.add(UPPER_CLASS)
        elif _is_lower(ch):
            classes.add(LOWER_CLASS)
        elif _is_digit(ch):
            classes.add(DIGIT_CLASS)
        elif not ch.isspace():
            classes.add(SPECIAL_CLASS)
    return frozenset(classes)


@dataclass(frozen=True)
class PasswordVerdict:
    """口令判定结果。

    ``ok`` 为 False 时 ``reason`` 是内部原因码，``public_message`` 是可直接回显的稳定文案。
    """

    ok: bool
    reason: str | None = None
    length: int = 0
    classes: frozenset[str] = field(default_factory=frozenset)
    class_count: int = 0
    missing_classes: tuple[str, ...] = ()

    @property
    def is_rejected(self) -> bool:
        return not self.ok

    @property
    def public_message(self) -> str:
        return WEAK_PASSWORD_MESSAGE if self.ok else WEAK_PASSWORD_MESSAGE


def validate_password(
    password: object,
    *,
    min_length: int = MIN_PASSWORD_LENGTH,
    min_classes: int = MIN_CLASSES,
    max_length: int = MAX_PASSWORD_LENGTH,
) -> PasswordVerdict:
    """校验口令是否符合 FR-1 策略。

    Args:
        password: 候选口令。传入 ``None`` / 非字符串视为不合规（不抛异常）。
        min_length: 最小长度，默认 12（FR-1）。
        min_classes: 至少命中的字符类别数，默认 3（FR-1）。
        max_length: 最大长度，防止超长口令触发内存放大攻击。

    Returns:
        :class:`PasswordVerdict`。永不为 None，永不抛异常。
    """
    if password is None or isinstance(password, bool):
        return PasswordVerdict(ok=False, reason=REASON_NOT_TEXT)
    if not isinstance(password, str):
        return PasswordVerdict(ok=False, reason=REASON_NOT_TEXT, length=0)

    length = len(password)
    if length == 0:
        return PasswordVerdict(ok=False, reason=REASON_EMPTY, length=0, classes=frozenset())

    classes = classify(password)
    class_count = len(classes)
    missing = tuple(c for c in ALL_CLASSES if c not in classes)

    if length < min_length:
        return PasswordVerdict(
            ok=False,
            reason=REASON_TOO_SHORT,
            length=length,
            classes=classes,
            class_count=class_count,
            missing_classes=missing,
        )
    if length > max_length:
        return PasswordVerdict(
            ok=False,
            reason=REASON_TOO_LONG,
            length=length,
            classes=classes,
            class_count=class_count,
            missing_classes=missing,
        )
    if class_count < min_classes:
        return PasswordVerdict(
            ok=False,
            reason=REASON_TOO_FEW_CLASSES,
            length=length,
            classes=classes,
            class_count=class_count,
            missing_classes=missing,
        )
    return PasswordVerdict(
        ok=True,
        length=length,
        classes=classes,
        class_count=class_count,
        missing_classes=missing,
    )


def is_valid_password(
    password: object,
    *,
    min_length: int = MIN_PASSWORD_LENGTH,
    min_classes: int = MIN_CLASSES,
    max_length: int = MAX_PASSWORD_LENGTH,
) -> bool:
    """FR-1 的布尔便捷包装：`validate_password(...).ok`。"""
    return validate_password(
        password, min_length=min_length, min_classes=min_classes, max_length=max_length
    ).ok


def classes_of(password: str) -> tuple[str, ...]:
    """返回口令命中的类别名，按固定顺序排序（便于稳定断言）。"""
    hit = classify(password)
    return tuple(c for c in ALL_CLASSES if c in hit)


def check_all_classes(password: str) -> bool:
    """四类是否全部命中（比 FR-1 更严，供后续「强口令」档位使用）。"""
    return len(classify(password)) == len(ALL_CLASSES)


def sample_passwords() -> tuple[str, ...]:
    """合规示例（供文档/quickstart 引用，不作为真实口令使用）。"""
    return ("Correct-Horse-99", "Str0ng!Passw0rd#1")


def reject_reason_public(verdict: PasswordVerdict) -> str | None:
    """把 verdict 变成回显给客户端的文案；通过时返回 None。"""
    if verdict.ok:
        return None
    return verdict.public_message


def policy_summary() -> dict[str, object]:
    """策略摘要，用于启动自检与 /health 之外的调试端点。"""
    return {
        "min_length": MIN_PASSWORD_LENGTH,
        "max_length": MAX_PASSWORD_LENGTH,
        "min_classes": MIN_CLASSES,
        "classes": list(ALL_CLASSES),
        "public_message": WEAK_PASSWORD_MESSAGE,
    }
