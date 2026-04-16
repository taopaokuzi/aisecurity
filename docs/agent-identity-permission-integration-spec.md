# 外部集成文档

## 给 AI 发通行证：Agent 身份与权限系统 V1

| 项目 | 内容 |
| --- | --- |
| 文档名称 | Agent 身份与权限系统外部集成文档 |
| 文档标识 | `docs/agent-identity-permission-integration-spec.md` |
| 当前版本 | V1.0 |
| 文档状态 | Active |
| 生效日期 | 2026-04-16 |
| 对应基线 | `docs/agent-identity-permission-srs.md` / `docs/agent-identity-permission-technical-design.md` / `docs/agent-identity-permission-development-guide.md` |
| 适用范围 | IAM/SSO、飞书审批、飞书权限开通、回调安全、Mock 联调、错误补偿 |

## 1. 文档目标

本文档用于定义 V1 对外集成边界、接入方式、回调安全要求、错误补偿策略和本地联调约定，作为 Gate 3、Gate 4 实施依据。

## 2. 集成范围

### 2.1 V1 纳入范围

- 企业 IAM / SSO
- 飞书审批
- 飞书文档 / 报表类只读权限开通
- Redis / Celery 作为内部依赖
- `mock-feishu` 作为本地联调依赖

### 2.2 V1 不纳入范围

- 多租户联合身份互信
- 多连接器事务一致性
- 多 Agent 编排系统
- 所有企业系统的统一权限开通

## 3. 集成原则

1. Agent 不允许直接访问外部系统，必须通过应用服务或 Provisioning Service。
2. 外部回调必须遵循“验签 -> 幂等校验 -> 落库 -> 状态迁移”的顺序。
3. 外部异常不能直接推动内部状态跳到成功态。
4. 所有关键外部交互必须写审计。
5. 不可判定时按更安全路径处理，不默认放行。

## 4. 外部系统清单

| 集成对象 | 作用 | V1 状态 |
| --- | --- | --- |
| IAM / SSO | 用户认证与组织信息获取 | 必接 |
| Feishu Approval | 审批流外部承载 | 必接 |
| Feishu Permission Connector | 权限开通、续期、回收、撤销 | 必接 |
| Mock Feishu | 本地与测试环境模拟 | 必接 |

## 5. IAM / SSO 集成说明

### 5.1 目标

为系统提供员工身份、组织关系、主管信息和登录态校验。

### 5.2 输入

- 登录态 Token 或 Session
- 用户基本资料
- 部门信息
- 直属主管信息
- 用户启停状态

### 5.3 输出到平台的数据

同步到 `users` 表的字段至少包括：

- `user_id`
- `display_name`
- `email`
- `department_id`
- `department_name`
- `manager_user_id`
- `user_status`

### 5.4 同步策略

- 登录时懒同步基础信息
- 后台定时任务补齐组织变更
- 用户被禁用时，需触发相关委托、会话与授权的检查和撤销流程

## 6. 飞书审批集成

### 6.1 作用

承载 V1 的审批流程，输出审批结果回调。

### 6.2 发起审批时机

当申请完成评估，得到风险等级和审批链建议，且策略要求人工审批时，由 Workflow Orchestrator 调用 Approval Adapter 发起审批。

### 6.3 内部字段映射

| 内部字段 | 飞书审批单展示内容 |
| --- | --- |
| `request_id` | 申请单号 |
| `user_id` / `display_name` | 申请人 |
| `resource_key` / `resource_type` | 资源 |
| `action` | 目标动作 |
| `requested_duration` | 时效 |
| `risk_level` | 风险等级 |
| `suggested_permission` | 最小权限建议 |
| `human_readable_explanation` | 业务说明 |
| `approval_route` | 审批链 |

### 6.4 审批结果映射

| 飞书结果 | 内部 `approval_status` |
| --- | --- |
| 审批通过 | `Approved` |
| 审批驳回 | `Rejected` |
| 审批撤回 | `Withdrawn` |
| 审批超时 | `Expired` |
| 回调处理失败 | `CallbackFailed` |

### 6.5 回调契约

平台内部统一按以下字段接收回调，再由适配器做提供方差异转换：

```json
{
  "external_approval_id": "feishu_apr_998",
  "request_id": "req_123",
  "approval_status": "Approved",
  "approval_node": "manager",
  "approver_id": "user_mgr_001",
  "decision_at": "2026-04-16T09:34:00Z",
  "idempotency_key": "feishu_cb_001",
  "payload": {}
}
```

### 6.6 实施注意

- 审批通过后只更新 `approval_status=Approved`，不得直接置 `grant_status=Active`。
- 回调的原始载荷必须落库到 `approval_records.callback_payload_json`。
- 适配器必须保留提供方请求 ID，便于追溯。

## 7. 飞书权限开通集成

### 7.1 V1 支持范围

- 飞书文档只读权限
- 飞书报表只读权限

V1 不支持：

- 多系统混合开通
- 写权限自动开通
- 跨系统原子事务

### 7.2 开通发起时机

满足以下条件后由 Provisioning Service 发起：

