# TASK-012 Provisioning Service 与飞书连接器

| 字段 | 内容 |
| --- | --- |
| Task ID | `TASK-012` |
| 阶段 | Gate 3 |
| 状态来源 | `docs/tasks/TODO.md` |
| 依赖 | `TASK-011` |
| 参考文档 | `docs/agent-identity-permission-api-spec.md`, `docs/agent-identity-permission-integration-spec.md`, `docs/agent-identity-permission-state-machine.md` |
| 建议写入范围 | 开通与连接器相关的 `packages/application/**`、`packages/infrastructure/**`、`apps/api/**`、Worker 任务文件 |
| 禁止改动范围 | 四份冻结基线文档、员工端与管理端页面、与本任务无关的策略规则定义 |

## 任务目标

实现审批通过后的自动开通流程，完成授权记录创建、连接器调用和状态回写。

## 范围

- `POST /grants/{id}/provision`
- Provisioning Service
- Feishu 文档/报表只读权限连接器
- `access_grants`、`connector_tasks` 状态流转

## 交付物

- 授权开通服务
- Feishu Connector
- 开通成功、受理成功、失败、重试测试

## 完成定义

- “已批准未生效”与“已生效”有清晰状态区分
- 开通失败时不误报为 `Active`
- grant 与 connector task 可追踪

## 协作要求

- Agent 不得直接调用连接器
