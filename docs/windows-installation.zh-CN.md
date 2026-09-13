# Windows 安装与启动

Windows 用户推荐使用 **Docker Desktop + WSL 2 + Ubuntu** 运行 MOVO 启动器。Docker Desktop 创建的 `docker-desktop` 是内部发行版，不是 Ubuntu，不能作为 MOVO 的命令行环境。

## 1. 安装 WSL 2 与 Ubuntu

以管理员身份打开 PowerShell：

```powershell
wsl --install -d Ubuntu
```

完成后重启 Windows，并在 Ubuntu 首次启动时按提示创建 Linux 用户名和密码。输入密码时终端不会显示字符，这是正常现象。

检查安装结果：

```powershell
wsl -l -v
```

应当看到 `Ubuntu`，且 `VERSION` 为 `2`。如果同时看到 `docker-desktop`，不要进入它。建议将 Ubuntu 设为默认发行版：

```powershell
wsl --set-default Ubuntu
```

如果下载安装返回 `403`，请先关闭异常的系统代理或切换网络后重试。

## 2. 安装 Docker Desktop

安装并启动 Docker Desktop，在设置中启用 WSL 2 后端，并在 **Settings → Resources → WSL Integration** 中开启 Ubuntu 集成。等待 Docker Engine 启动完成。

明确进入 Ubuntu：

```powershell
wsl -d Ubuntu
```

在 Ubuntu 中验证 Docker：

```bash
docker version
docker compose version
```

## 3. 获取并启动 MOVO

建议将仓库克隆到 Ubuntu 的 Linux 主目录，以获得更好的文件权限兼容性和磁盘性能：

```bash
cd ~
git clone https://github.com/himovo/movo.git
cd movo
./movo --lang zh-CN up
```

启动器会串行拉取镜像；网络中断时持续重试，直到成功或用户按 `Ctrl+C` 停止。默认部署不需要 `.env` 文件。

服务就绪后打开：

```text
http://localhost:3000/admin/setup
```

## 使用 Windows 下载的 ZIP

如果通过浏览器下载并解压到 `D:\dsh\movo`，请在 Ubuntu 中执行：

```bash
cd /mnt/d/dsh/movo
bash ./movo --lang zh-CN up
```

使用 `bash ./movo` 可以绕过 Windows 解压或 NTFS 挂载导致的脚本执行权限问题。

## 常见问题

### 提示符以 `docker-desktop:` 开头

说明进入了 Docker Desktop 内部发行版。执行 `exit` 返回 Windows，然后执行：

```powershell
wsl -d Ubuntu
```

### `env: can't execute 'bash': No such file or directory`

通常也是误入了 `docker-desktop`。使用 `wsl -l -v` 确认 Ubuntu 已安装，并明确通过 `wsl -d Ubuntu` 进入。

### `Permission denied`

在 Windows 磁盘上的仓库中改用：

```bash
bash ./movo --lang zh-CN up
```

### 镜像拉取出现 `EOF` 或连接中断

这通常是 Docker Hub 或 GitHub Container Registry 的网络波动。最新版 `./movo up` 会串行拉取并自动持续重试；已完成的镜像和镜像层不会重新完整下载。

## 不使用 Ubuntu

安装 Git for Windows 后，也可以在 MOVO 目录打开 Git Bash 并执行 `./movo --lang zh-CN up`。Windows PowerShell 或 CMD 还可以直接执行 `docker compose up -d`，但原生 Compose 会采用默认的并发拉取方式，也不会提供 MOVO 启动器的重试、健康等待和初始化提示。
