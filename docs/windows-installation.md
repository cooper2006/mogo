# Install and start MOVO on Windows

The recommended Windows environment is **Docker Desktop + WSL 2 + Ubuntu**. The `docker-desktop` distribution created by Docker Desktop is an internal appliance, not an Ubuntu user environment, and must not be used to run the MOVO launcher.

## 1. Install WSL 2 and Ubuntu

Open PowerShell as Administrator:

```powershell
wsl --install -d Ubuntu
```

Restart Windows when installation finishes. On the first Ubuntu launch, create a Linux username and password. Password input is intentionally not displayed.

Verify the distributions:

```powershell
wsl -l -v
```

`Ubuntu` should be listed with `VERSION` set to `2`. If `docker-desktop` is also listed, do not enter it. Set Ubuntu as the default:

```powershell
wsl --set-default Ubuntu
```

If the download returns `403`, disable a misconfigured system proxy or switch networks and retry.

## 2. Install Docker Desktop

Install and start Docker Desktop, enable its WSL 2 backend, and enable Ubuntu under **Settings → Resources → WSL Integration**. Wait for the Docker Engine to start.

Enter Ubuntu explicitly:

```powershell
wsl -d Ubuntu
```

Verify Docker from Ubuntu:

```bash
docker version
docker compose version
```

## 3. Get and start MOVO

Clone into the Linux home directory for the best permission compatibility and filesystem performance:

```bash
cd ~
git clone https://github.com/himovo/movo.git
cd movo
./movo up
```

The launcher pulls images sequentially and keeps retrying network interruptions until it succeeds or the user presses `Ctrl+C`. The default deployment does not require an `.env` file.

When the services are ready, open:

```text
http://localhost:3000/admin/setup
```

## Using a ZIP extracted by Windows

For a ZIP extracted to `D:\dsh\movo`, enter Ubuntu and run:

```bash
cd /mnt/d/dsh/movo
bash ./movo up
```

Using `bash ./movo` bypasses script execute-bit problems caused by Windows ZIP extraction or an NTFS mount.

## Troubleshooting

### The prompt starts with `docker-desktop:`

You entered Docker Desktop's internal distribution. Run `exit`, return to Windows and enter Ubuntu explicitly:

```powershell
wsl -d Ubuntu
```

### `env: can't execute 'bash': No such file or directory`

This usually means the command is running inside `docker-desktop`. Use `wsl -l -v` to verify that Ubuntu is installed, then enter it with `wsl -d Ubuntu`.

### `Permission denied`

For a repository stored on a Windows drive, run:

```bash
bash ./movo up
```

### Image pulls fail with `EOF` or interrupted connections

This usually indicates unstable access to Docker Hub or GitHub Container Registry. The latest `./movo up` pulls sequentially and keeps retrying automatically. Completed images and layers are reused.

## Without Ubuntu

After installing Git for Windows, you may open Git Bash in the MOVO directory and run `./movo up`. PowerShell or Command Prompt can also run `docker compose up -d`, but native Compose retains its default parallel pulling and does not provide the launcher's retry loop, readiness wait or setup guidance.
