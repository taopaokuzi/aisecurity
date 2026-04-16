# API 接口文档

## 给 AI 发通行证：Agent 身份与权限系统 V1

| 项目 | 内容 |
| --- | --- |
| 文档名称 | Agent 身份与权限系统 API 接口文档 |
| 文档标识 | `docs/agent-identity-permission-api-spec.md` |
| 当前版本 | V1.0 |
| 文档状态 | Active |
| 生效日期 | 2026-04-16 |
| 对应基线 | `docs/agent-identity-permission-prd.md` / `docs/agent-identity-permission-srs.md` / `docs/agent-identity-permission-technical-design.md` / `docs/agent-identity-permission-development-guide.md` |
| 适用范围 | V1 对外 API、内部管理 API、审批回调 API、授权生命周期 API |

## 1. 文档目标

本文档定义 V1 阶段的接口契约，目标是为后端开发、前端联调、测试编写、审批回调接入和连接器实现提供统一输入。本文档重点回答以下问题：

- 系统提供哪些接口。
- 每个接口由谁调用。
- 请求和响应的数据结构如何定义。
- 状态、错误码、幂等键和审计要求如何统一。
- 审批回调、开通、续期、撤销等安全关键接口如何设计。

## 2. 接口设计原则

### 2.1 风格与协议

- 接口风格以 REST 为主。
- 请求与响应统一使用 `application/json`。
- 时间字段统一使用 UTC ISO 8601，例如 `2026-04-16T09:30:00Z`。
- 所有写接口必须具备可追踪的 `X-Request-Id`。
- 所有高风险写接口必须生成审计事件。

### 2.2 返回规范

成功响应使用业务字段直出，并附带追踪字段：

```json
{
  "request_id": "req_trace_001",
  "data": {
    "status": "Submitted"
  }
}
```

错误响应统一结构：

```json
{
  "request_id": "req_trace_001",
  "error": {
    "code": "DELEGATION_INVALID",
    "message": "Delegation is expired or revoked",
    "details": {
      "delegation_id": "dlg_123"
    }
  }
}
```

### 2.3 分页规范

列表接口使用游标或页码分页。V1 默认采用页码分页：

- `page`：从 `1` 开始
- `page_size`：默认 `20`，最大 `100`

分页响应示例：

```json
{
  "request_id": "req_trace_002",
  "data": {
    "items": [],
    "page": 1,
    "page_size": 20,
    "total": 0
  }
}
```

### 2.4 幂等规范

- 用户侧写接口支持 `Idempotency-Key` 请求头。
- 审批回调按 `idempotency_key` 去重。
- 开通任务按 `grant_id` 去重。
- 撤销任务按 `global_session_id` 去重。
- 续期请求按 `request_id + renew_round` 去重。

### 2.5 追踪规范

所有接口统一支持以下请求头：

- `X-Request-Id`：调用方请求 ID，必传。
- `X-Trace-Id`：链路追踪 ID，可选。
- `Idempotency-Key`：写接口幂等键，可选或按接口要求必传。

## 3. 鉴权与身份上下文

### 3.1 调用方分类

| 调用方 | 鉴权方式 | 典型接口 |
| --- | --- | --- |
| 普通员工 | 企业 SSO Session 或 Bearer Token | `POST /permission-requests` |
| 管理员 / 安全管理员 / IT 管理员 | 企业 SSO Session 或 Bearer Token + 角色校验 | `GET /audit-records` |
| 系统内部 Worker | 内部服务身份或服务间签名 | `POST /grants/{id}/provision` |
| 飞书审批回调 | 回调签名 + 来源校验 + 幂等校验 | `POST /approvals/callback` |

### 3.2 身份上下文字段

与权限自助服务 Agent 相关的上下文统一为：

- `user_id`：登录用户 ID
- `agent_id`：发起代办的 Agent 标识
- `delegation_id`：用户委托凭证 ID
- `conversation_id`：可选，会话 ID
- `operator_type`：`User` / `Agent` / `Approver` / `ITAdmin` / `System`

### 3.3 角色访问边界

| 接口分组 | 普通员工 | 审批人 | IT 管理员 | 安全管理员 | Worker / 系统 |
| --- | --- | --- | --- | --- | --- |
| 委托 | 可创建/查询本人 | 否 | 查询 | 查询 | 否 |
| 申请单 | 可创建/查询本人 | 可查询待审批相关 | 查询 | 查询 | 调用评估/编排 |
| 审批回调 | 否 | 否 | 否 | 否 | 飞书回调 |
| 开通/续期/撤销 | 续期/撤销本人相关 | 否 | 可补偿/撤销 | 可查询/干预高风险 | Worker |
| 审计 | 否 | 否 | 查询运维相关 | 查询全量安全相关 | 生成 |

