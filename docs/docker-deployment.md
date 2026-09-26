# Docker deployment

## Install from GitHub Container Registry

Clone the GitHub repository at a release tag and run:

```bash
git clone --branch vX.Y.Z https://github.com/himovo/movo.git
cd movo
./movo up
```

Both `./movo up` and `docker compose up -d` pull the seven official MOVO images
from `ghcr.io/himovo/movo-*` by default. Neither command requires an `.env`
file. The MOVO launcher pulls images sequentially and keeps retrying registry
failures until they succeed or the user presses `Ctrl+C`; native Compose retains
Docker's default parallel pull behavior.

Windows users should follow the [Windows installation guide](windows-installation.md)
and run the launcher from Ubuntu WSL or Git Bash. The Docker Desktop internal
`docker-desktop` distribution is not a user shell and does not include the Bash
environment required by `./movo`.

To pin a production deployment to the checked-out release, set:

```env
MOVO_VERSION=vX.Y.Z
```

Do not use `latest` for a production deployment. Upgrade only after reading the
release notes, taking a backup and confirming the rollback image tag.

## Build from source

For development or before public images are available:

```bash
./movo up --build
```

This loads `docker-compose.build.yml` in addition to the default Compose file.
It downloads and builds Playwright, LibreOffice, Docling and model assets, so it
needs substantially more time and disk space than the prebuilt-image path.

To build without starting services:

```bash
./movo build
```

Both build paths reuse the base images already present in the local Docker
store (for example the ones OrbStack has cached) and reach the registry only
for base images that are genuinely missing. This keeps a rebuild that changed
only application code off the network. `MOVO_BASE_IMAGE_POLICY` changes that
behaviour:

| Value | Behaviour |
| --- | --- |
| `reuse` (default) | Use local base images; pull only what is missing |
| `pull` | Always refresh base images from the registry |
| `local` | Never use the network; fail when a base image is missing |

The distro security refresh (`apt-get upgrade` / `apk upgrade`) is off by
default so its layer stays cacheable: a rebuild that changed only application
code then reuses the cached dependency installation instead of downloading
everything again. The release workflow sets `MOVO_SECURITY_REFRESH` to its run
id, which re-enables the refresh for published images. To apply the patches to
a local build as well, pass a non-empty value:

```bash
MOVO_SECURITY_REFRESH=1 ./movo build
```

### Moving base images to another machine

To build on a host without registry access, export the base images from a
machine that already has them and import the archives on the target:

```bash
# On the machine that has the images
scripts/export_base_images.sh save ./base-images
# Copy the directory across, then on the target
scripts/export_base_images.sh load ./base-images
```

`save` writes one `.tar` per image plus a `manifest.txt` recording the exported
platform. The image set is derived from the build Dockerfiles, so it always
matches the current requirements. Export fails before writing anything when an
image is missing locally, which prevents a silently incomplete set; run
`./movo build` first to fetch it. `load` warns when the archives were exported
for a different architecture than the target, and `scripts/export_base_images.sh
list` shows which required images are present locally.

## Operations

```bash
./movo status
./movo logs chat-api
./movo restart
./movo update
./movo backup /path/on/a/large-disk/movo-backup
./movo down
```

`./movo update` pulls the configured image tag and recreates services. Pin a new
`MOVO_VERSION` before running it. It does not migrate or delete data volumes.

`./movo down -v` permanently deletes all MOVO data and now requires an explicit
interactive confirmation. Automation must pass `./movo down -v --yes`.

`./movo backup` briefly stops the deployment and archives all eight named
volumes, including deployment secrets. Because the archive can be large, put
it on a disk with sufficient free space. Verify restoration only on a
disposable host:

```bash
./movo restore /path/to/movo-backup --yes
```

Restore verifies SHA-256 checksums and requires the configured volume prefix to
match the backup. It replaces all data in the target volumes; it is not a merge.

## Production baseline

- Terminate TLS in an external reverse proxy and expose only the gateway port.
- Keep MongoDB, Redis and Weaviate on the internal Compose network.
- Keep `MOVO_VOLUME_PREFIX` unchanged throughout the installation lifecycle.
- Back up deployment secrets together with MongoDB, generated files, knowledge
  documents, Weaviate and DSH state.
- Restrict Docker daemon access; Docker access is equivalent to root access on
  the host in common installations.
- Monitor free disk, memory, container health and gateway error rates.
- Test backup restoration and release rollback with non-production data before
  every production upgrade.

The default Compose file is a single-host baseline. Operators requiring
high-availability databases, external object storage, centralized secrets or
orchestrated rolling updates should replace the bundled stateful services with
managed equivalents and validate those integrations independently.
