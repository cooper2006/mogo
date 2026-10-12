"""FR-1 (QF-521) 弱口令策略测试.

覆盖：长度下界、四类至少三类、纯数字/纯字母/无特殊字符、边界长度、
非字符串输入、可配置阈值、稳定拒绝文案。
"""

from __future__ import annotations

from app.security import password_policy as pp


# ---------------------------------------------------------------------------
# 通过 / 拒绝 的正反例
# ---------------------------------------------------------------------------


def test_accepts_twelve_char_three_class_password():
    verdict = pp.validate_password("Abcdefghijk9")  # 小写 + 大写 + 数字
    assert verdict.ok
    assert verdict.reason is None
    assert verdict.length == 12
    assert verdict.class_count == 3


def test_accepts_four_class_password():
    verdict = pp.validate_password("Str0ng!Passw0rd#1")
    assert verdict.ok
    assert verdict.class_count == 4
    assert pp.check_all_classes("Str0ng!Passw0rd#1")


def test_rejects_too_short():
    verdict = pp.validate_password("Ab1!xyz")
    assert not verdict.ok
    assert verdict.reason == pp.REASON_TOO_SHORT
    assert verdict.length == 7


def test_rejects_empty_string():
    verdict = pp.validate_password("")
    assert not verdict.ok
    assert verdict.reason == pp.REASON_EMPTY


def test_rejects_none_and_non_string():
    assert not pp.validate_password(None).ok
    assert pp.validate_password(None).reason == pp.REASON_NOT_TEXT
    assert not pp.validate_password(12345).ok
    assert pp.validate_password(12345).reason == pp.REASON_NOT_TEXT
    assert not pp.validate_password(True).ok


def test_rejects_pure_digits():
    verdict = pp.validate_password("123456789012")
    assert not verdict.ok
    assert verdict.reason == pp.REASON_TOO_FEW_CLASSES
    assert verdict.classes == frozenset({pp.DIGIT_CLASS})


def test_rejects_pure_letters():
    verdict = pp.validate_password("abcdefghijkl")
    assert not verdict.ok
    assert verdict.reason == pp.REASON_TOO_FEW_CLASSES
    assert verdict.classes == frozenset({pp.LOWER_CLASS})


def test_three_classes_without_special_char_is_accepted():
    # FR-1 要求"四类至少三类"，因此 upper+lower+digit 已达标
    verdict = pp.validate_password("Abcdefghij12")
    assert verdict.ok
    assert verdict.class_count == 3
    assert pp.SPECIAL_CLASS in verdict.missing_classes


def test_two_classes_only_rejected():
    # 只有大写 + 数字 = 2 类，必须拒绝
    verdict = pp.validate_password("AB12AB12AB12")
    assert not verdict.ok
    assert verdict.class_count == 2
    assert set(verdict.missing_classes) >= {pp.LOWER_CLASS, pp.SPECIAL_CLASS}


def test_rejects_too_long():
    long_password = "A" * (pp.MAX_PASSWORD_LENGTH + 1)
    verdict = pp.validate_password(long_password + "b1!")
    assert not verdict.ok
    assert verdict.reason == pp.REASON_TOO_LONG


def test_accepts_max_length_boundary():
    password = "Abcd1234!xyz" + "Q" * (pp.MAX_PASSWORD_LENGTH - len("Abcd1234!xyz"))
    assert len(password) == pp.MAX_PASSWORD_LENGTH
    verdict = pp.validate_password(password)
    assert verdict.ok


def test_whitespace_does_not_count_as_a_class():
    # 空格不应被当作"特殊字符"来凑数
    verdict = pp.validate_password("abcd1234    ")
    assert not verdict.ok
    assert pp.SPECIAL_CLASS not in verdict.classes


def test_unicode_digits_do_not_count_as_digits():
    # '²' 等上标数字不应通过 str.isdigit() 漏洞凑成"数字"类（此处口令不含 ASCII 数字）
    verdict = pp.validate_password("abcdefgh²²²²")
    assert pp.DIGIT_CLASS not in verdict.classes
    assert pp.SPECIAL_CLASS in verdict.classes
    # 只有 lower + special 两类 → 不达标
    assert not verdict.ok
    assert verdict.reason == pp.REASON_TOO_FEW_CLASSES


# ---------------------------------------------------------------------------
# 客户端可见文案与内部细节分离
# ---------------------------------------------------------------------------


def test_public_message_is_stable_and_non_enumerable():
    short = pp.validate_password("Ab1!xyz")
    weak = pp.validate_password("Abcdefghijk9"[:8] + "!x")
    assert short.public_message == weak.public_message == pp.WEAK_PASSWORD_MESSAGE
    # 文案中不应出现具体原因码
    assert pp.REASON_TOO_SHORT not in pp.WEAK_PASSWORD_MESSAGE
    assert pp.REASON_TOO_FEW_CLASSES not in pp.WEAK_PASSWORD_MESSAGE


def test_reject_reason_public_returns_none_when_ok():
    assert pp.reject_reason_public(pp.validate_password("Str0ng!Passw0rd#1")) is None
    assert pp.reject_reason_public(pp.validate_password("123456789012")) == pp.WEAK_PASSWORD_MESSAGE


# ---------------------------------------------------------------------------
# 便捷函数与可配置性
# ---------------------------------------------------------------------------


def test_is_valid_password_wraps_validate():
    assert pp.is_valid_password("Str0ng!Passw0rd#1")
    assert not pp.is_valid_password("123456789012")


def test_thresholds_are_configurable():
    # 自定义策略（例如访客账号放宽到 8 位 / 2 类）
    verdict = pp.validate_password("Ab1!xyzw", min_length=8, min_classes=2)
    assert verdict.ok
    # 默认策略下同一口令被拒（长度不足 12）
    assert not pp.validate_password("Ab1!xyzw").ok
    assert pp.validate_password("Ab1!xyzw").reason == pp.REASON_TOO_SHORT


def test_classes_of_is_stable_and_ordered():
    assert pp.classes_of("Ab1!x") == ("upper", "lower", "digit", "special")
    assert pp.classes_of("abc") == ("lower",)


def test_classify_returns_frozenset():
    assert isinstance(pp.classify("Ab1!"), frozenset)


def test_policy_summary_shape():
    summary = pp.policy_summary()
    assert summary["min_length"] == pp.MIN_PASSWORD_LENGTH == 12
    assert summary["min_classes"] == pp.MIN_CLASSES == 3
    assert summary["classes"] == list(pp.ALL_CLASSES)
    assert summary["public_message"] == pp.WEAK_PASSWORD_MESSAGE


def test_constants_match_spec():
    # FR-1 明确数值：长度 ≥ 12、四类至少三类
    assert pp.MIN_PASSWORD_LENGTH == 12
    assert pp.MIN_CLASSES == 3
    assert len(pp.ALL_CLASSES) == 4
