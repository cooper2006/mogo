#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts/release/mirror_container_release.sh"


class ContainerMirrorTests(unittest.TestCase):
    def run_mirror(self, *, publish_latest: bool, include_dependencies: bool):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            call_log = temporary_path / "docker-calls.log"
            docker = temporary_path / "docker"
            docker.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"$DOCKER_CALL_LOG\"\n"
                "if [[ \"$*\" == *'imagetools inspect --raw'* ]]; then\n"
                "  printf '%s\\n' '{\"schemaVersion\":2,\"manifests\":['"
                "'{\"digest\":\"sha256:amd64\",\"platform\":{\"os\":\"linux\",\"architecture\":\"amd64\"}},'"
                "'{\"digest\":\"sha256:arm64\",\"platform\":{\"os\":\"linux\",\"architecture\":\"arm64\"}},'"
                "'{\"digest\":\"sha256:attestation\",\"platform\":{\"os\":\"unknown\",\"architecture\":\"unknown\"}}]}'\n"
                "fi\n"
            )
            docker.chmod(0o755)
            env = os.environ | {
                "CN_REGISTRY_HOST": "registry.example.cn",
                "CN_REGISTRY_NAMESPACE": "himovo",
                "SOURCE_REPOSITORY": "ghcr.io/himovo/movo",
                "SOURCE_VERSION": "v1.2.3",
                "PUBLISH_LATEST": str(publish_latest).lower(),
                "INCLUDE_DEPENDENCIES": str(include_dependencies).lower(),
                "DOCKER_CALL_LOG": str(call_log),
                "DOCKER_BIN": str(docker),
            }
            subprocess.run(
                ["bash", str(SCRIPT)],
                check=True,
                env=env,
                stdout=subprocess.PIPE,
                text=True,
            )
            return call_log.read_text().splitlines()

    def test_preflights_all_sources_before_copying(self):
        calls = self.run_mirror(publish_latest=False, include_dependencies=True)
        source_count = 11
        self.assertEqual(source_count * 3, len(calls))
        self.assertTrue(
            all("imagetools inspect" in call for call in calls[:source_count])
        )
        self.assertTrue(
            all("imagetools create" in call for call in calls[source_count : source_count * 2])
        )
        version_copy_calls = calls[source_count : source_count * 2]
        self.assertTrue(
            all("@sha256:amd64" in call and "@sha256:arm64" in call for call in version_copy_calls)
        )
        self.assertTrue(all("sha256:attestation" not in call for call in version_copy_calls))
        self.assertTrue(
            all("imagetools inspect" in call for call in calls[source_count * 2 :])
        )
        self.assertTrue(any("docker.io/library/mongo:6.0.20" in call for call in calls))
        self.assertTrue(
            any("registry.example.cn/himovo/movo-mongo:6.0.20" in call for call in calls)
        )

    def test_latest_is_published_only_after_version_verification(self):
        calls = self.run_mirror(publish_latest=True, include_dependencies=False)
        version_verification_end = 21
        latest_calls = calls[version_verification_end : version_verification_end + 7]
        latest_verifications = calls[version_verification_end + 7 :]
        self.assertEqual(35, len(calls))
        self.assertTrue(all(":latest" in call for call in latest_calls))
        self.assertTrue(all("imagetools create" in call for call in latest_calls))
        self.assertTrue(all(":latest" in call for call in latest_verifications))
        self.assertTrue(
            all("imagetools inspect" in call for call in latest_verifications)
        )

    def test_release_mirrors_only_after_ghcr_promotion(self):
        release_workflow = (
            REPOSITORY_ROOT / ".github/workflows/container-release.yml"
        ).read_text()
        mirror_workflow = (
            REPOSITORY_ROOT / ".github/workflows/container-mirror-cn.yml"
        ).read_text()
        self.assertIn("mirror-cn:\n    needs: promote-release", release_workflow)
        self.assertIn("uses: ./.github/workflows/container-mirror-cn.yml", release_workflow)
        self.assertIn("workflow_dispatch:", mirror_workflow)
        self.assertIn("secrets.CN_REGISTRY_PASSWORD", mirror_workflow)
        self.assertIn("Verify public anonymous pulls", mirror_workflow)


if __name__ == "__main__":
    unittest.main()
