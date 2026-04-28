---
project: xuebao
type: deployment-guide
updated_at: "2026-04-29"
---

# 部署指南

本指南面向 Linux 服务器部署。Windows 下的 `install.bat` 和 `run.bat` 仍只作为本地开发入口。

## 前置条件

- Linux 服务器。
- 已安装 Docker Engine 和 Docker Compose plugin。
- 服务器上已拉取本仓库。
- 已准备机器人运行所需的真实配置值。

部署脚本不会自动安装 Docker，也不会写入真实配置。

## 首次部署

1. 复制环境模板：

   ```bash
   cp .env.example .env
   ```

2. 编辑 `.env`，至少检查以下值：

   - `SUPERUSERS`
   - `COMMAND_START`
   - 你实际启用功能需要的密钥或配置，例如 `DEEPSEEK_API_KEY`
   - `XUEBAO_DATA_DIR`
   - `XUEBAO_CONFIG_DIR`
   - `XUEBAO_BACKUP_DIR`

3. 验证配置：

   ```bash
   scripts/validate-deploy-env.sh
   ```

4. 部署并启动：

   ```bash
   scripts/deploy.sh
   ```

5. 查看状态：

   ```bash
   docker compose ps
   ```

如果 `.env` 缺失、仍使用占位值，或 Docker/Compose 不可用，部署会在启动服务前失败。

## 数据与备份

`docker-compose.yml` 将宿主机路径挂载到容器内：

- `XUEBAO_DATA_DIR` -> `/app/data`
- `XUEBAO_CACHE_DIR` -> `/app/cache`
- `XUEBAO_CONFIG_DIR` -> `/app/config`

默认部署前会执行备份。可手动备份：

```bash
scripts/backup-data.sh
```

备份会写入 `XUEBAO_BACKUP_DIR` 下的 UTC 时间戳目录，包含 `data`、`cache` 和 `config`。备份失败时，部署脚本会停止后续更新步骤。

## 日志

查看最近日志：

```bash
docker compose logs --tail=100 bot
```

持续跟随日志：

```bash
docker compose logs -f bot
```

## 重新部署

在服务器仓库目录拉取新代码后再次运行：

```bash
scripts/deploy.sh
```

同一命令用于首次部署和后续更新。

## Push-to-Deploy

`.github/workflows/deploy.yml` 默认只在 `main` 分支触发部署。若部署分支不同，需要同时调整：

- `.github/workflows/deploy.yml` 中的 `branches` 和 `DEPLOY_BRANCH`
- 服务器 `.env` 中的 `DEPLOY_BRANCH`

仓库 Secrets 需要配置：

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`
- `DEPLOY_TARGET_PATH`
- `DEPLOY_PORT`，未设置时默认使用 `22`

工作流会先检查部署脚本语法和 Compose 配置，再通过 SSH 进入服务器仓库目录，执行：

```bash
git fetch --prune origin
git checkout "$DEPLOY_BRANCH"
git pull --ff-only origin "$DEPLOY_BRANCH"
scripts/deploy.sh
```

非部署分支不会自动部署。部署失败会在 GitHub Actions 日志中显示，服务器上可继续通过 `docker compose ps` 和 `docker compose logs --tail=100 bot` 检查当前服务。

## 本地开发

Windows 本地开发仍可使用：

```bat
install.bat
run.bat
```
