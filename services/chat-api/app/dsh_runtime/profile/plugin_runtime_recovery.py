"""Isolate a broken optional plugin before MOGO retries Runtime creation."""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import uuid4

from app.dsh_runtime.errors import DshTransportError
from app.dsh_runtime.transport import KernelHostTransport


logger = logging.getLogger(__name__)


async def profile_without_unavailable_plugins(
    transport: KernelHostTransport, payload: dict[str, Any], failure: DshTransportError,
) -> dict[str, Any]:
    profile = payload.get("modelProfile")
    plugins = profile.get("plugins") if isinstance(profile, dict) else None
    message = str(failure).lower()
    install_failure = "plugin" in message and bool(re.search(r"failed to (install|load|activate)", message))
    if not isinstance(plugins, list) or not plugins or not install_failure:
        raise failure

    available: list[dict[str, Any]] = []
    for plugin in plugins:
        if not isinstance(plugin, dict):
            raise failure
        probe_id = uuid4().hex
        probe_profile = {**profile, "plugins": [plugin]}
        probe_payload = {
            **payload,
            "isolationKey": f"plugin-runtime-probe:{probe_id}",
            "profileVersion": f"plugin-runtime-probe:{probe_id}",
            "modelProfile": {**probe_profile, "profileVersion": f"plugin-runtime-probe:{probe_id}"},
        }
        try:
            probe = await transport.request("POST", "/v1/runtimes", json=probe_payload)
        except DshTransportError as error:
            logger.warning("optional_plugin_runtime_unavailable name=%s error=%s", plugin.get("name"), error)
            continue
        try:
            available.append(plugin)
        finally:
            await transport.request("DELETE", f"/v1/runtimes/{probe['runtimeId']}")

    if len(available) == len(plugins):
        raise failure
    logger.warning(
        "runtime_profile_optional_plugins_omitted profile=%s requested=%d available=%d",
        payload.get("profileVersion"), len(plugins), len(available),
    )
    return {**payload, "modelProfile": {**profile, "plugins": available}}