## 4. 通用数据结构

### 4.1 PermissionRequest

```json
{
  "request_id": "req_123",
  "user_id": "user_001",
  "agent_id": "agent_perm_assistant_v1",
  "delegation_id": "dlg_123",
  "raw_text": "我需要查看销售部Q3报表，但不需要修改权限",
  "resource_key": "sales.q3_report",
  "resource_type": "report",
  "action": "read",
  "requested_duration": "P7D",
  "suggested_permission": "report:sales.q3:read",
  "risk_level": "Low",
  "approval_status": "Pending",
  "grant_status": "NotCreated",
  "request_status": "PendingApproval",
  "policy_version": "perm-map.v1",
  "created_at": "2026-04-16T09:30:00Z",
  "updated_at": "2026-04-16T09:32:00Z"
}
```

### 4.2 DelegationCredential

```json
{
  "delegation_id": "dlg_123",
  "user_id": "user_001",
  "agent_id": "agent_perm_assistant_v1",
  "task_scope": "permission_self_service",
  "scope": {
    "resource_types": ["report", "doc"],
    "allowed_actions": ["read", "request_edit"]
  },
  "issued_at": "2026-04-16T09:20:00Z",
  "expire_at": "2026-04-23T09:20:00Z",
  "delegation_status": "Active"
}
```

### 4.3 ApprovalRecord

```json
{
  "approval_id": "apr_001",
  "request_id": "req_123",
  "external_approval_id": "feishu_apr_998",
  "approval_node": "manager",
  "approver_id": "user_mgr_001",
  "approval_status": "Pending",
  "submitted_at": "2026-04-16T09:33:00Z"
}
```

### 4.4 AccessGrant

```json
{
  "grant_id": "grt_001",
  "request_id": "req_123",
  "resource_key": "sales.q3_report",
  "action": "read",
  "grant_status": "Provisioning",
  "connector_status": "Accepted",
  "effective_at": null,
  "expire_at": "2026-04-23T09:33:00Z"
}
```

### 4.5 SessionContext

```json
{
  "global_session_id": "gs_001",
  "request_id": "req_123",
  "agent_id": "agent_perm_assistant_v1",
  "user_id": "user_001",
  "session_status": "Active"
}
```

### 4.6 AuditRecord

```json
{
  "audit_id": "aud_001",
  "request_id": "req_123",
  "event_type": "grant.provisioned",
  "actor_type": "System",
  "actor_id": "worker_01",
  "result": "Success",
  "created_at": "2026-04-16T09:35:00Z"
}
```

## 5. 状态与枚举

### 5.1 request_status

- `Draft`
- `Submitted`
- `Evaluating`
- `PendingApproval`
- `Approved`
- `Provisioning`
- `Active`
- `Expiring`
- `Expired`
- `Revoked`
- `Failed`

### 5.2 approval_status

- `NotRequired`
- `Pending`
- `Approved`
- `Rejected`
- `Withdrawn`
- `Expired`
- `CallbackFailed`

### 5.3 grant_status

- `NotCreated`
- `ProvisioningRequested`
- `Provisioning`
- `Active`
- `Expiring`
- `Expired`
- `Revoking`
- `Revoked`
- `ProvisionFailed`
- `RevokeFailed`

### 5.4 session_status

- `Active`
- `Revoking`
- `Revoked`
- `Syncing`
- `SyncFailed`
- `Expired`

### 5.5 risk_level

- `Low`
- `Medium`
- `High`
- `Critical`

### 5.6 operator_type / actor_type

- `User`
- `Agent`
- `Approver`
- `ITAdmin`
- `SecurityAdmin`
- `System`

## 6. 核心接口总览

