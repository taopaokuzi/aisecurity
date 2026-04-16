# TASK-011 Approval Adapter 与审批回调

| 字段 | 内容 |
| --- | --- |
| Task ID | `TASK-011` |
| 阶段 | Gate 3 |
| 状态来源 | `docs/tasks/TODO.md` |
| 依赖 | `TASK-010` |
| 参考文档 | `docs/agent-identity-permission-api-spec.md`, `docs/agent-identity-permission-integration-spec.md`, `docs/agent-identity-permission-state-machine.md` |
| 建议写入范围 | 审批适配与回调相关的 `packages/application/**`、`packages/infrastructure/**`、`apps/api/**`、Worker 回调处理文件 |
| 禁止改动范围 | 四份冻结基线文档、前端页面、授权生命周期与会话治理实现 |

## 任务目标

实现审批发起、回调验签、幂等处理和审批状态映射。

## 范围

- 审批发起适配层
- `POST /approvals/callback`
- 回调签名校验、来源校验、幂等键处理
- `approval_records` 落库与状态迁移

## 交付物

- Approval Adapter
- 回调处理服务
- 回调与重复事件测试

## 完成定义

- 审批通过后仅更新审批状态，不直接把授权置为生效
- 重复回调不重复推进流程
- 回调原始载荷可追踪

## 协作要求

- 所有回调必须先落库再驱动后续动作
