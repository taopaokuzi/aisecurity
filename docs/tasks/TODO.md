# 全局开发 Todo

## 用途

本文件是多线程协作的唯一总表。其他线程无需逐个阅读全部任务文件，只需查看本表即可判断：

- 哪些任务已经完成
- 哪些任务正在进行
- 哪些任务被阻塞
- 当前哪些任务可以启动
- 每个任务对应的详细说明文件在哪里

协作细则见 [AGENT.md](../../AGENT.md)。

## 状态规则

### 实现状态

- `TODO`：未开始
- `IN_PROGRESS`：进行中
- `BLOCKED`：被依赖、环境或外部条件阻塞
- `DONE`：实现已完成，等待或已经进入验收
- `CANCELLED`：不再执行

### 验收状态

- `NOT_READY`：尚未进入验收
- `PENDING`：已实现完成，待验收
- `PASS`：验收通过
- `FAIL`：验收未通过，需要回修
- `CANCELLED`：不再验收

## 启动判断规则

1. `启动条件` 不是静态人工许可，而是依赖判断规则。
2. 当一个任务的所有依赖都达到 `实现状态=DONE` 且 `验收状态=PASS` 时，该任务即可启动。
3. 无依赖任务可直接启动。
4. 是否真正开始执行，仍需先由领取线程更新总表。

## 协作规则

1. 任一线程开始任务前，先更新本表的 `实现状态 / 执行人 / 最近更新 / 备注`。
2. 任一线程实现完成后，必须把 `实现状态` 改为 `DONE`，并把 `验收状态` 改为 `PENDING`。
3. 任一线程验收通过后，必须把 `验收状态` 改为 `PASS`。
4. 若任务阻塞，`实现状态` 改为 `BLOCKED`，并明确阻塞原因和上游任务。
5. 若任务验收失败，`验收状态` 改为 `FAIL`，并在备注中写明需要回修的点。
6. 四份冻结基线文档不得修改：
   - `docs/agent-identity-permission-prd.md`
   - `docs/agent-identity-permission-srs.md`
   - `docs/agent-identity-permission-technical-design.md`
   - `docs/agent-identity-permission-development-guide.md`

## 任务总表