| 分组 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| 委托 | `POST` | `/delegations` | 创建委托凭证 |
| 委托 | `GET` | `/delegations/{id}` | 查询委托凭证 |
| Agent 管理 | `POST` | `/agents/{id}/disable` | 停用 Agent 并触发撤销 |
| 申请单 | `POST` | `/permission-requests` | 提交自然语言申请 |
| 申请单 | `GET` | `/permission-requests/{id}` | 查询申请详情 |
| 申请单 | `GET` | `/permission-requests` | 分页查询申请单 |
| 评估 | `POST` | `/permission-requests/{id}/evaluate` | 执行评估 |
| 评估 | `GET` | `/permission-requests/{id}/evaluation` | 查询评估结果 |
| 审批 | `POST` | `/approvals/callback` | 审批回调 |
| 审批 | `GET` | `/permission-requests/{id}/approvals` | 查询审批记录 |
| 授权 | `POST` | `/grants/{id}/provision` | 发起开通 |
| 授权 | `GET` | `/grants/{id}` | 查询授权详情 |
| 授权 | `GET` | `/permission-requests/{id}/grants` | 查询申请相关授权 |
| 生命周期 | `POST` | `/grants/{id}/renew` | 发起续期 |
| 生命周期 | `POST` | `/grants/{id}/revoke` | 发起撤销 |
| 会话 | `POST` | `/sessions/revoke` | 发起会话撤销 |
| 审计 | `GET` | `/audit-records` | 查询审计记录 |
| 后台 | `GET` | `/admin/failed-tasks` | 查询失败任务 |
| 后台 | `POST` | `/admin/connector-tasks/{id}/retry` | 发起补偿重试 |

## 7. 接口明细

### 7.1 POST /delegations

**调用方**

- 员工端

**说明**

创建用户到权限自助服务 Agent 的委托凭证。

**Request Body**

```json
{
  "agent_id": "agent_perm_assistant_v1",
  "task_scope": "permission_self_service",
  "scope": {
    "resource_types": ["report", "doc"],
    "allowed_actions": ["read", "request_edit"]
  },
  "expire_at": "2026-04-23T09:20:00Z"
}
```

**响应**

```json
{
  "request_id": "req_trace_101",
  "data": {
    "delegation_id": "dlg_123",
    "delegation_status": "Active",
    "issued_at": "2026-04-16T09:20:00Z",
    "expire_at": "2026-04-23T09:20:00Z"
  }
}
```

**错误码**

- `AGENT_DISABLED`
- `DELEGATION_SCOPE_INVALID`
- `DELEGATION_EXPIRE_AT_INVALID`

**幂等规则**

- 相同 `Idempotency-Key` 的重复创建返回同一条委托记录。

**审计要求**

- 写入 `delegation.created`

### 7.2 GET /delegations/{id}

**调用方**

- 委托创建者
- 管理员

**响应字段**

- `delegation_id`
- `user_id`
- `agent_id`
- `task_scope`
- `scope`
- `delegation_status`
- `issued_at`
- `expire_at`
- `revoked_at`

### 7.3 POST /agents/{id}/disable

**调用方**

- IT 管理员

**说明**

停用 Agent 并触发所有相关活动会话与授权的撤销流程。

**Request Body**

```json
{
  "reason": "Security suspension",
  "cascade_revoke": true
}
```

**响应**

```json
{
  "request_id": "req_trace_102",
  "data": {
    "agent_id": "agent_perm_assistant_v1",
    "agent_status": "Disabled",
    "revoke_job_created": true
  }
}
```

### 7.4 POST /permission-requests

**调用方**

- 员工端
- Agent BFF

**说明**

提交自然语言权限申请，并创建申请主记录。

**Request Body**

```json
{
  "message": "我需要查看销售部Q3报表，但不需要修改权限",
  "agent_id": "agent_perm_assistant_v1",
  "delegation_id": "dlg_123",
  "conversation_id": "conv_001"
}
```

**响应**

```json
{
  "request_id": "req_trace_103",
  "data": {
    "permission_request_id": "req_123",
    "request_status": "Submitted",
    "next_action": "Evaluating"
  }
}
```

**错误码**

- `DELEGATION_INVALID`
- `AGENT_DISABLED`
- `REQUEST_MESSAGE_EMPTY`

**审计要求**

- 写入 `request.submitted`

### 7.5 GET /permission-requests/{id}

**调用方**

- 申请人
- 管理员
- 相关审批人

**响应**

```json
{
  "request_id": "req_trace_104",
  "data": {
    "request_id": "req_123",
    "user_id": "user_001",
    "agent_id": "agent_perm_assistant_v1",
    "delegation_id": "dlg_123",
    "raw_text": "我需要查看销售部Q3报表，但不需要修改权限",
    "resource_key": "sales.q3_report",
    "resource_type": "report",
    "action": "read",
    "suggested_permission": "report:sales.q3:read",
    "risk_level": "Low",
    "approval_status": "Pending",
    "grant_status": "NotCreated",
    "request_status": "PendingApproval",
    "policy_version": "perm-map.v1",
    "created_at": "2026-04-16T09:30:00Z",
    "updated_at": "2026-04-16T09:32:00Z"
  }
}
```

