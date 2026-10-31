"""Build and reuse isolated dependency images for immutable Skill bundles."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from pathlib import Path
from uuid import uuid4

from .docker_engine import DockerEngine, split_docker_logs
from .dependency_sources import build_attempts, retryable_failure


LOG = logging.getLogger(__name__)


class DependencyPreparationError(RuntimeError):
    pass


class SkillEnvironments:
    def __init__(self, engine: DockerEngine) -> None:
        self.engine = engine
        self.root = Path(os.environ.get("MOGO_SANDBOX_WORKSPACE_ROOT", "/workspaces")) / "skill-cache"
        self.volume = os.environ["MOGO_SANDBOX_WORKSPACE_VOLUME"]
        self.base_image = os.environ["MOGO_SANDBOX_SCRIPT_IMAGE"]
        self.project = os.environ.get("MOGO_SANDBOX_COMPOSE_PROJECT", "mogo")
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mogo-skill-deps")
        self.lock = threading.Lock()
        self.pending: dict[str, Future[str]] = {}

    def _skill_root(self, digest: str) -> Path:
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("Invalid Skill digest")
        bundle = self.root / digest
        roots = [path.parent for path in bundle.glob("SKILL.md")]
        roots.extend(path.parent for path in bundle.glob("*/SKILL.md"))
        if len(roots) != 1:
            raise ValueError("Skill package root is missing or ambiguous")
        return roots[0]

    def _image_name(self, digest: str) -> str | None:
        root = self._skill_root(digest)
        if not any((root / name).is_file() for name in (
            "requirements.txt", "package.json", "apt-packages.txt",
        )):
            return None
        base_id = self.engine.image_id(self.base_image)
        if not base_id:
            raise ValueError("Sandbox script base image is missing")
        key = hashlib.sha256(f"{base_id}:{digest}".encode()).hexdigest()[:40]
        return f"mogo-skill-deps:{key}"

    def start(self, digest: str, *, retry_failed: bool = False) -> str:
        image = self._image_name(digest)
        if image is None:
            return "not_required"
        if self.engine.image_id(image):
            return "ready"
        with self.lock:
            existing = self.pending.get(image)
            if existing is None or (retry_failed and existing.done() and existing.exception()):
                existing = self.pool.submit(self._build, digest, image)
                self.pending[image] = existing
        return "failed" if existing.done() and existing.exception() else "preparing"

    def ready_image(self, digest: str, timeout: float = 5) -> str:
        image = self._image_name(digest)
        if image is None:
            return self.base_image
        if self.engine.image_id(image):
            return image
        self.start(digest)
        with self.lock:
            future = self.pending[image]
        try:
            return future.result(timeout=timeout)
        except TimeoutError as exc:
            raise DependencyPreparationError("Skill dependencies are still preparing; retry shortly") from exc
        except Exception as exc:
            raise DependencyPreparationError(
                "Skill dependency preparation failed; check sandbox manager logs"
            ) from exc

    def status(self, digest: str) -> str:
        image = self._image_name(digest)
        if image is None:
            return "not_required"
        if self.engine.image_id(image):
            return "ready"
        with self.lock:
            future = self.pending.get(image)
        if future is None:
            # A manager restart loses in-memory futures, but the cached bundle
            # survives. Resume preparation when the installer polls again.
            return self.start(digest)
        return "failed" if future.done() and future.exception() else "preparing"

    def _build(self, digest: str, image: str) -> str:
        lease = uuid4().hex
        network_id = proxy_id = None
        deadline = time.monotonic() + self._build_timeout()
        try:
            proxy_id = self.engine.find_compose_service(self.project, "sandbox-egress")
            network_id = self.engine.create_internal_network(f"mogo-deps-{lease}")
            self.engine.connect_network(network_id, proxy_id, ["sandbox-egress"])
            environment = [
                "HOME=/tmp",
                "HTTP_PROXY=http://sandbox-egress:3128",
                "HTTPS_PROXY=http://sandbox-egress:3128",
                "http_proxy=http://sandbox-egress:3128",
                "https_proxy=http://sandbox-egress:3128",
                "PIP_DISABLE_PIP_VERSION_CHECK=1",
                f"MOGO_SKILL_DEPENDENCY_STEP_TIMEOUT={self._step_timeout()}",
            ]
            payload = {
                "Image": self.base_image,
                "User": "0:0",
                "Entrypoint": ["python"],
                "Cmd": ["/opt/mogo-sandbox/prepare_skill.py"],
                "WorkingDir": "/tmp",
                "Env": environment,
                "HostConfig": {
                    "NetworkMode": network_id,
                    "CapDrop": ["ALL"],
                    "CapAdd": ["CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID"],
                    "SecurityOpt": ["no-new-privileges:true"],
                    "PidsLimit": 256,
                    "Memory": 2 * 1024 * 1024 * 1024,
                    "NanoCpus": 2_000_000_000,
                    "Mounts": [{
                        "Type": "volume", "Source": self.volume, "Target": "/skill",
                        "ReadOnly": True,
                        "VolumeOptions": {"Subpath": str(self._skill_root(digest).relative_to(self.root.parent)), "NoCopy": True},
                    }],
                },
                "Labels": {"mogo.role": "skill-dependency-build", "mogo.skill_digest": digest},
            }
            sources = build_attempts()
            for index, source in enumerate(sources):
                container_id = None
                try:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Skill dependency preparation exceeded its total time limit")
                    payload["Env"] = environment + source.environment()
                    container_id = self.engine.create(f"mogo-deps-{lease}-{index}", payload)
                    self.engine.start(container_id)
                    exit_code = self.engine.wait(container_id, remaining)
                    if exit_code == 0:
                        self.engine.commit(container_id, "mogo-skill-deps", image.rsplit(":", 1)[1])
                        return image
                    stdout, stderr = split_docker_logs(self.engine.logs(container_id))
                    detail = (stderr or stdout)[-4000:].decode(errors="replace")
                    if index < len(sources) - 1 and retryable_failure(detail):
                        LOG.warning("Skill dependency source %s failed; retrying with %s for %s: %s", source.name, sources[index + 1].name, digest, detail)
                        continue
                    raise RuntimeError(f"Skill dependency installation failed using {source.name}: {detail}")
                finally:
                    if container_id:
                        self.engine.remove(container_id)
            raise RuntimeError("Skill dependency installation failed after all sources")
        except Exception:
            LOG.exception("Skill dependency build failed for %s", digest)
            raise
        finally:
            if network_id:
                if proxy_id:
                    self.engine.disconnect_network(network_id, proxy_id)
                self.engine.remove_network(network_id)

    @staticmethod
    def _step_timeout() -> int:
        return SkillEnvironments._bounded_timeout("MOGO_SKILL_DEPENDENCY_STEP_TIMEOUT", 480, 60, 1200)

    @staticmethod
    def _build_timeout() -> int:
        return SkillEnvironments._bounded_timeout("MOGO_SKILL_DEPENDENCY_BUILD_TIMEOUT", 1800, 300, 3600)

    @staticmethod
    def _bounded_timeout(name: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(os.environ.get(name, str(default)))
        except ValueError:
            value = default
        return max(minimum, min(value, maximum))
