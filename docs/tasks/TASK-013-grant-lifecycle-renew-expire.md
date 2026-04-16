# TASK-013 授权生命周期：提醒、续期、过期回收

| 字段 | 内容 |
| --- | --- |
| Task ID | `TASK-013` |
| 阶段 | Gate 4 |
| 状态来源 | `docs/tasks/TODO.md` |
| 依赖 | `TASK-012` |
| 参考文档 | `docs/agent-identity-permission-api-spec.md`, `docs/agent-identity-permission-state-machine.md` |
| 建议写入范围 | 授权生命周期相关的 `packages/application/**`、`apps/api/**`、Worker 定时任务、通知任务文件 |
| 禁止改动范围 | 四份冻结基线文档、管理后台页面、审批回调适配逻辑 |

## 任务目标

实现授权到期提醒、续期申请和自动回收主流程。

## 范围

- `POST /grants/{id}/renew`
- 到期提醒任务
- 过期自动回收任务
- grant 生命周期状态迁移

## 交付物

- 续期服务
- 定时任务
- 提醒与过期处理测试

## 完成定义

- 即将到期的授权能进入 `Expiring`
- 用户可发起续期
- 到期授权可自动回收并进入 `Expired`

## 协作要求

- 若续期涉及重新审批，应显式复用申请单主链路
