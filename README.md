# aisecurity

Agent Identity & Permission 系统的单仓项目骨架。

## 文档

- [需求文档](docs/agent-identity-permission-prd.md)
- [系统需求规格](docs/agent-identity-permission-srs.md)
- [技术设计](docs/agent-identity-permission-technical-design.md)
- [开发指南](docs/agent-identity-permission-development-guide.md)

## 目录约定

- `compose.yaml`：本地统一编排入口
- `config/`：按 `base + dev/test/prod` 分层的运行配置
- `.env.example`：环境变量样例
- `docker/`：本地开发镜像与依赖安装定义
- `migrations/`、`alembic.ini`：Alembic 初始化配置

## Task 3

Task 3 完成了本地开发编排与配置加载基础设施：

- 新增 `compose.yaml`，统一编排 `postgres`、`redis`、`api`、`worker`、`web`
- 新增 `config/` 分层配置与 `python -m config.loader` 加载入口
- 新增 `.env.example`、Docker 开发镜像定义和 Alembic 初始化链路
- 补充 README 本地启动、迁移和健康检查说明，方便后续任务直接复用

## 环境准备

1. 安装 Python 3.11、Node.js 20+、Docker、Docker Compose。
2. 从样例复制本地环境变量文件：

```bash
cp .env.example .env
```

如果当前 Linux / WSL 用户的 `uid:gid` 不是 `1000:1000`，请同步把 `.env` 里的 `APP_UID`、`APP_GID` 改成 `id -u`、`id -g` 的实际值，然后使用 `docker compose up --build` 重新构建 Python 镜像，避免容器内进程以 root 运行或生成权限不匹配的文件。

3. 如果要在宿主机直接执行 Python 命令，先安装运行与迁移依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --no-build-isolation -e . -r docker/python-requirements.txt
npm install
```

## 配置加载

运行配置由 `config/settings.base.toml` 与 `config/settings.<env>.toml` 叠加生成，当前提供：

- `config/settings.dev.toml`
- `config/settings.test.toml`
- `config/settings.prod.toml`

加载入口是 `python -m config.loader`：

- 查看当前解析结果：`python -m config.loader show --format json`
- 指定环境查看：`python -m config.loader show --env test`
- 带配置执行命令：`python -m config.loader exec -- alembic upgrade head`
- 根目录存在 `.env` 时会自动参与解析，宿主机直跑服务时无需再手工 `export`

优先级从低到高：

1. `config/settings.base.toml`
2. `config/settings.<env>.toml`
3. 根目录 `.env`
4. 当前 shell 中显式设置的同名环境变量

## 本地启动

统一入口：

```bash
docker compose up --build -d postgres redis api worker web
```

查看服务状态：

```bash
docker compose ps
```

停止并清理：

```bash
docker compose down
```

如需在宿主机单独启动服务，也可以直接复用配置加载入口：

```bash
python -m config.loader exec -- python -m apps.api
python -m config.loader exec -- python -m apps.worker
python -m config.loader exec -- npm --prefix apps/web run dev
```

## Alembic 初始化与迁移命令

容器内执行：

```bash
docker compose run --rm api alembic upgrade head
docker compose run --rm api alembic revision -m "init_schema"
```

宿主机执行：

```bash
python -m config.loader exec -- alembic upgrade head
python -m config.loader exec -- alembic revision -m "init_schema"
```

当前仓库已提供基础 Alembic 链路：

- `alembic.ini`
- `migrations/env.py`
- `migrations/script.py.mako`
- `migrations/versions/20260416_0001_task_003_bootstrap.py`

## 健康检查

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:3000/api/health
docker compose exec worker python -m config.loader exec -- python -m apps.worker.healthcheck
docker compose exec postgres pg_isready -U "${POSTGRES_USER:-aisecurity}" -d "${POSTGRES_DB:-aisecurity}"
docker compose exec redis redis-cli ping
```

期望结果：

- API 返回 `status=ok`
- Web 健康接口返回 `status=ok`
- Worker 健康检查输出已注册任务和 `status=ok`
- PostgreSQL 返回 `accepting connections`
- Redis 返回 `PONG`

## 本地联调的 Mock / Stub 约定

当前本地联调默认不接真实外部系统：

- `SSO_MODE=stub`：身份与组织数据走 stub 模式
- `FEISHU_MODE=mock`：审批与权限开通接口走 mock 模式
- `MOCK_FEISHU_BASE_URL`：预留给后续 `TASK-018` 的 mock 服务地址

这意味着：

- `postgres`、`redis`、`api`、`worker`、`web` 已可通过 Compose 统一启动
- 真实 SSO / 飞书连接器不会在 `TASK-003` 中提前实现
- 后续外部系统联调可直接沿用 `.env` 与 `config/` 中的变量名
