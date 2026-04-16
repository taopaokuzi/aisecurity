# TASK-014 Session Authority 与撤销链路

| 字段 | 内容 |
| --- | --- |
| Task ID | `TASK-014` |
| 阶段 | Gate 4 |
| 状态来源 | `docs/tasks/TODO.md` |
| 依赖 | `TASK-012` |
| 参考文档 | `docs/agent-identity-permission-api-spec.md`, `docs/agent-identity-permission-state-machine.md`, `docs/agent-identity-permission-database-design.md` |
| 建议写入范围 | `session_contexts` 相关模型、`packages/application/**`、`packages/infrastructure/**`、撤销 Worker 与会话 API |
| 禁止改动范围 | 四份冻结基线文档、前端页面、与评估逻辑无关的策略规则定义 |

## 任务目标

建立全局会话模型和撤销流程，支持 Agent 停用、授权到期、人工撤销后的会话同步。

## 范围

- `session_contexts`
- `POST /sessions/revoke`
- Agent 停用后的联动撤销
- grant revoke 与 session revoke 协同
- 撤销失败重试与补偿

## 交付物

- Session Authority 服务
- 会话表迁移与仓储
- 撤销链路测试

## 完成定义

- 高风险调用前可检查会话状态
- 撤销失败进入 `SyncFailed` 或等价状态
- 会话与授权链路关联清晰

## 协作要求

- 补偿任务与告警入口要为运维侧保留