1. 审批通过
2. 开通前二次策略校验通过
3. `request_status=Approved`
4. `grant_status` 允许进入开通

### 7.3 开通请求内部契约

```json
{
  "request_id": "req_123",
  "grant_id": "grt_001",
  "delegation_id": "dlg_123",
  "policy_version": "perm-map.v1",
  "resource_key": "sales.q3_report",
  "resource_type": "report",
  "action": "read",
  "expire_at": "2026-04-23T09:33:00Z"
}
```

### 7.4 开通结果建模

| 外部结果 | 内部含义 | 内部状态 |
| --- | --- | --- |
| 请求受理成功 | 外部已接单，未必生效 | `connector_status=Accepted`，`grant_status=Provisioning` |
| 实际生效成功 | 权限已生效 | `connector_status=Applied`，`grant_status=Active` |
| 可重试失败 | 可通过重试或补偿修复 | `connector_status=Failed`，`grant_status=ProvisionFailed` |
| 不可重试失败 | 需人工介入 | `connector_status=Failed`，`grant_status=ProvisionFailed` |
| 部分成功 | 视为失败并人工补偿 | `connector_status=Partial`，`grant_status=ProvisionFailed` |

### 7.5 续期、回收、撤销

- 续期：更新外部授权到期时间，成功后更新 `expire_at`
- 到期回收：由定时任务触发，调用连接器删除外部授权
- 人工撤销：管理员触发撤销任务
- Agent 停用：对相关活动授权发起批量撤销

## 8. 回调安全规范

### 8.1 通用要求

- 所有回调必须校验签名。
- 必须校验时间戳，防止重放。
- 必须校验来源信息。
- 必须使用幂等键落库去重。

### 8.2 处理顺序

1. 校验 `timestamp`
2. 校验签名
3. 校验来源
4. 检查幂等键
5. 落原始载荷
6. 更新业务状态
7. 写审计

### 8.3 失败响应规范

- 签名失败：`401`
- 来源不可信：`403`
- 请求格式错误：`400`
- 内部短暂失败：`500`

## 9. 错误处理与补偿策略

### 9.1 审批回调到达但内部落库失败

- 将审批状态标记为 `CallbackFailed`
- 原始回调写入失败日志或死信队列
- 允许后续人工重放

### 9.2 回调重复到达

- 识别到相同 `idempotency_key` 后直接返回成功
- 不重复推进状态机

### 9.3 开通接口超时

- 标记 `grant_status=Provisioning`
- 后续通过查询或补偿确认最终结果

### 9.4 开通受理成功但迟迟未生效

- 保持 `Provisioning`
- 建立对账或轮询任务
- 超出阈值后告警并进入人工补偿

### 9.5 回收失败或撤销失败

- `grant_status=RevokeFailed`
- `session_status=SyncFailed`
- 允许 IT 管理员重试

### 9.6 外部接口限流

- 记录限流错误码
- 延迟重试
- 达到阈值后告警

### 9.7 认证失效

- 任务进入失败态
- 阻断继续执行
- 通知 IT 管理员刷新凭证

## 10. Mock 联调方案

### 10.1 目标

在本地和测试环境模拟审批和权限开通，不依赖真实飞书环境即可完成主链路联调。

### 10.2 Mock 范围

- 审批创建成功
- 审批通过
- 审批驳回
- 重复回调
- 开通成功
- 开通失败
- 受理成功但延迟生效
- 撤销失败

### 10.3 联调约束

- 本地默认接 `mock-feishu`
- 测试环境先连 mock，再切飞书沙箱
- 接口字段与真实提供方适配层保持一致

## 11. 环境配置

| 变量名 | 说明 |
| --- | --- |
| `SSO_CLIENT_ID` | SSO Client ID |
| `SSO_CLIENT_SECRET` | SSO Client Secret |
| `FEISHU_APP_ID` | 飞书应用 ID |
| `FEISHU_APP_SECRET` | 飞书应用密钥 |
| `FEISHU_APPROVAL_BASE_URL` | 飞书审批基础地址 |
| `FEISHU_PERMISSION_BASE_URL` | 飞书权限接口基础地址 |
| `FEISHU_CALLBACK_SIGNING_SECRET` | 回调验签密钥 |
| `MOCK_FEISHU_BASE_URL` | Mock 服务地址 |

## 12. 集成测试场景

至少覆盖以下场景：

1. 审批通过后正常开通
2. 审批驳回
3. 审批回调重复
4. 开通失败后重试
5. 已批准未生效
6. 到期自动回收
7. Agent 停用触发撤销
8. 撤销失败后补偿

## 13. V1 已知限制

- 只支持一个 first-party Agent
- 只支持单层委托
- 只支持飞书审批
- 只支持飞书文档 / 报表类只读权限
- 不支持跨系统事务一致性

## 14. 最低完成标准

集成文档进入实施状态，至少需满足：

1. 审批创建与回调契约明确。
2. 开通、续期、回收、撤销的连接器契约明确。
3. 回调验签、来源校验、幂等规则明确。
4. 错误处理与补偿路径明确。
5. Mock 联调方案和环境变量清单明确。
