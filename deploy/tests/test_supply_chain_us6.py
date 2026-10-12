"""022 US6 (T053) — 供应链安全集成测试。

覆盖四条验收线：

1. **高危 CVE 阻断构建** —— CI 必须包含 pip-audit / pnpm audit / trivy 扫描步骤，
   且失败即阻断；
2. **构建/部署权限分离** —— 发布 workflow 的作业级 ``permissions`` 必须收窄，
   promote 作业必须绑定 ``environment`` 触发环境审批；
3. **提交钩子阻止密钥** —— 钩子脚本与 CI 全量扫描都在位，且能真实识别
   密钥模式（用临时文件做正向验证）；
4. **容器非 root** —— 已由 ``deploy/tests/test_container_hardening.py``（US3/T029）
   覆盖，这里只做交叉引用断言，避免重复实现。

前三条是静态检查 + 脚本行为验证（不依赖 docker daemon 或网络，CI 上任何
平台可跑）。

用法::

    python -m pytest deploy/tests/test_supply_chain_us6.py -q
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

RELEASE_WF = WORKFLOWS / "container-release.yml"
QUALITY_WF = WORKFLOWS / "quality-gate.yml"

SECRETS_SCRIPT = REPO_ROOT / "scripts" / "check-secrets.sh"
HOOK = REPO_ROOT / ".githooks" / "pre-commit"
PINNING_SCRIPT = REPO_ROOT / "scripts" / "check_action_pinning.py"


def _read(path: Path) -> str:
    assert path.exists(), f"缺少文件：{path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. 高危 CVE 阻断构建
# ---------------------------------------------------------------------------


def test_pip_audit_blocks_high_cve_in_ci() -> None:
    """backend-quality 作业必须包含 pip-audit 步骤且失败即退出。"""
    text = _read(QUALITY_WF)
    assert "pip-audit" in text, "CI 缺少 pip-audit 依赖漏洞扫描（022 FR-25 / T046）"
    # 步骤必须有退出码传导，否则扫描失败不会阻断构建
    assert "pip-audit -r requirements.txt" in text, "pip-audit 未对 requirements.txt 扫描"
    # 扫描步骤必须位于测试步骤之前（依赖缺陷独立于代码缺陷）
    assert text.index("pip-audit -r requirements.txt") < text.index("- name: Run tests"), (
        "pip-audit 应在测试步骤之前运行"
    )


def test_pnpm_audit_blocks_high_in_ci() -> None:
    """前端依赖必须用 --audit-level high 阻断。"""
    text = _read(QUALITY_WF)
    # user-web 与 admin-web 各一处
    hits = [ln for ln in text.splitlines() if "pnpm audit" in ln]
    assert len(hits) >= 2, f"pnpm audit 步骤不足（找到 {len(hits)} 处）"
    assert any("--audit-level high" in h for h in hits), (
        "pnpm audit 未指定 --audit-level high，无法阻断高危"
    )


def test_trivy_scan_blocks_critical_and_high() -> None:
    """镜像扫描必须限定 CRITICAL/HIGH 且 exit-code 非 0。"""
    text = _read(RELEASE_WF) + _read(QUALITY_WF)
    assert "trivy-action" in text, "缺少 trivy 镜像扫描"
    assert 'exit-code: "1"' in text, "trivy 未设置 exit-code 1（扫描失败不阻断发布）"
    assert "CRITICAL,HIGH" in text or "severity: CRITICAL" in text, (
        "trivy 未限定 CRITICAL/HIGH 严重度"
    )
    # 已修复的 CVE 不阻断（否则无法推进补丁节奏）
    assert "ignore-unfixed" in text, "trivy 未设置 ignore-unfixed"


def test_provenance_and_sbom_emitted() -> None:
    """发布镜像必须产出 provenance 与 SBOM（022 FR-26 / T050）。"""
    text = _read(RELEASE_WF)
    assert "provenance: mode=max" in text, "构建未启用 provenance"
    assert "sbom: true" in text, "构建未启用 SBOM"
    assert "attest-build-provenance" in text, "缺少 provenance attestation 步骤"


def test_build_reproducibility_verified() -> None:
    """发布前必须做二次构建校验（QF-006 的供应链延伸）。"""
    text = _read(RELEASE_WF)
    assert "Verify build reproducibility" in text, "缺少构建可复现性校验"
    assert text.count("docker/build-push-action") >= 2, "应有构建与复现校验两次构建"


# ---------------------------------------------------------------------------
# 2. 构建 / 部署权限分离
# ---------------------------------------------------------------------------


def test_release_workflow_has_job_level_permissions() -> None:
    """发布 workflow 必须用作业级 permissions，而不是只靠顶层。"""
    text = _read(RELEASE_WF)
    # 顶层 permissions 存在但不够：必须每个发布作业单独收窄
    lines = text.splitlines()
    idx = next((i for i, ln in enumerate(lines) if ln.strip() == "permissions:"), None)
    assert idx is not None, "缺少顶层 permissions 声明"
    block = "\n".join(lines[idx:idx + 8])
    assert "contents: read" in block, "顶层 permissions 应包含 contents: read"
    # 作业级 permissions 至少 3 处（validate/plan/publish/promote）
    job_permissions = re.findall(r"^    permissions:\n", text, re.M)
    assert len(job_permissions) >= 3, (
        f"作业级 permissions 只有 {len(job_permissions)} 处，构建/部署未分离"
    )


def test_validate_and_plan_jobs_are_read_only() -> None:
    """校验与规划作业只读，不持有发布能力。"""
    text = _read(RELEASE_WF)
    for job in ("validate-release", "plan-release"):
        block = re.search(rf"^  {job}:\n(.*?)(?=^  [a-z][a-z-]*:|^  #|\Z)", text, re.M | re.S)
        assert block is not None, f"缺少作业 {job}"
        body = block.group(1)
        assert "packages: write" not in body, f"{job} 不应持有 packages: write"
        assert "id-token: write" not in body, f"{job} 不应持有 id-token: write"
        assert "contents: write" not in body, f"{job} 不应持有 contents: write"


def test_promote_job_requires_environment_approval() -> None:
    """promote（部署等价动作）必须绑定 environment 触发审批。"""
    text = _read(RELEASE_WF)
    block = re.search(r"^  promote-release:\n(.*?)(?=^  [a-z][a-z-]*:|\Z)", text, re.M | re.S)
    assert block is not None, "缺少 promote-release 作业"
    body = block.group(1)
    assert re.search(r"^\s+environment:\s+\S+", body, re.M), (
        "promote-release 未绑定 environment，无法强制人工审批"
    )


def test_promote_only_runs_on_tag_push() -> None:
    """promote 只应在 tag push 时执行，workflow_dispatch 不得绕过。"""
    text = _read(RELEASE_WF)
    block = re.search(r"^  promote-release:\n(.*?)(?=^  [a-z][a-z-]*:|\Z)", text, re.M | re.S)
    body = block.group(1)
    assert "github.event_name == 'push'" in body, (
        "promote-release 未在 if 条件中限定 push 事件"
    )


def test_build_job_cannot_write_contents() -> None:
    """构建作业不得持有 contents: write（无法推 tag / 改 workflow 绕过审批）。"""
    text = _read(RELEASE_WF)
    block = re.search(
        r"^  publish-candidates:\n(.*?)(?=^  [a-z][a-z-]*:|\Z)", text, re.M | re.S
    )
    body = block.group(1)
    assert "contents: write" not in body, (
        "publish-candidates 持有 contents: write，可绕过环境审批"
    )
    assert "packages: write" in body, "publish-candidates 需要 packages: write 推送镜像"
    assert "id-token: write" in body, "publish-candidates 需要 id-token: write 换取 GHCR 凭据"


# ---------------------------------------------------------------------------
# 3. 提交钩子阻止密钥
# ---------------------------------------------------------------------------


def test_secrets_script_exists_and_is_executable() -> None:
    assert SECRETS_SCRIPT.exists(), "缺少 scripts/check-secrets.sh"
    assert os.access(SECRETS_SCRIPT, os.X_OK), "check-secrets.sh 未设可执行位"
    assert (REPO_ROOT / ".githooks").is_dir(), "缺少 .githooks/"
    assert HOOK.exists(), "缺少 .githooks/pre-commit"
    assert os.access(HOOK, os.X_OK), "pre-commit 未设可执行位"


def _run_secrets_check(content: str, tmp_path: Path) -> subprocess.CompletedProcess:
    """在临时文件上运行钩子脚本（非 git 上下文，直接按路径模式匹配）。"""
    target = tmp_path / "leak.py"
    target.write_text(content, encoding="utf-8")
    return subprocess.run(
        [str(SECRETS_SCRIPT), str(target)],
        capture_output=True, text=True, timeout=30,
    )


# 测试固件：用**构造器**生成匹配 pattern 的值，而不是硬编码看起来像真密钥的
# 字符串。GitHub 服务端 secret scanning 会阻断包含硬编码密钥样例的提交，
# 因此测试数据在运行时构造 —— 既保证 pattern 被真实验证，又不在版本库里
# 留下可被扫描器命中的字面量。
_PATTERNS: list[tuple[str, str]] = [
    ("aws-secret", "aws_secret_access_key = '{}'"),
    ("aws-access-key-id", "AKIA" + "A" * 16),
    ("pem-private-key", "-----BEGIN RSA PRIVATE KEY-----" + "MIIE" + "p" * 20),
    ("github-pat", "ghp_" + "a" * 36),
    ("stripe-live-key", "sk_live_" + "1" * 24),
    ("long-password", "password = '{}'"),
]


@pytest.mark.parametrize("payload_id,template", _PATTERNS, ids=[p[0] for p in _PATTERNS])
def test_secrets_script_detects_known_patterns(
    payload_id: str, template: str, tmp_path: Path
) -> None:
    """钩子必须识别各类密钥模式（正向验证）。"""
    if payload_id == "aws-secret":
        payload = template.format("a" * 40)
    elif payload_id == "long-password":
        payload = template.format("a" * 30)
    else:
        payload = template
    result = _run_secrets_check(payload, tmp_path)
    assert result.returncode == 1, (
        f"未拦截密钥（{payload_id}）：\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_secrets_script_allows_clean_code(tmp_path: Path) -> None:
    """干净代码不应误报。"""
    clean = textwrap.dedent(
        """\
        import os

        # 从环境变量读取密钥，不在源码里硬编码
        JWT_SECRET = os.environ.get("JWT_SECRET", "")
        DB_URI = os.environ["MONGODB_URI"]


        def connect():
            return f"connecting with secret={bool(JWT_SECRET)}"
        """
    )
    result = _run_secrets_check(clean, tmp_path)
    assert result.returncode == 0, (
        f"干净代码被误报：\n{result.stderr}"
    )


def test_ci_runs_full_secrets_scan() -> None:
    """CI 必须跑 --all 全量扫描（钩子只覆盖提交范围）。"""
    text = _read(QUALITY_WF)
    assert "check-secrets.sh --all" in text, "CI 缺少全量密钥扫描步骤"


def test_precommit_hook_delegates_to_script() -> None:
    """钩子应委托给脚本而不是自己实现逻辑（单一事实来源）。"""
    text = _read(HOOK)
    assert "check-secrets.sh" in text, "pre-commit 未调用 check-secrets.sh"
    # 紧急绕过开关存在但不默认启用
    assert "SKIP_SECRETS_CHECK" in text, "缺少紧急绕过开关"


# ---------------------------------------------------------------------------
# 2. 豁免通道：行级标记 + 任意层级路径白名单
# ---------------------------------------------------------------------------
#
# 高置信模式 `(secret|password|passwd|token|api[_-]?key)\s*[:=]\s*\S{20,}`
# 必然会把「赋值给标识符 / 函数调用」算作候选，例如
# `signing_secret = resolve_local_file_signing_secret(`。路径白名单管不到单行，
# 而收紧 pattern 会同时削弱对真实密钥的检出——那是不可接受的取舍。
#
# 所以脚本提供两条**都不放宽 pattern** 的豁免通道：
#   1. 路径级 ALLOWLIST_PATHS（任意层级目录名匹配）
#   2. 行级 LINE_ALLOWLIST_MARKER（精确到单行）
# 下面把两条都钉住，防止它们被无意中削弱。

LINE_ALLOWLIST_MARKER = "pragma: allowlist secret"

# 已登记的误报行所在文件：它们必须带行级豁免标记，否则 `--all` 立刻变红。
KNOWN_FALSE_POSITIVE_FILES = [
    "dev_dsh.sh",
    "services/admin-api/app/api/routes/directory.py",
    "services/admin-api/app/core/config.py",
    "services/chat-api/app/api/endpoints/documents.py",
    "services/chat-api/app/enterprise_capabilities/content/writer_engine/compose_skill.py",
    "services/chat-api/app/enterprise_capabilities/evidence/foundation/external_web_raw.py",
    "services/chat-api/app/governance/suspensions/resume_admission.py",
    "services/chat-api/dsh/runtime-host/scripts/runtime-inventory-probe.mjs",
    "services/document-parser/app/services/model_center_runtime.py",
]


def _scan_path(path: Path) -> int:
    return subprocess.run(
        [str(SECRETS_SCRIPT), str(path)],
        capture_output=True, text=True, timeout=60,
    ).returncode


def test_secrets_script_supports_line_allowlist_marker(tmp_path: Path) -> None:
    """行尾标记必须精确豁免该行。"""
    payload = "password = '" + "a" * 30 + "'"

    unmarked = tmp_path / "unmarked.py"
    unmarked.write_text(payload + "\n", encoding="utf-8")
    marked = tmp_path / "marked.py"
    marked.write_text(payload + f"  # {LINE_ALLOWLIST_MARKER}\n", encoding="utf-8")

    assert _scan_path(unmarked) == 1, "未标记的密钥赋值必须被拦下"
    assert _scan_path(marked) == 0, "带行级豁免标记的行不应被拦下"


def test_secrets_allowlist_matches_nested_directories(tmp_path: Path) -> None:
    """`tests/` 这类目录名必须按任意层级匹配，而不是只匹配仓库根。"""
    payload = "JWT_SECRET = '" + "b" * 30 + "'\n"

    nested = tmp_path / "services" / "admin-api" / "tests" / "fixture.py"
    nested.parent.mkdir(parents=True)
    nested.write_text(payload, encoding="utf-8")

    plain = tmp_path / "app" / "leak.py"
    plain.parent.mkdir(parents=True)
    plain.write_text(payload, encoding="utf-8")

    assert _scan_path(nested) == 0, "嵌套的 tests/ 目录必须被豁免"
    assert _scan_path(plain) == 1, "非豁免目录里的同一内容仍必须被拦下"


def test_secrets_allowlist_registers_fixture_and_doc_directories() -> None:
    """测试固件、文档、生成物必须登记在 ALLOWLIST_PATHS，而不是靠放宽 pattern。"""
    text = _read(SECRETS_SCRIPT)
    for entry in (
        '"tests/"',
        '"specs/"',
        '"scripts/dev/"',
        '"docs/"',
        '"node_modules/"',
        '"pnpm-lock.yaml"',
        '"versions.lock"',
    ):
        assert entry in text, f"ALLOWLIST_PATHS 缺少 {entry}"


def _scan_all(path: Path) -> str:
    """`--all` 模式下的完整输出（低置信提示只在该模式下、且走 stderr）。"""
    result = subprocess.run(
        [str(SECRETS_SCRIPT), "--all", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    return result.stdout + result.stderr


def test_low_confidence_pattern_ignores_long_identifier_names(tmp_path: Path) -> None:
    """40+ 字符的**变量名**不是随机串，不应触发低置信提示。

    旧写法 `[A-Za-z0-9_\\-]{40,}==?` 里 `==?` 读作「一个**必选** `=` + 一个可选
    `=`」，于是该模式实际只匹配「长名字 + `=`」：`.env.example`、compose、
    部署模板里的长 KEY 名全部被误报，而真正的长值（不带 base64 填充）反而漏掉。
    """
    name = "ASKAI_ADMIN_TENANT_BOOTSTRAP_ADMIN_ENABLED"
    assert len(name) >= 40, "用例前提：名字本身要够长"
    target = tmp_path / "settings.env.example"
    target.write_text(f"{name}=false\n", encoding="utf-8")

    out = _scan_all(target)
    assert "低置信" not in out, f"长变量名不应触发低置信提示：\n{out}"


def test_low_confidence_pattern_flags_padded_long_values(tmp_path: Path) -> None:
    """值位置 + base64 填充的长随机串仍必须被提示（本通道不能变成死代码）。

    键名刻意选一个不在高置信关键词表（secret/password/token/api_key…）里的词，
    这样命中的只可能是低置信通道。
    """
    value = "aB3xZ9qL7mN2pR5tY8uI4oP6sD1fG0hJ2kM9nB4vC7xZ3q=="
    target = tmp_path / "payload.txt"
    target.write_text(f'blob = "{value}"\n', encoding="utf-8")

    out = _scan_all(target)
    assert "低置信" in out, f"值位置的长随机串应触发低置信提示：\n{out}"
    # 低置信通道是提示性的：不得出现阻断标记 `✗ 疑似密钥`。
    assert "✗ 疑似密钥" not in out, "低置信通道不应阻断"


@pytest.mark.parametrize("rel", KNOWN_FALSE_POSITIVE_FILES)
def test_known_false_positive_lines_carry_the_marker(rel: str) -> None:
    """钉住已登记的误报行：标记被删掉时全量扫描会立刻变红。"""
    text = _read(REPO_ROOT / rel)
    assert LINE_ALLOWLIST_MARKER in text, (
        f"{rel} 缺少行级豁免标记 {LINE_ALLOWLIST_MARKER!r}；"
        "删除它会让 scripts/check-secrets.sh --all 重新变红"
    )


def test_action_pinning_policy_is_enforced() -> None:
    """发布关键 action 必须 SHA 固定的政策已被脚本化并接入 CI。"""
    assert PINNING_SCRIPT.exists(), "缺少 scripts/check_action_pinning.py"
    text = _read(QUALITY_WF)
    assert "check_action_pinning.py" in text, "CI 未接入 action pinning 检查"

    result = subprocess.run(
        [sys.executable, str(PINNING_SCRIPT), "--json"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"存在未固定到 SHA 的发布关键 action：\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# 4. 容器非 root（交叉引用 US3）
# ---------------------------------------------------------------------------


def test_container_hardening_tests_present() -> None:
    """容器非 root 已由 US3 覆盖，这里只断言测试文件仍在（防回归）。"""
    hardening = REPO_ROOT / "deploy" / "tests" / "test_container_hardening.py"
    assert hardening.exists(), (
        "缺少 deploy/tests/test_container_hardening.py（US3/T029 容器非 root 覆盖）"
    )
    text = hardening.read_text(encoding="utf-8")
    # 关键断言点：4 个应用镜像 + compose 加固参数
    assert "USER" in text or "uid" in text.lower(), "容器非 root 测试缺少 USER/uid 断言"
    assert "no-new-privileges" in text, "容器加固测试缺少 no-new-privileges 断言"
    assert "cap_drop" in text, "容器加固测试缺少 cap_drop 断言"
