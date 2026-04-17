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
| `TASK-003` | Gate 0 | 本地开发编排与配置加载 | `DONE` | `PASS` | `TASK-001=PASS` 且 `TASK-002=PASS` | `TASK-001`,`TASK-002` | `Codex` | `2026-04-16` | [TASK-003-local-dev-compose-and-config.md](./TASK-003-local-dev-compose-and-config.md) | 编排文件位置：`compose.yaml`、`docker/python.Dockerfile`、`docker/web.Dockerfile`、`docker/python-requirements.txt`；配置文件位置：`config/settings.base.toml`、`config/settings.dev.toml`、`config/settings.test.toml`、`config/settings.prod.toml`、`config/loader.py`；环境变量样例位置：`.env.example`；README 启动说明已补齐：是；Alembic 初始化：`alembic.ini`、`migrations/env.py`、`migrations/script.py.mako`、`migrations/versions/20260416_0001_task_003_bootstrap.py`；实现验证：`docker compose config`、`docker compose up -d postgres redis api worker web`、`curl /health`、`curl /api/health`、`python3 -m config.loader show`、`docker compose exec -T api alembic heads/history/upgrade head` 通过，`alembic_version=20260416_0001`；冻结文档检查：未修改；越界检查：未实现业务接口、审批流、业务表结构或真实连接器；验收结果：PASS；下游影响：`TASK-016`、`TASK-017` 的本地环境前置已满足，后续仅待各自业务依赖通过 |
| `TASK-004` | Gate 1 | 领域枚举与共享模型 | `DONE` | `PASS` | `TASK-001=PASS` 且 `TASK-002=PASS` | `TASK-001`,`TASK-002` | `Codex` | `2026-04-17` | [TASK-004-domain-enums-and-shared-models.md](./TASK-004-domain-enums-and-shared-models.md) | 修改文件：`packages/domain/__init__.py`、`packages/domain/enums.py`、`packages/domain/models.py`、`packages/domain/errors.py`、`tests/unit/test_domain_enums.py`、`tests/unit/test_domain_models.py`、`tests/unit/test_domain_errors.py`；领域枚举入口文件：`packages/domain/enums.py`；共享模型入口文件：`packages/domain/models.py`；错误码入口文件：`packages/domain/errors.py`；统一导出入口：`packages/domain/__init__.py`；命令：`sed -n`、`rg -n`、`git status --short`、`python3 -m compileall packages/domain tests/unit`、`python3 -m unittest discover -s tests/unit -p 'test_domain_*.py' -v`；测试结果：11 个单元测试通过；可进入验收：是；验收结果：PASS；下游判断：`TASK-005` 可启动，`TASK-009` 仍需等待 `TASK-008=PASS`；遗留风险：`reconcile_status` 文档未给出受控枚举，当前在模型中保留为字符串字段，待后续规格明确后再收紧 |
| `TASK-005` | Gate 1 | 核心数据库迁移与仓储骨架 | `DONE` | `PASS` | `TASK-004=PASS` | `TASK-004` | `Codex` | `2026-04-17` | [TASK-005-core-db-migrations-and-repositories.md](./TASK-005-core-db-migrations-and-repositories.md) | 首批 8 张表已全部落地：`users`、`agent_identities`、`delegation_credentials`、`permission_requests`、`permission_request_events`、`approval_records`、`access_grants`、`audit_records`；模型/DB 骨架：`packages/infrastructure/db/{base.py,models.py,session.py}`，repository 骨架：`packages/infrastructure/repositories/{base.py,identity.py,permissions.py}`；Alembic 迁移：`migrations/versions/20260417_0002_task_005_core_schema.py`；命令：`python3 -m compileall packages/infrastructure`、`python3 -m compileall migrations/env.py migrations/versions/20260417_0002_task_005_core_schema.py`、`docker compose up -d postgres redis`、`docker compose run --rm api alembic revision --autogenerate -m "task_005_core_schema"`、`docker compose run --rm api alembic upgrade head`、`docker compose run --rm api python - <<'PY' ...`、`docker compose exec -T postgres psql ...`；迁移验证：升级到 `20260417_0002` 成功，8 张表、关键约束与索引均已落库，模型与 repository 可导入；可进入验收：是；验收结果：PASS；遗留风险：`reconcile_status` 设计文档尚未定义受控枚举，当前按文档保留为非空字符串列，待规格明确后再收紧；下游判断：`TASK-006` 已满足启动前置，`TASK-007` 仍需等待 `TASK-006=PASS` |
| `TASK-006` | Gate 1 | 委托凭证用例与 API | `DONE` | `PASS` | `TASK-005=PASS` | `TASK-005` | `Codex` | `2026-04-17` | [TASK-006-delegation-service-and-api.md](./TASK-006-delegation-service-and-api.md) | 委托服务入口：`packages/application/delegations.py`；委托 API 路由：`apps/api/delegations.py`（`POST /delegations`、`GET /delegations/{id}`），配套依赖/错误处理：`apps/api/{dependencies.py,errors.py}`、`apps/api/main.py`；已覆盖测试：正常创建委托、Agent 停用拒绝、`expire_at` 非法拒绝、查询已存在委托、幂等回放；命令：`python3 -m compileall packages/application apps/api tests/unit/test_delegation_service.py tests/integration/test_delegation_api.py`、`docker compose exec -T api python -m unittest tests.unit.test_delegation_service tests.integration.test_delegation_api -v`；测试：8 项通过；可进入验收：是；验收结果：PASS；TASK-007 可启动：是；遗留风险：当前用户/管理员身份上下文通过 `X-User-Id` / `X-Operator-Type` 请求头注入，待后续统一鉴权接入替换 |
| `TASK-007` | Gate 1 | 申请单创建与查询 API | `DONE` | `PASS` | `TASK-005=PASS` 且 `TASK-006=PASS` | `TASK-005`,`TASK-006` | `Codex` | `2026-04-17` | [TASK-007-permission-request-create-and-query.md](./TASK-007-permission-request-create-and-query.md) | 修改文件：`packages/application/{__init__.py,permission_requests.py}`、`apps/api/{main.py,permission_requests.py}`、`packages/infrastructure/repositories/permissions.py`、`tests/{unit/test_permission_request_service.py,integration/test_permission_request_api.py}`；申请单服务入口：`packages/application/permission_requests.py`；API 路由：`apps/api/permission_requests.py`（`POST /permission-requests`、`GET /permission-requests/{id}`、`GET /permission-requests`）；事件记录实现位置：`packages/application/permission_requests.py` 写入 `permission_request_events` 与 `audit_records`；已覆盖测试：正常创建申请、`delegation` 无效拒绝、`message` 为空拒绝、查询已存在申请详情、分页查询申请列表；命令：`python3 -m compileall packages/application apps/api tests/unit/test_permission_request_service.py tests/integration/test_permission_request_api.py`、`docker compose exec -T api python -m unittest tests.unit.test_permission_request_service tests.integration.test_permission_request_api -v`；测试：10 项通过；是否已可进入验收：是；验收结果：PASS；遗留风险：创建后 `approval_status` 当前按状态机推断初始化为 `NotRequired`，待 `TASK-010` 评估流程接入后再推进审批态 |
| `TASK-008` | Gate 2 | LLM Gateway 与 Prompt 装载 | `DONE` | `PASS` | `TASK-001=PASS` 且 `TASK-002=PASS` | `TASK-001`,`TASK-002` | `Codex` | `2026-04-17` | [TASK-008-llm-gateway-and-prompt-loading.md](./TASK-008-llm-gateway-and-prompt-loading.md) | 修改文件：`packages/infrastructure/llm_gateway.py`、`packages/prompts/{__init__.py,loader.py,templates/*}`、`config/{loader.py,settings.base.toml,settings.test.toml}`、`tests/unit/{test_prompt_loader.py,test_llm_gateway.py}`；`llm_gateway` 入口：`packages/infrastructure/llm_gateway.py`；Prompt 存放路径：`packages/prompts/templates/`；已覆盖测试：Prompt 加载、缺失 Prompt 报错、模板变量渲染、Gateway 统一入口读取配置、超时包装、基础异常包装；命令：`PYTHONPYCACHEPREFIX=/tmp/codex-pycache python3 -m compileall packages/prompts packages/infrastructure config tests/unit/test_prompt_loader.py tests/unit/test_llm_gateway.py`、`PYTHONPYCACHEPREFIX=/tmp/codex-pycache python3 -m unittest tests.unit.test_prompt_loader tests.unit.test_llm_gateway -v`；测试：8 项通过；是否已可进入验收：是；验收结果：PASS；TASK-009 可启动：是；遗留风险：默认 provider 仍为 `stub`，真实 LLM 凭据、联通性与业务评估链路集成待后续任务接入 |
| `TASK-009` | Gate 2 | 策略映射与风险规则引擎 | `DONE` | `PASS` | `TASK-004=PASS` 且 `TASK-008=PASS` | `TASK-004`,`TASK-008` | `Codex` | `2026-04-17` | [TASK-009-policy-mapping-and-risk-engine.md](./TASK-009-policy-mapping-and-risk-engine.md) | 修改文件：`packages/policy/{__init__.py,engine.py,loader.py,models.py}`、`config/policy/{policy_manifest.toml,permission_mappings.toml,risk_rules.toml,approval_rules.toml}`、`tests/unit/test_policy_engine.py`；规则文件位置：`config/policy/`；策略服务入口：`packages/policy/engine.py` 与 `packages/policy/__init__.py`；关键测试场景：销售部 Q3 报表只读映射、跨部门访问提风险、高敏资源提风险、无法明确判定走安全路径；命令：`PYTHONPYCACHEPREFIX=/tmp/codex-pycache python3 -m compileall packages/policy tests/unit/test_policy_engine.py`、`PYTHONPYCACHEPREFIX=/tmp/codex-pycache python3 -m unittest tests.unit.test_policy_engine -v`；测试：5 项通过；可进入验收：是；遗留风险：当前规则词典仍为静态 TOML，真实资源目录/组织关系与 Evaluate 流程集成待 `TASK-010` 接入 |
| `TASK-010` | Gate 2 | 评估流程与 Evaluate API | `DONE` | `PASS` | `TASK-007=PASS` 且 `TASK-009=PASS` | `TASK-007`,`TASK-009` | `Codex` | `2026-04-17` | [TASK-010-evaluation-flow-and-api.md](./TASK-010-evaluation-flow-and-api.md) | 修改文件：`packages/application/{__init__.py,permission_request_evaluations.py}`、`packages/infrastructure/{__init__.py,permission_request_parser.py}`、`apps/api/permission_requests.py`、`tests/{unit/test_permission_request_evaluation_service.py,integration/test_permission_request_api.py}`；评估服务入口：`packages/application/permission_request_evaluations.py`；API 路由：`apps/api/permission_requests.py`（`POST /permission-requests/{id}/evaluate`、`GET /permission-requests/{id}/evaluation`）；事件记录位置：`packages/application/permission_request_evaluations.py` 写入 `permission_request_events` 与 `audit_records`；主案例测试结果：`我需要查看销售部 Q3 报表，但不需要修改权限` 输出 `report:sales.q3:read`，测试通过；命令：`git status --short`、`git diff -- docs/tasks/TODO.md`、`sed -n`、`rg -n`、`python3 -m compileall packages/application packages/infrastructure apps/api tests/unit/test_permission_request_evaluation_service.py tests/integration/test_permission_request_api.py`、`docker compose ps`、`docker compose exec -T api python -m unittest tests.unit.test_permission_request_service tests.unit.test_permission_request_evaluation_service tests.integration.test_permission_request_api -v`；测试：18 项通过；是否已可进入验收：是；验收结果：PASS；遗留风险：`approval_route` 当前存于 `structured_request_json`，尚无独立结构化列；`TASK-011` 前置是否满足：是，可启动 |
| `TASK-011` | Gate 3 | Approval Adapter 与审批回调 | `DONE` | `PASS` | `TASK-010=PASS` | `TASK-010` | `Codex` | `2026-04-17` | [TASK-011-approval-adapter-and-callback.md](./TASK-011-approval-adapter-and-callback.md) | 修改文件：`packages/infrastructure/{approval_adapter.py,__init__.py}`、`packages/application/{approvals.py,__init__.py}`、`apps/api/{approvals.py,permission_requests.py,main.py,errors.py}`、`tests/{unit/test_approval_service.py,integration/test_permission_request_api.py,integration/test_approval_callback_api.py}`；Adapter 入口：`packages/application/approvals.py:ApprovalService.submit_approval_for_request`（由 `apps/api/permission_requests.py` 在 Evaluate 成功且 `approval_status=Pending` 时触发）；回调路由：`apps/api/approvals.py` `POST /approvals/callback`；签名与来源处理：`packages/application/approvals.py:_verify_callback` + `packages/infrastructure/approval_adapter.py:ApprovalCallbackVerifier`；幂等处理位置：`packages/application/approvals.py` 调用 `ApprovalRecordRepository.get_by_idempotency_key`；已覆盖测试：审批通过回调、审批驳回回调、重复回调、签名非法、找不到审批记录、评估后自动发起审批；命令：`python3 -m compileall packages/application packages/infrastructure apps/api tests/unit/test_approval_service.py tests/integration/test_permission_request_api.py tests/integration/test_approval_callback_api.py`、`docker compose ps`、`docker compose exec -T api python -m unittest tests.unit.test_approval_service tests.integration.test_permission_request_api tests.integration.test_approval_callback_api -v`；测试：15 项通过；可进入验收：是；验收结果：PASS；TASK-012 可启动：是；遗留风险：Approval Adapter 当前为 `stub` 提供方实现，生产签名密钥/来源白名单依赖环境变量配置，单条 `approval_record` 当前仅保留最近一次成功处理的回调载荷快照 |
| `TASK-012` | Gate 3 | Provisioning Service 与飞书连接器 | `DONE` | `PASS` | `TASK-011=PASS` | `TASK-011` | `Codex` | `2026-04-17` | [TASK-012-provisioning-service-and-feishu-connector.md](./TASK-012-provisioning-service-and-feishu-connector.md) | 已修复 connector unavailable 失败写回回滚问题，API/worker 事务边界已处理：`apps/api/grants.py` 与 `apps/worker/tasks.py` 在 `CONNECTOR_UNAVAILABLE` 时先提交失败写回再继续抛错；新增测试：`tests.unit.test_provisioning_service.test_provisioning_persists_failed_writeback_before_raising_connector_unavailable`、`tests.integration.test_grant_provision_api.test_provision_endpoint_persists_failed_writeback_when_connector_is_unavailable`、`tests.integration.test_worker_provision_task.test_worker_task_persists_failed_writeback_when_connector_is_unavailable`；回归结果：`tests.unit.test_provisioning_service`、`tests.integration.test_grant_provision_api`、`tests.integration.test_approval_callback_api`、`tests.integration.test_worker_provision_task` 共 16 项通过；重新验收结论：PASS，`TASK-013` 与 `TASK-014` 可启动 |
| `TASK-013` | Gate 4 | 授权生命周期：提醒、续期、过期回收 | `DONE` | `PASS` | `TASK-012=PASS` | `TASK-012` | `Codex` | `2026-04-17` | [TASK-013-grant-lifecycle-renew-expire.md](./TASK-013-grant-lifecycle-renew-expire.md) | 已补上续期审批提交闭环：`apps/api/approval_submission.py` 共享复用 `ApprovalService.submit_approval_for_request`，`apps/api/grants.py` `POST /grants/{id}/renew` 在创建 renewal request 后显式提交审批，`approval_records` 已创建；新增测试：`tests.integration.test_grant_renew_api.GrantRenewApiIntegrationTests.test_post_grant_renew_creates_follow_up_request`、`tests.integration.test_grant_renew_api.GrantRenewApiIntegrationTests.test_post_grant_renew_rolls_back_when_approval_submission_fails`；命令：`python3 -m compileall apps/api tests/integration/test_grant_renew_api.py`、`docker compose exec -T api python -m unittest tests.integration.test_grant_renew_api tests.integration.test_permission_request_api tests.integration.test_approval_callback_api tests.unit.test_grant_lifecycle_service tests.integration.test_worker_grant_lifecycle_task -v`；测试：22 项通过；重新验收结论：PASS，满足 V1 生命周期治理最小要求；遗留风险：续期审批提交失败当前按整笔回滚处理，避免半成品状态，外部会话撤销与全局 session 同步仍待 `TASK-014` |
| `TASK-014` | Gate 4 | Session Authority 与撤销链路 | `IN_PROGRESS` | `NOT_READY` | `TASK-012=PASS` | `TASK-012` | `Codex` | `2026-04-17` | [TASK-014-session-authority-and-revoke-flow.md](./TASK-014-session-authority-and-revoke-flow.md) | 已确认 `TASK-012` 为 `DONE/PASS`，开始实现 `session_contexts`、Session Authority、`POST /sessions/revoke`、撤销广播与同步失败补偿 |
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
