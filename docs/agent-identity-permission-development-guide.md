# 开发实施文档

## 给 AI 发通行证：Agent 身份与权限系统 V1

> 文档状态：`Frozen`
> 冻结日期：`2026-04-16`
> 冻结说明：本文档已作为 V1 研发执行基线冻结。自本次冻结起，不再直接修改；后续任务拆解、阶段计划、开发提示词与验收结果统一维护在执行类文档中。

## 1. 文档目的

本文档基于以下文档继续下钻，面向研发团队的实际开发与交付：

- 产品需求文档：`docs/agent-identity-permission-prd.md`
- 软件需求规格说明书：`docs/agent-identity-permission-srs.md`
- 技术设计文档：`docs/agent-identity-permission-technical-design.md`

本文档回答的问题不是“产品做什么”或“系统怎么设计”，而是：

- 项目应该如何开始开发。
- 第一阶段要先做哪些模块。
- 代码仓库如何组织。
- 每个模块的开发责任、输入输出和验收标准是什么。
- 数据库、接口、任务调度、连接器、测试和部署应如何推进。

本文档是 V1 的研发执行基线。后续若技术选型、接口协议或范围发生变化，应优先更新本文件，再同步调整任务拆解和开发排期。

## 2. 研发目标

V1 的开发目标是交付一个可运行的权限自助服务闭环，至少满足以下能力：

1. 员工通过自然语言提交权限申请。
2. 系统生成结构化权限申请和最小权限建议。
3. 系统完成风险分级并发起飞书审批。
4. 审批通过后自动调用飞书连接器完成只读权限开通。
5. 系统记录有效期，支持到期提醒、续期和自动回收。
6. 管理员能够查看申请状态、授权状态和异常状态。
7. 所有关键动作具备审计记录。

V1 不追求：

- 多 Agent 协同编排。
- 多租户和跨组织治理。
- 全量资源系统接入。
- 高度复杂的实时策略编排。

## 3. 技术栈定版

由于当前仓库尚无代码基础，V1 采用以下默认技术栈，以保证最短时间内交付可运行版本。

### 3.1 后端

- 语言：Python 3.11
- Web 框架：FastAPI
- ORM：SQLAlchemy 2.x
- 数据校验：Pydantic 2.x
- 数据库迁移：Alembic
- 异步任务：Celery
- 缓存与队列：Redis
- 主数据库：PostgreSQL 15+

### 3.2 前端

- 管理端与简单申请端：Next.js 15 + React
- UI 组件：基于现成组件库二次封装
- 鉴权：通过企业 SSO / 后端 session 或 token 转发

### 3.3 AI 与规则

- LLM 调用：统一封装为 `llm_gateway`
- 规则引擎：V1 采用代码内规则 + 配置表驱动，不单独引入复杂策略引擎
- Prompt 模板：存放于应用配置目录，不散落在业务代码中

### 3.4 运维与观测

- 容器化：Docker
- 编排：Docker Compose 用于开发和 PoC，Kubernetes 留待后续
- 日志：结构化 JSON 日志
- 指标：Prometheus 格式导出
- 告警：企业现有告警平台或简单 webhook

### 3.5 技术选型理由

- Python 更适合 Agent、LLM、规则与连接器的快速集成。
- FastAPI 适合快速构建 API、后台任务和内部管理接口。
- PostgreSQL + Redis + Celery 是成熟、低风险的 PoC 组合。
- Next.js 适合快速搭建申请页和管理端页面。
- 模块化单体便于快速落地，同时能逐步拆分为独立服务。

## 4. 仓库结构建议

建议采用单仓多应用结构：

```text
aisecurity/
├── apps/
│   ├── api/                      # FastAPI 主应用
│   ├── worker/                   # Celery worker
│   └── web/                      # Next.js 前端
├── packages/
│   ├── domain/                   # 领域模型与核心枚举
│   ├── application/              # 用例服务
│   ├── infrastructure/           # DB、Redis、SSO、Connector
│   ├── policy/                   # 权限映射、风险规则、策略决策
│   ├── prompts/                  # LLM prompts
│   └── audit/                    # 审计事件模型
├── docs/
├── scripts/
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── docker/
```

