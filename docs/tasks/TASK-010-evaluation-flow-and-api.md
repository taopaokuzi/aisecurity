# TASK-010 评估流程与 Evaluate API

| 字段 | 内容 |
| --- | --- |
| Task ID | `TASK-010` |
| 阶段 | Gate 2 |
| 状态来源 | `docs/tasks/TODO.md` |
| 依赖 | `TASK-007`, `TASK-009` |
| 参考文档 | `docs/agent-identity-permission-api-spec.md`, `docs/agent-identity-permission-state-machine.md` |
| 建议写入范围 | 评估流程相关的 `packages/application/**`、`apps/api/**`、`packages/infrastructure/**` 与测试 |
| 禁止改动范围 | 四份冻结基线文档、审批回调、连接器开通、前端页面 |

## 任务目标

实现申请评估主流程，把自然语言申请转成结构化结果、最小权限建议、风险等级和审批链。

## 范围

- `POST /permission-requests/{id}/evaluate`
- `GET /permission-requests/{id}/evaluation`
- 结构化解析结果落库
- `policy_version` 回写
- 评估相关状态迁移与事件

## 交付物

- 评估服务
- 评估 API
- 正常、模糊、跨部门、高敏场景测试

## 完成定义

- 评估成功后申请进入 `PendingApproval`
- 主案例输出只读权限建议
- 数据库中可查询评估结果与策略版本

## 协作要求

- 审批任务只能依赖本任务产出的结构化评估结果
