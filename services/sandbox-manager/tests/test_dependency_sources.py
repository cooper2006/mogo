from app.dependency_sources import build_attempts, retryable_failure, source_attempts


def test_china_deployment_uses_china_then_global(monkeypatch):
    monkeypatch.setenv("MOGO_DEPENDENCY_MIRROR", "cn")
    monkeypatch.delenv("MOGO_PIP_INDEX_URL", raising=False)
    monkeypatch.delenv("MOGO_NPM_REGISTRY", raising=False)
    monkeypatch.delenv("MOGO_APT_MIRROR", raising=False)
    attempts = source_attempts()
    assert [item.name for item in attempts] == ["cn", "global"]
    assert attempts[0].pip_index == "https://mirrors.aliyun.com/pypi/simple"
    assert attempts[0].apt_mirror == "https://mirrors.aliyun.com"


def test_global_deployment_uses_global_then_china(monkeypatch):
    monkeypatch.setenv("MOGO_DEPENDENCY_MIRROR", "global")
    monkeypatch.delenv("MOGO_PIP_INDEX_URL", raising=False)
    monkeypatch.delenv("MOGO_NPM_REGISTRY", raising=False)
    monkeypatch.delenv("MOGO_APT_MIRROR", raising=False)
    assert [item.name for item in source_attempts()] == ["global", "cn"]


def test_custom_source_takes_precedence(monkeypatch):
    monkeypatch.setenv("MOGO_DEPENDENCY_MIRROR", "cn")
    monkeypatch.setenv("MOGO_PIP_INDEX_URL", "https://internal.example/simple")
    monkeypatch.delenv("MOGO_NPM_REGISTRY", raising=False)
    monkeypatch.delenv("MOGO_APT_MIRROR", raising=False)
    attempts = source_attempts()
    assert attempts[0].pip_index == "https://internal.example/simple"
    assert attempts[0].npm_registry == "https://registry.npmmirror.com"
    assert attempts[1].pip_index == "https://pypi.org/simple"


def test_only_transport_failures_trigger_fallback():
    assert retryable_failure("subprocess.TimeoutExpired: pip timed out after 240 seconds")
    assert retryable_failure("npm ERR! code EAI_AGAIN")
    assert not retryable_failure("No matching distribution found for package==99")
    assert not retryable_failure("package.json requires a package-lock.json")


def test_extra_attempts_are_bounded_and_follow_source_order(monkeypatch):
    monkeypatch.setenv("MOGO_DEPENDENCY_MIRROR", "cn")
    monkeypatch.setenv("MOGO_SKILL_DEPENDENCY_RETRIES", "9")
    assert [source.name for source in build_attempts()] == ["cn", "global", "cn", "global"]
    monkeypatch.setenv("MOGO_SKILL_DEPENDENCY_RETRIES", "0")
    assert [source.name for source in build_attempts()] == ["cn", "global"]