### 7.6 GET /permission-requests

**支持查询参数**

- `page`
- `page_size`
- `request_status`
- `approval_status`
- `risk_level`
- `created_from`
- `created_to`
- `mine_only`

### 7.7 POST /permission-requests/{id}/evaluate

**调用方**

- 系统内部
- Worker

**说明**

执行自然语言解析、最小权限映射、风险分级和审批链推荐。

**Request Body**

```json
{
  "force_re_evaluate": false
}
```

**响应**

```json
{
  "request_id": "req_trace_105",
  "data": {
    "request_id": "req_123",
    "resource_key": "sales.q3_report",
    "resource_type": "report",
    "action": "read",
    "requested_duration": "P7D",
    "suggested_permission": "report:sales.q3:read",
    "risk_level": "Low",
    "approval_route": ["manager"],
    "policy_version": "perm-map.v1",
    "request_status": "PendingApproval"
  }
}
```

**错误码**

- `REQUEST_STATUS_INVALID`
- `POLICY_MAPPING_NOT_FOUND`
- `RISK_EVALUATION_FAILED`

**审计要求**

- 写入 `request.evaluated`

### 7.8 GET /permission-requests/{id}/evaluation

**返回字段**

- 结构化解析结果
- 最小权限建议
- 风险等级
- 审批链建议
- `policy_version`
- 评估时间

### 7.9 POST /approvals/callback

**调用方**

- 飞书审批回调

**请求头**

- `X-Feishu-Signature`
- `X-Feishu-Timestamp`
- `X-Feishu-Request-Id`

**Request Body**

```json
{
  "external_approval_id": "feishu_apr_998",
  "request_id": "req_123",
  "approval_status": "Approved",
  "approval_node": "manager",
  "approver_id": "user_mgr_001",
  "decision_at": "2026-04-16T09:34:00Z",
  "idempotency_key": "feishu_cb_001",
  "payload": {
    "raw": "provider callback payload"
  }
}
```

**响应**

```json
{
  "request_id": "req_trace_106",
  "data": {
    "accepted": true,
    "approval_status": "Approved"
  }
}
```

**错误码**

- `CALLBACK_SIGNATURE_INVALID`
- `CALLBACK_SOURCE_INVALID`
- `CALLBACK_DUPLICATED`
- `APPROVAL_RECORD_NOT_FOUND`

**幂等规则**

- 按 `idempotency_key` 唯一处理。

**审计要求**

- 写入 `approval.callback_received`
- 写入 `approval.approved` 或 `approval.rejected`

### 7.10 GET /permission-requests/{id}/approvals

**返回字段**

- `approval_id`
- `external_approval_id`
- `approval_node`
- `approver_id`
- `approval_status`
- `submitted_at`
- `approved_at`
- `rejected_at`

### 7.11 POST /grants/{id}/provision

**调用方**

- Worker
- 编排服务

**说明**

依据审批结果和策略二次校验结果发起授权开通。

**Request Body**

```json
{
  "request_id": "req_123",
  "policy_version": "perm-map.v1",
  "delegation_id": "dlg_123",
  "force_retry": false
}
```

**响应**

```json
{
  "request_id": "req_trace_107",
  "data": {
    "grant_id": "grt_001",
    "grant_status": "Provisioning",
    "connector_status": "Accepted"
  }
}
```

**错误码**

- `APPROVAL_NOT_APPROVED`
- `GRANT_ALREADY_ACTIVE`
- `PROVISION_POLICY_RECHECK_FAILED`
- `CONNECTOR_UNAVAILABLE`

**审计要求**

- 写入 `grant.provisioning_requested`

### 7.12 GET /grants/{id}

**响应字段**

- `grant_id`
- `request_id`
- `resource_key`
- `action`
- `grant_status`
- `connector_status`
- `effective_at`
- `expire_at`
- `revoked_at`
- `reconcile_status`

### 7.13 GET /permission-requests/{id}/grants

**说明**

查询某一申请单关联的授权记录，V1 默认一个申请单对应一条主授权记录，后续可扩展多条。

### 7.14 POST /grants/{id}/renew

**调用方**

- 申请人
- 管理员

**Request Body**

```json
{
  "requested_duration": "P7D",
  "reason": "项目仍在进行，需要继续查看"
}
```

**响应**