### 4.1 `apps/api`

职责：

- 提供外部 API。
- 承载主业务路由。
- 调用应用层服务。
- 不直接写复杂业务逻辑。

### 4.2 `apps/worker`

职责：

- 处理异步审批回调。
- 处理开通重试。
- 处理到期提醒。
- 处理自动回收和补偿任务。

### 4.3 `apps/web`

职责：

- 员工申请页。
- 员工状态查询页。
- 管理员后台。
- 异常补偿页面。

### 4.4 `packages/domain`

职责：

- 统一维护实体、值对象、枚举和状态机定义。
- 作为 `api`、`worker`、`policy` 共用的核心模型层。

### 4.5 `packages/application`

职责：

- 编排用例。
- 连接领域层与基础设施层。
- 实现“提交申请”“评估申请”“发起审批”“执行开通”“续期”“撤销”等用例。

### 4.6 `packages/infrastructure`

职责：

- 数据库仓储实现。
- Redis、Celery、SSO、Feishu、日志、告警等外部依赖封装。

### 4.7 `packages/policy`

职责：

- 资源与动作词典。
- 最小权限映射规则。
- 风险评分规则。
- 审批升级规则。
- 输出控制策略。

## 5. 环境与配置

## 5.1 本地开发依赖

- Python 3.11
- Node.js 20+
- PostgreSQL
- Redis
- Docker / Docker Compose

## 5.2 环境变量分类

建议按以下类别拆分：

- 基础环境：`APP_ENV`、`LOG_LEVEL`
- 数据库：`DATABASE_URL`
- Redis / Celery：`REDIS_URL`、`CELERY_BROKER_URL`
- SSO：`SSO_CLIENT_ID`、`SSO_CLIENT_SECRET`
- Feishu：`FEISHU_APP_ID`、`FEISHU_APP_SECRET`
- LLM：`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`
- 安全：`SIGNING_SECRET`、`AUDIT_HASH_SECRET`

## 5.3 配置文件建议

```text
config/
├── settings.dev.yaml
├── settings.test.yaml
├── settings.prod.yaml
├── policy/
│   ├── permission_mappings.yaml
│   ├── risk_rules.yaml
│   └── approval_rules.yaml
└── prompts/
    ├── parse_permission_request.md
    └── explain_permission_result.md
```

## 6. 数据库实施方案

## 6.1 第一批表

第一阶段必须创建：

- `users`
- `agent_identities`
- `delegation_credentials`
- `permission_requests`
- `permission_request_events`
- `approval_records`
- `access_grants`
- `audit_records`

这些表足以支撑“提交申请 -> 审批 -> 开通 -> 审计”最小闭环。

## 6.2 第二批表

第二阶段创建：

- `session_contexts`
- `policy_rules`
- `risk_rules`
- `connector_tasks`
- `notification_tasks`

这些表用于支撑续期、回收、撤销、会话治理和配置化规则。

## 6.3 建表顺序

1. 基础身份表：`users`、`agent_identities`
2. 委托表：`delegation_credentials`
3. 申请主表：`permission_requests`
4. 审批与授权结果表：`approval_records`、`access_grants`
5. 事件与审计表：`permission_request_events`、`audit_records`
6. 会话与任务表：`session_contexts`、`connector_tasks`

## 6.4 状态字段规范

所有核心表的状态字段统一用枚举值，不使用自由文本。至少包括：

- `request_status`
- `approval_status`
- `grant_status`
- `session_status`
- `task_status`

状态迁移必须通过应用层服务完成，禁止直接在控制器中拼装 SQL 改状态。

## 7. API 开发方案

## 7.1 第一批接口

优先开发以下接口：

