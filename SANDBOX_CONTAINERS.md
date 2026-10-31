# Container isolation (sandbox)

> 状态：本特性对应 himovo/movo 的 sandbox 容器隔离，本地 mogo 目前处于 **P1 移植阶段，默认未启用**。本文档由 himovo/movo 的 `SANDBOX_CONTAINERS.md` 改写而来，品牌词已按本地约定（`MOGO` / `./mogo` / `MOGO_*`）替换。启用前请先完成 P1 移植（sandbox-manager / sandbox-egress / chat-api execution_isolation）。

MOGO can run governed scripts in one-shot containers and DSH plugins in separate per-profile Runtime containers. The feature is optional during rollout; the existing execution path remains in use until it is enabled. Docker Engine 26 or newer is required for per-job volume subpaths.

## Enable

Add these lines to the deployment `.env` file, then run `./mogo up --build` for a source deployment or `./mogo update` once the sandbox images have been published:

```dotenv
COMPOSE_PROFILES=sandbox
MOGO_SANDBOX_MANAGER_URL=http://sandbox-manager:8300
MOGO_SANDBOX_MAX_CONCURRENT=2
MOGO_SANDBOX_MAX_PENDING=8
MOGO_SANDBOX_PLUGIN_IDLE_SECONDS=900
```

The manager and egress proxy run as separate Compose services. The manager alone has access to the Docker socket. Script jobs receive a private workspace and internal Docker network. Plugin Runtime containers receive storage scoped to their Runtime isolation key. Network egress is available through the proxy, which rejects private and local destinations. Admin → Settings → Sandbox containers shows current health and counts.

The script concurrency setting limits active one-shot containers. Requests beyond the limit wait up to 20 seconds, with at most `MOGO_SANDBOX_MAX_PENDING` queued. Administrators can adjust the queue limit in Settings; the saved value persists across manager restarts. The concurrency limit remains a deployment setting. A plugin Runtime is reclaimed after the idle timeout; its session storage remains available for the next turn. The first turn after reclamation must start a new container and may take several seconds.

## Packaged Skills

MOGO accepts a Skill ZIP with one `SKILL.md` and up to 20,000 files, 100 MiB compressed, and 200 MiB expanded. A repository ZIP may place the sole Skill in a deeper directory; MOGO keeps only that Skill subtree and stores a canonical ZIP. An invoked Skill's package is cached by its content digest. Each script job mounts that package read-only under `/job/skills` and receives a separate writable `/job` directory. Script code can use `skill_dir` for the exact package root and `output_dir` for files that should be delivered to the user. Packages with dependency manifests are extracted when installed so dependency preparation can begin in the background; packages without manifests are extracted on first execution. Subsequent jobs reuse the cached read-only copy.

The DSH text resource reader caches the compressed archive and extracts only the requested UTF-8 entry. Reading Skill instructions does not unpack thousands of templates into the Runtime Host. This cache is separate from the script execution cache because the two components use different volumes.

The sandbox script base image provides Python, pip, Node.js, npm, and the backend's existing Python libraries. A Skill may declare root-level `requirements.txt`, `package.json` with `package-lock.json`, and `apt-packages.txt` (one Debian package name per line). After installation, MOGO starts an isolated dependency build in the background. The resulting image is reused by Skill archive digest and base-image ID; ordinary script jobs never install packages. The installer shows preparation progress and failure. A call made before preparation finishes waits briefly and then reports that preparation is still in progress. Large dependency sets can take several minutes to prepare, depending on download speed; normal calls after preparation do not repeat installation. `./mogo --mirror cn up` and `update` select Chinese package registries for future Skill dependency builds; the default launcher selects official registries. A download timeout or connection failure retries once from the alternate registries in a fresh build container. Package conflicts and install-script failures do not trigger a source switch. Explicit `MOGO_PIP_INDEX_URL`, `MOGO_APT_MIRROR`, and `MOGO_NPM_REGISTRY` values take precedence over the selected primary source. Packages that run install hooks execute only inside the disposable dependency build container, without user files or a Docker socket. Reinstalling the same ZIP retries a failed preparation.

Dependency manifests must be part of the trusted Skill ZIP. Dependencies mentioned only in prose cannot be inferred reliably. Native tools that do not expose a Debian package still require an operator-controlled base image selected with `MOGO_SANDBOX_SCRIPT_IMAGE`.

Do not mount the Docker socket into the chat API, the DSH Host, or the job containers. The manager creates containers from fixed images and commands; requests cannot supply arbitrary Docker configuration.