```json
{
  "request_id": "req_trace_108",
  "data": {
    "grant_id": "grt_001",
    "renew_round": 1,
    "request_status": "PendingApproval"
  }
}
```

### 7.15 POST /grants/{id}/revoke

**调用方**

- 申请人
- IT 管理员
- 安全管理员
- 系统自动任务

**Request Body**

```json
{
  "reason": "Access no longer needed",
  "trigger_source": "User"
}
```

**响应**

```json
{
  "request_id": "req_trace_109",
  "data": {
    "grant_id": "grt_001",
    "grant_status": "Revoking"
  }
}
```

### 7.16 POST /sessions/revoke

**调用方**

- 系统
- 安全管理员

**Request Body**

```json
{
  "global_session_id": "gs_001",
  "reason": "Agent disabled",
  "cascade_connector_sessions": true
}
```

**响应**

```json
{
  "request_id": "req_trace_110",
  "data": {
    "global_session_id": "gs_001",
    "session_status": "Revoking"
  }
}
```

### 7.17 GET /audit-records

**调用方**

- 安全管理员
- IT 管理员

**查询参数**

- `request_id`
- `event_type`
- `actor_type`
- `actor_id`
- `created_from`
- `created_to`
- `page`
- `page_size`

### 7.18 GET /admin/failed-tasks

**说明**

查询审批回调失败、开通失败、撤销失败、同步失败等异常任务。

**查询参数**

- `task_type`
- `task_status`
- `request_id`
- `grant_id`
- `page`
- `page_size`

### 7.19 POST /admin/connector-tasks/{id}/retry

**调用方**

- IT 管理员

**Request Body**

```json
{
  "reason": "Manual retry after credential refresh"
}
```

**审计要求**

- 写入 `connector.retry_requested`

## 8. 回调接口专项说明

### 8.1 回调处理顺序

审批回调处理必须遵循以下顺序：

1. 校验签名。
2. 校验时间戳和来源。
3. 校验幂等键。
4. 原始载荷落库。
5. 更新 `approval_records`。
6. 触发后续状态迁移。
7. 写审计事件。

### 8.2 回调响应规则

- 成功处理：返回 `200`。
- 已处理的重复回调：返回 `200`，并标记 `accepted=true`。
- 签名失败：返回 `401`。
- 来源非法：返回 `403`。
- 载荷不完整：返回 `400`。
- 内部暂时失败：返回 `500`，允许外部重试。

## 9. 错误码表

| 错误码 | 含义 |
| --- | --- |
| `UNAUTHORIZED` | 未认证 |
| `FORBIDDEN` | 无权限访问 |
| `DELEGATION_INVALID` | 委托失效、已过期或已撤销 |
| `AGENT_DISABLED` | Agent 已停用 |
| `REQUEST_MESSAGE_EMPTY` | 申请内容为空 |
| `REQUEST_STATUS_INVALID` | 当前申请状态不允许本操作 |
| `POLICY_MAPPING_NOT_FOUND` | 未找到最小权限映射规则 |
| `RISK_EVALUATION_FAILED` | 风险评估失败 |
| `CALLBACK_SIGNATURE_INVALID` | 回调签名不合法 |
| `CALLBACK_SOURCE_INVALID` | 回调来源不合法 |
| `CALLBACK_DUPLICATED` | 回调重复 |
| `APPROVAL_NOT_APPROVED` | 审批尚未通过 |
| `PROVISION_POLICY_RECHECK_FAILED` | 开通前策略复核失败 |
| `CONNECTOR_UNAVAILABLE` | 外部连接器不可用 |
| `SESSION_ALREADY_REVOKED` | 会话已撤销 |
| `RETRY_NOT_ALLOWED` | 当前失败任务不允许重试 |

## 10. 联调说明

### 10.1 第一批必须可用接口

- `POST /delegations`
- `POST /permission-requests`
- `GET /permission-requests/{id}`
- `POST /permission-requests/{id}/evaluate`
- `POST /approvals/callback`
- `POST /grants/{id}/provision`

### 10.2 本地联调建议

- 本地开发默认使用 `mock-feishu`。
- 前端在 Gate 0 到 Gate 2 阶段可先使用固定用户上下文。
- 审批回调与开通接口由测试脚本或 mock 服务驱动。

### 10.3 验证重点

- 主案例是否能从提交一路推进到审批与开通。
- “审批通过不等于已生效”是否在 API 层有清晰表达。
- 失败与补偿接口是否可观测、可重试、可审计。
