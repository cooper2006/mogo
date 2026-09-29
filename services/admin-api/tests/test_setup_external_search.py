from __future__ import annotations

import pytest

from app.services.external_search_provider import ExternalSearchConfigError, normalized_config
from app.services.setup_external_search import setup_provider_catalog


def test_setup_catalog_exposes_supported_providers_without_secrets() -> None:
    providers = setup_provider_catalog()

    assert [item["id"] for item in providers] == ["tavily", "serper", "serpapi", "baidu_qianfan", "volc_ark", "claw_search"]
    assert all("apiKey" not in item for item in providers)


def test_claw_search_config_does_not_require_api_key() -> None:
    config = normalized_config("claw_search", api_key="")

    assert config["api_key"] == ""
    assert config["endpoint"] == "https://www.claw-search.com/api/search"


def test_search_config_applies_provider_defaults() -> None:
    config = normalized_config("baidu_qianfan", api_key="secret")

    assert config["api_key"] == "secret"
    assert config["endpoint"] == "https://qianfan.baidubce.com/v2/ai_search/web_search"


@pytest.mark.parametrize(
    ("provider", "endpoint"),
    [
        ("serper", "https://google.serper.dev/search"),
        ("serpapi", "https://serpapi.com/search.json"),
    ],
)
def test_serp_provider_config_applies_official_endpoint(provider: str, endpoint: str) -> None:
    config = normalized_config(provider, api_key="secret")

    assert config["endpoint"] == endpoint


def test_ark_requires_bot_model() -> None:
    with pytest.raises(ExternalSearchConfigError, match="Bot Model"):
        normalized_config("volc_ark", api_key="secret")


def test_api_key_with_non_ascii_is_rejected_with_readable_message() -> None:
    """误把中文内容粘进 API Key 时，要给出可读提示而不是 latin-1 codec 报错。"""
    with pytest.raises(ExternalSearchConfigError, match="API Key"):
        normalized_config("baidu_qianfan", api_key="使用MOGO_VERSION")


def test_endpoint_with_non_ascii_is_rejected() -> None:
    with pytest.raises(ExternalSearchConfigError, match="Endpoint"):
        normalized_config("serper", api_key="secret", endpoint="https://example.com/搜索")


def test_ascii_config_passes_encoding_check() -> None:
    config = normalized_config("baidu_qianfan", api_key="bce-v3/ALTAK-abc/123")

    assert config["api_key"] == "bce-v3/ALTAK-abc/123"