| ID | 阶段 | 任务 | 实现状态 | 验收状态 | 启动条件 | 依赖 | 执行人 | 最近更新 | 任务文件 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `TASK-001` | Gate 0 | 仓库脚手架与目录骨架 | `DONE` | `PASS` | 无 | 无 | `Codex` | `2026-04-16` | [TASK-001-repo-scaffold.md](./TASK-001-repo-scaffold.md) | 新增目录：`apps/api`、`apps/worker`、`apps/web`、`packages/domain`、`packages/application`、`packages/infrastructure`、`packages/policy`、`packages/prompts`、`packages/audit`、`migrations`、`tests/unit`、`tests/integration`、`tests/e2e`、`docker`；新增基础工程文件：`.gitignore`、`pyproject.toml`、`package.json`、`apps/web/package.json` 与各目录占位文件；命令：`sed`、`rg --files`、`find`、`mkdir -p`、`python3 -c`、`git status --short`；测试：配置文件解析通过；风险：仅完成仓库骨架，运行入口/Compose/配置样例待后续任务补齐；可进入验收：是；验收结果：目录、占位文件、基础工程文件与冻结文档检查通过 |
| `TASK-002` | Gate 0 | 运行时入口与健康检查 | `DONE` | `PASS` | `TASK-001=PASS` | `TASK-001` | `Codex` | `2026-04-16` | [TASK-002-runtime-entry-and-health.md](./TASK-002-runtime-entry-and-health.md) | FastAPI 入口：`apps/api/main.py`；Worker 入口：`apps/worker/celery_app.py` 与 `apps/worker/__main__.py`；Web 入口：`apps/web/app/page.js` 与 `apps/web/app/layout.js`；健康检查：`GET /health`、`GET /api/health`、`python -m apps.worker.healthcheck`；命令：`python3 -m compileall apps`、`python -m apps.api`、`curl http://127.0.0.1:8000/health`、`python -m apps.worker`、`python -m apps.worker.healthcheck`、`npm install`、`npm run web:build`、`npm run web:start`、`curl http://127.0.0.1:3000/api/health`、`npm run web:lint`；测试：API/Worker/Web 启动通过，API/Web 健康检查通过，Web build/lint 通过；风险：Worker 当前默认使用 `memory://` broker 作为最小本地运行兜底，Redis/Compose 与统一配置加载待 `TASK-003`；可进入验收：是；验收结果：通过，满足 `TASK-003` 与 `TASK-004` 的启动前置条件 |
| `TASK-003` | Gate 0 | 本地开发编排与配置加载 | `TODO` | `NOT_READY` | `TASK-001=PASS` 且 `TASK-002=PASS` | `TASK-001`,`TASK-002` | `TBD` | `2026-04-16` | [TASK-003-local-dev-compose-and-config.md](./TASK-003-local-dev-compose-and-config.md) | Docker Compose、环境变量、README、本地启动链路 |
| `TASK-004` | Gate 1 | 领域枚举与共享模型 | `TODO` | `NOT_READY` | `TASK-001=PASS` 且 `TASK-002=PASS` | `TASK-001`,`TASK-002` | `TBD` | `2026-04-16` | [TASK-004-domain-enums-and-shared-models.md](./TASK-004-domain-enums-and-shared-models.md) | 枚举、错误码、核心实体与状态常量 |
| `TASK-005` | Gate 1 | 核心数据库迁移与仓储骨架 | `TODO` | `NOT_READY` | `TASK-004=PASS` | `TASK-004` | `TBD` | `2026-04-16` | [TASK-005-core-db-migrations-and-repositories.md](./TASK-005-core-db-migrations-and-repositories.md) | 第一批表、Alembic、仓储接口 |
| `TASK-006` | Gate 1 | 委托凭证用例与 API | `TODO` | `NOT_READY` | `TASK-005=PASS` | `TASK-005` | `TBD` | `2026-04-16` | [TASK-006-delegation-service-and-api.md](./TASK-006-delegation-service-and-api.md) | `POST/GET /delegations` 与委托校验 |
| `TASK-007` | Gate 1 | 申请单创建与查询 API | `TODO` | `NOT_READY` | `TASK-005=PASS` 且 `TASK-006=PASS` | `TASK-005`,`TASK-006` | `TBD` | `2026-04-16` | [TASK-007-permission-request-create-and-query.md](./TASK-007-permission-request-create-and-query.md) | `POST/GET /permission-requests` |
| `TASK-008` | Gate 2 | LLM Gateway 与 Prompt 装载 | `TODO` | `NOT_READY` | `TASK-001=PASS` 且 `TASK-002=PASS` | `TASK-001`,`TASK-002` | `TBD` | `2026-04-16` | [TASK-008-llm-gateway-and-prompt-loading.md](./TASK-008-llm-gateway-and-prompt-loading.md) | Prompt 目录、模型调用封装 |
| `TASK-009` | Gate 2 | 策略映射与风险规则引擎 | `TODO` | `NOT_READY` | `TASK-004=PASS` 且 `TASK-008=PASS` | `TASK-004`,`TASK-008` | `TBD` | `2026-04-16` | [TASK-009-policy-mapping-and-risk-engine.md](./TASK-009-policy-mapping-and-risk-engine.md) | 资源动作映射、风险规则、审批链规则 |
| `TASK-010` | Gate 2 | 评估流程与 Evaluate API | `TODO` | `NOT_READY` | `TASK-007=PASS` 且 `TASK-009=PASS` | `TASK-007`,`TASK-009` | `TBD` | `2026-04-16` | [TASK-010-evaluation-flow-and-api.md](./TASK-010-evaluation-flow-and-api.md) | `POST /permission-requests/{id}/evaluate` |
| `TASK-011` | Gate 3 | Approval Adapter 与审批回调 | `TODO` | `NOT_READY` | `TASK-010=PASS` | `TASK-010` | `TBD` | `2026-04-16` | [TASK-011-approval-adapter-and-callback.md](./TASK-011-approval-adapter-and-callback.md) | 发起审批、回调验签、幂等处理 |
| `TASK-012` | Gate 3 | Provisioning Service 与飞书连接器 | `TODO` | `NOT_READY` | `TASK-011=PASS` | `TASK-011` | `TBD` | `2026-04-16` | [TASK-012-provisioning-service-and-feishu-connector.md](./TASK-012-provisioning-service-and-feishu-connector.md) | 授权开通与 grant 状态回写 |
| `TASK-013` | Gate 4 | 授权生命周期：提醒、续期、过期回收 | `TODO` | `NOT_READY` | `TASK-012=PASS` | `TASK-012` | `TBD` | `2026-04-16` | [TASK-013-grant-lifecycle-renew-expire.md](./TASK-013-grant-lifecycle-renew-expire.md) | 提醒、续期、自动回收 |
| `TASK-014` | Gate 4 | Session Authority 与撤销链路 | `TODO` | `NOT_READY` | `TASK-012=PASS` | `TASK-012` | `TBD` | `2026-04-16` | [TASK-014-session-authority-and-revoke-flow.md](./TASK-014-session-authority-and-revoke-flow.md) | 会话表、撤销广播、同步失败补偿 |
| `TASK-015` | Gate 5 | 审计查询与异常补偿 API | `TODO` | `NOT_READY` | `TASK-011=PASS` 且 `TASK-012=PASS` 且 `TASK-014=PASS` | `TASK-011`,`TASK-012`,`TASK-014` | `TBD` | `2026-04-16` | [TASK-015-audit-query-and-compensation-api.md](./TASK-015-audit-query-and-compensation-api.md) | 审计查询、失败任务、重试接口 |
| `TASK-016` | Gate 5 | 员工端申请与状态页面 | `TODO` | `NOT_READY` | `TASK-003=PASS` 且 `TASK-007=PASS` 且 `TASK-010=PASS` | `TASK-003`,`TASK-007`,`TASK-010` | `TBD` | `2026-04-16` | [TASK-016-web-request-and-status-ui.md](./TASK-016-web-request-and-status-ui.md) | 员工申请页、状态页、详情页 |
| `TASK-017` | Gate 5 | 管理后台与补偿页面 | `TODO` | `NOT_READY` | `TASK-003=PASS` 且 `TASK-015=PASS` | `TASK-003`,`TASK-015` | `TBD` | `2026-04-16` | [TASK-017-web-admin-and-compensation-ui.md](./TASK-017-web-admin-and-compensation-ui.md) | 管理后台、失败任务、补偿页面 |
| `TASK-018` | Gate 6 | Mock Feishu 与集成 / E2E 用例 | `TODO` | `NOT_READY` | `TASK-011=PASS` 且 `TASK-012=PASS` 且 `TASK-013=PASS` 且 `TASK-014=PASS` | `TASK-011`,`TASK-012`,`TASK-013`,`TASK-014` | `TBD` | `2026-04-16` | [TASK-018-mock-feishu-and-integration-e2e.md](./TASK-018-mock-feishu-and-integration-e2e.md) | Mock、集成测试、端到端场景 |
| `TASK-019` | Gate 6 | 发布前收口与上线检查 | `TODO` | `NOT_READY` | `TASK-013=PASS` 且 `TASK-014=PASS` 且 `TASK-015=PASS` 且 `TASK-016=PASS` 且 `TASK-017=PASS` 且 `TASK-018=PASS` | `TASK-013`,`TASK-014`,`TASK-015`,`TASK-016`,`TASK-017`,`TASK-018` | `TBD` | `2026-04-16` | [TASK-019-release-readiness-and-final-check.md](./TASK-019-release-readiness-and-final-check.md) | 最终验证、风险清单、上线建议 |

## 推荐执行顺序

1. `TASK-001` -> `TASK-002` -> `TASK-003`
2. `TASK-004` -> `TASK-005` -> `TASK-006` -> `TASK-007`
3. `TASK-008` -> `TASK-009` -> `TASK-010`
4. `TASK-011` -> `TASK-012`
5. `TASK-013` 与 `TASK-014` 可并行
6. `TASK-015`
7. `TASK-016` 与 `TASK-017` 可并行
8. `TASK-018`
9. `TASK-019`
