import asyncio
import base64
import json

import httpx

from app.llm.image_json_protocol import build_image_payload, response_value
from app.services.image_generation import ConfiguredImageGenerationService


def test_payload_omits_empty_optional_fields_and_merges_nested_extra_params():
    payload = build_image_payload(
        model="agnes-image-2.5-flash",
        prompt="draw a cover",
        settings={
            "size": "2K",
            "ratio": "16:9",
            "quality": "",
            "extra_params": {"extra_body": {"response_format": "url"}},
        },
    )

    assert payload == {
        "model": "agnes-image-2.5-flash",
        "prompt": "draw a cover",
        "size": "2K",
        "ratio": "16:9",
        "extra_body": {"response_format": "url"},
    }


def test_response_value_supports_object_and_array_paths():
    assert response_value({"data": [{"url": "https://example.com/a.png"}]}, "data.0.url") == "https://example.com/a.png"
    assert response_value({"data": []}, "data.0.url") is None


def test_custom_image_request_uses_configured_path_and_response_mapping(monkeypatch):
    captured = {}
    image_bytes = b"custom-image"

    def respond(request):
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"result": {"image": base64.b64encode(image_bytes).decode()}})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        "app.services.image_generation.httpx.AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = asyncio.run(ConfiguredImageGenerationService()._generate_with_openai_config(
        config={"base_url": "https://images.example/v1", "api_key": "test", "model_name": "custom-image"},
        settings={
            "request_path": "/generate",
            "size": "2K",
            "response_base64_path": "result.image",
            "response_url_path": "result.url",
        },
        prompt="cover",
        size=None,
        quality=None,
        output_format=None,
        timeout_seconds=None,
        model_source="admin_config",
        runtime_kind="custom_images",
    ))

    assert result.image_bytes == image_bytes
    assert captured == {
        "url": "https://images.example/v1/generate",
        "payload": {"model": "custom-image", "prompt": "cover", "size": "2K"},
    }