- `POST /permission-requests`
- `GET /permission-requests/{id}`
- `POST /permission-requests/{id}/evaluate`
- `POST /approvals/callback`
- `POST /grants/{id}/provision`

这一批接口能打通主链路。

## 7.2 第二批接口

- `POST /grants/{id}/renew`
- `POST /grants/{id}/revoke`
- `POST /delegations`
- `GET /audit-records`
- `POST /sessions/revoke`

这一批接口支撑续期、撤销、审计和会话治理。

## 7.3 控制器规范

- 控制器只做参数校验、鉴权、调用应用层和返回结果。
- 所有业务错误都使用统一错误码。
- 所有接口必须带 `request_id` 或可追踪日志上下文。
- 所有写接口都必须生成审计事件。

## 7.4 幂等规范

- 审批回调：按 `idempotency_key`
- 开通任务：按 `grant_id`
- 撤销任务：按 `global_session_id`
- 续期请求：按 `request_id + renew_round`

## 8. 模块开发顺序

## 8.1 Sprint 0：脚手架与基础设施

目标：

- 初始化代码仓库结构。
- 搭好 FastAPI、Next.js、PostgreSQL、Redis、Celery。
- 配置基础日志、中间件、环境变量和迁移工具。

交付物：

- 项目可启动。
- 本地 Docker Compose 可运行。
- 数据库迁移链路可执行。
- 健康检查接口可用。

## 8.2 Sprint 1：身份、委托与申请单

目标：

- 建立用户、Agent、委托、申请单的基础数据模型。
- 实现自然语言提交申请和申请单持久化。

交付物：

- `POST /permission-requests`
- `POST /delegations`
- `GET /permission-requests/{id}`
- `users/agents/delegations/requests` 基础表

验收标准：

- 用户可以提交自然语言申请。
- 系统可以创建申请单并保存原文。
- 系统可以校验 Agent 是否有代办资格。

## 8.3 Sprint 2：意图解析、最小权限与风险分级

目标：

- 实现自然语言解析。
- 实现资源/动作映射。
- 实现最小权限建议。
- 实现风险分级与审批链推荐。

交付物：

- `POST /permission-requests/{id}/evaluate`
- `policy` 配置文件
- 解析结果落库

验收标准：

- “查看销售部 Q3 报表，但不需要修改”能被正确映射为只读权限建议。
- 系统能返回风险等级和建议审批链。

## 8.4 Sprint 3：审批与自动开通

目标：

- 接入飞书审批。
- 接入飞书文档/报表只读权限开通连接器。
- 贯通“审批通过 != 已开通”状态机。

交付物：

- `POST /approvals/callback`
- `POST /grants/{id}/provision`
- `approval_records`、`access_grants`

验收标准：

- 飞书审批通过后能自动开通权限。
- 连接器失败时状态显示为“已批准未生效”或失败，而不是错误地显示为已开通。

## 8.5 Sprint 4：续期、回收与会话治理

目标：

- 实现到期提醒。
- 实现续期。
- 实现自动回收。
- 实现会话撤销主流程。

交付物：

- `POST /grants/{id}/renew`
- `POST /grants/{id}/revoke`
- 定时任务和 `session_contexts`

验收标准：

- 即将到期的授权能生成提醒。
- 用户能发起续期。
- 到期授权能自动回收。
- Agent 停用后相关会话进入撤销流程。

## 8.6 Sprint 5：审计、后台与异常补偿

目标：

- 完善审计链。
- 完善管理员后台。
- 实现补偿任务和异常处理页面。

交付物：

- `GET /audit-records`
- 管理员后台页面
- 补偿任务页面

验收标准：

- 能查询一条完整申请链路。
- IT 管理员能看到开通失败任务并发起补偿。
- 安全管理员能看到撤销失败和高风险事件。

## 9. 开发责任拆分

若按 3 到 4 人小组开发，建议按以下边界拆分：

### 9.1 后端主链路负责人

负责：

- `permission_requests`
- `workflow`
- `approval_records`
- 状态机与事件流

