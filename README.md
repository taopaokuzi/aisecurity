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

## Task 4

Task 4 完成了共享领域层的第一版沉淀：

- 在 `packages/domain` 中统一定义状态枚举、错误码和核心领域模型
- 通过 `packages/domain/__init__.py` 暴露统一导出入口，供后续 API、Worker、Policy 复用
- 增加针对枚举、错误对象和模型约束的单元测试
- 在任务总表中把 `TASK-004` 标记为 `DONE / PASS`

## Task 5

Task 5 完成了数据库基础结构和仓储骨架：

- 在 `packages/infrastructure/db` 中新增首批核心表的 SQLAlchemy 模型和 session 封装
- 在 `packages/infrastructure/repositories` 中新增用户、委托、申请单、审批、授权、审计等仓储骨架
- 增加 `20260417_0002` Alembic 迁移，并把 `migrations/env.py` 接到 `Base.metadata`
- 在任务总表中把 `TASK-005` 标记为 `DONE / PASS`

## Task 6

Task 6 完成了委托凭证用例与 API：

- 在 `packages/application` 中新增委托创建、查询和有效性校验服务
- 在 `apps/api` 中新增 `POST /delegations` 与 `GET /delegations/{id}` 路由、请求上下文依赖和统一错误处理
- 增加覆盖委托创建、禁用 Agent 拒绝、非法过期时间拒绝、查询已存在委托和幂等回放的单元测试与集成测试
- 在任务总表中把 `TASK-006` 标记为 `DONE / PASS`

## Task 7

Task 7 完成了申请单创建与查询 API：

- 在 `packages/application` 中新增自然语言申请创建、详情查询、分页列表和事件落库服务
- 在 `apps/api` 中新增 `POST /permission-requests`、`GET /permission-requests/{id}`、`GET /permission-requests` 路由，并接入 API 入口
- 在 `packages/infrastructure/repositories` 中补充申请单分页过滤查询能力，支撑列表接口按状态和用户筛选
- 增加覆盖正常创建申请、无效委托拒绝、空消息拒绝、详情查询和分页列表的单元测试与集成测试
- 在任务总表中把 `TASK-007` 标记为 `DONE / PASS`

## Task 8

Task 8 完成了 LLM Gateway 与 Prompt 装载基础设施：

- 在 `packages/infrastructure` 中新增统一的 LLM Gateway、传输抽象、OpenAI-compatible transport 和配置加载入口
- 在 `packages/prompts` 中新增 Prompt 模板读取、变量渲染和缺失模板/变量的错误边界
- 在 `config/` 中新增 LLM provider、模型、超时、Prompt 目录等基础配置
- 增加覆盖 Prompt 加载、变量渲染、Gateway 配置读取、超时包装和异常包装的单元测试
- 在任务总表中把 `TASK-008` 标记为 `DONE / PASS`

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
