"""Feature 001 — PII redaction unit tests (US3 / T022).

Acceptance:
* phone number under the default ``mask`` strategy -> ``138****0000``-style
* private key under the default ``remove`` strategy -> disappears from the text
* audit trace carries 0 plaintext PII (fingerprints only)
"""

from __future__ import annotations

import pytest

from app.governance.gatekeeper import GateDecision
from app.governance.pii import (
    DEFAULT_STRATEGY,
    PII_TYPES,
    apply_strategy,
    find_pii,
    redact_text,
)


class TestFindPii:
    def test_phone_recognized(self):
        hits = find_pii("联系电话 13800138000 谢谢")
        assert ("phone", "13800138000") in [(t, v) for t, _s, _e, v in hits]

    def test_email_recognized(self):
        hits = find_pii("mail: alice@example.com ok")
        assert ("email", "alice@example.com") in [(t, v) for t, _s, _e, v in hits]

    def test_id_card_beats_bank_card(self):
        """An 18-digit national ID must be claimed as id_card, not bank_card."""
        value = "110101199003071234"
        hits = find_pii(f"证件 {value}")
        types = {t for t, _s, _e, _v in hits}
        assert types == {"id_card"}

    def test_private_key_pem(self):
        text = "key: -----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"
        hits = find_pii(text)
        assert any(t == "private_key" for t, _s, _e, _v in hits)

    def test_no_pii(self):
        assert find_pii("plain text with 123 numbers") == []


class TestApplyStrategy:
    def test_phone_mask_default(self):
        # Default phone strategy = mask -> first 3 + **** + last 4
        result = redact_text("call 13800000000")
        assert "13800000000" not in result
        assert "138****0000" in result

    def test_private_key_remove_default(self):
        result = redact_text(
            "secret: -----BEGIN RSA PRIVATE KEY-----\nxyz\n-----END RSA PRIVATE KEY-----"
        )
        assert "PRIVATE KEY" not in result
        assert "xyz" not in result

    def test_id_card_hash_default(self):
        value = "110101199003071234"
        result = redact_text(value)
        assert value not in result
        # Hash strategy yields a 12-char hex + ellipsis
        assert "…" in result
        assert len(result.split("…")[0]) == 12

    def test_email_abstract_default(self):
        result = redact_text("a@b.co")
        assert "a@b.co" not in result
        assert "[EMAIL]" in result

    def test_bank_card_mask(self):
        result = redact_text("card 4242424242424242")
        assert "4242424242424242" not in result
        assert "424" in result  # first 3 digits kept


class TestPiiPolicyMatrix:
    """5 PII classes x 4 strategies matrix sanity (T022: 5x4 matrix)."""

    @pytest.mark.parametrize("pii_type", ["private_key", "id_card", "bank_card", "phone", "email"])
    @pytest.mark.parametrize("strategy", ["mask", "remove", "hash", "abstract"])
    def test_matrix_no_plaintext(self, pii_type, strategy):
        samples = {
            "private_key": "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----",
            "id_card": "110101199003071234",
            "bank_card": "4242424242424242",
            "phone": "13800138000",
            "email": "alice@example.com",
        }
        sample = samples[pii_type]
        policies = {t: strategy for t in PII_TYPES}
        result = redact_text(sample, policies)
        # No strategy may return the original plaintext
        assert sample not in result, f"{pii_type}/{strategy} leaked plaintext"


class TestRedactText:
    def test_mixed_text(self):
        text = "call 13800138000 or mail bob@corp.io, card 4242424242424242"
        result = redact_text(text)
        assert "13800138000" not in result
        assert "bob@corp.io" not in result
        assert "4242424242424242" not in result

    def test_empty_text_passthrough(self):
        assert redact_text("") == ""
        assert redact_text(None) == ""

    def test_policy_override(self):
        result = redact_text("13800138000", policies={"phone": "remove"})
        assert "138" not in result

    def test_default_policies_match_schema(self):
        from app.governance.schema import DEFAULT_PII_POLICY

        assert DEFAULT_STRATEGY == DEFAULT_PII_POLICY


class TestRedactionLayerTrace:
    """The gate layer path, not just the pure PII helpers.

    001 hotfix (2026-10-19): ``RedactionLayer.evaluate`` read ``trace.count``,
    which the dataclass never declared — every PII-carrying gate call raised
    ``AttributeError`` inside the layer, admin-api returned 500, and chat-api
    fail-closed the whole turn into a 403. The bug survived from 2026-09-23
    because only ``as_document()`` computed a count and nothing exercised the
    layer itself. These tests drive the real layer so it cannot regress.
    """

    @staticmethod
    def _ctx(request: dict, response: dict | None = None) -> "GateContext":
        from app.governance.gatekeeper import GateContext

        return GateContext(
            tool="browser",
            tenant_id="tenant-a",
            user_id="user-1",
            request=request,
            response=response or {},
        )

    @staticmethod
    async def _run(layer, ctx: "GateContext"):
        from app.governance.layers.redaction import RedactionLayer

        # The layer reads pii_policies from the DB; an empty policy store must
        # degrade to the built-in defaults, so patch the lookup, not the layer.
        class _EmptyCollection:
            def find(self, *_a, **_k):
                class _Cursor:
                    def __aiter__(self):
                        return self

                    async def __anext__(self):
                        raise StopAsyncIteration

                return _Cursor()

        class _Db:
            def __getitem__(self, _name):
                return _EmptyCollection()

        from app.core import db as db_module

        original = db_module.get_db
        db_module.get_db = lambda: _Db()
        try:
            return await RedactionLayer().evaluate(ctx)
        finally:
            db_module.get_db = original

    @pytest.mark.asyncio
    async def test_pii_in_request_redacts_and_counts(self):
        ctx = self._ctx({"text": "call 13800138000 please"})
        verdict = await self._run(None, ctx)

        assert verdict.decision is GateDecision.ALLOW
        # The count lives on the trace, not only in the document helper.
        assert ctx.annotations["redaction"]["count"] == 1
        assert ctx.annotations["redaction"]["types"] == {"phone": 1}
        # The plaintext is rewritten in place, never kept.
        assert "13800138000" not in ctx.request["text"]

    @pytest.mark.asyncio
    async def test_no_pii_keeps_layer_allow_without_trace(self):
        ctx = self._ctx({"text": "plain text, no pii"})
        verdict = await self._run(None, ctx)

        assert verdict.decision is GateDecision.ALLOW
        assert "redaction" not in ctx.annotations

    @pytest.mark.asyncio
    async def test_response_text_is_also_redacted(self):
        ctx = self._ctx({"text": "ok"}, {"note": "mail bob@corp.io"})
        verdict = await self._run(None, ctx)

        assert verdict.decision is GateDecision.ALLOW
        assert ctx.annotations["redaction"]["count"] == 1
        assert "bob@corp.io" not in ctx.response["note"]