### 9.2 策略与 Agent 负责人

负责：

- `PermissionAssistantAgent`
- 解析逻辑
- 最小权限规则
- 风险分级规则

### 9.3 连接器与会话负责人

负责：

- Feishu connector
- 授权开通/续期/撤销
- Session Authority
- 补偿任务

### 9.4 前端与后台负责人

负责：

- 员工申请页
- 申请详情页
- 管理员后台
- 异常补偿页

## 10. 测试开发文档

## 10.1 单元测试范围

- 委托校验逻辑
- 状态机迁移逻辑
- 最小权限映射逻辑
- 风险分级逻辑
- 审批链生成逻辑
- 撤销状态机逻辑

## 10.2 集成测试范围

- 提交申请 -> 评估 -> 审批 -> 开通
- 审批回调幂等
- 开通失败补偿
- 到期提醒 -> 续期
- 撤销 -> 会话同步

## 10.3 端到端测试范围

至少覆盖以下场景：

1. 同部门员工申请销售 Q3 报表只读权限。
2. 跨部门员工申请高敏资源访问。
3. 审批通过但飞书开通失败。
4. 授权到期后自动回收。
5. Agent 被停用后撤销生效。

## 10.4 Mock 策略

- 本地开发阶段使用假的飞书审批回调和假的连接器响应。
- 集成测试阶段提供 `mock-feishu` 服务。
- 生产前联调切换到真实飞书沙箱环境。

## 11. 编码规范

### 11.1 领域模型优先

- 所有状态、枚举、关键实体定义在 `packages/domain`。
- 控制器、任务、连接器不得自行发明状态值。

### 11.2 审计优先

- 所有写操作必须生成审计事件。
- 所有安全关键动作都要记录前态、后态和触发原因。

### 11.3 显式错误优先

- 禁止吞异常。
- 外部接口失败必须记录错误码、请求 ID、重试次数。

### 11.4 配置优先

- 资源映射、风险规则和审批规则尽量以配置管理。
- 仅在极少数必须场景中写死在代码内。

### 11.5 安全边界优先

- Agent 只能调应用服务，不得直接调连接器。
- 连接器只能通过 Provisioning Service 执行。
- 审批结果只能由 Approval Adapter 写入。

## 12. 部署与联调

## 12.1 开发环境

- 本地使用 Docker Compose 起 `postgres + redis + api + worker + web`
- 使用 mock 的飞书服务和本地 SSO stub

## 12.2 测试环境

- 接入真实数据库和 Redis
- 接入飞书测试环境
- 开启真实审批回调联调

## 12.3 生产前检查清单

- 所有状态机枚举已冻结。
- 风险规则和最小权限映射表已审校。
- 审批回调签名校验通过。
- 开通接口具备幂等控制。
- 撤销主链路已压测。
- 审计日志可查询。

## 13. Definition of Done

一个开发任务完成，至少满足：

1. 代码合入主分支前通过 lint 与单元测试。
2. 关键业务逻辑有测试覆盖。
3. 新接口有请求/响应示例。
4. 涉及状态机变更时已更新枚举和文档。
5. 涉及写操作时已补审计事件。
6. 涉及运维告警时已补监控项。

## 14. 当前待开发前确认事项

以下事项建议在正式进入开发前确认：

- 飞书“报表”和“文档”的真实资源模型与 scope 对照表。
- 默认 7 天有效期是否适用于所有普通只读权限。
- 低风险是否允许全自动批准，还是仍需主管确认。
- IT 管理员的补偿操作是否需要二次确认。
- 管理员后台先做最小版还是直接做完整看板。

## 15. 建议下一步动作

建议立刻执行以下动作：

1. 初始化仓库目录和基础工程。
2. 建第一批数据库迁移。
3. 定义核心枚举和状态机。
4. 先实现申请单主链路和假审批/假连接器。
5. 打通最小 E2E 场景后，再接飞书真实联调。
