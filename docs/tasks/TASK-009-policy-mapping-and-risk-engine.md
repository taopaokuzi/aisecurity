# TASK-009 策略映射与风险规则引擎

| 字段 | 内容 |
| --- | --- |
| Task ID | `TASK-009` |
| 阶段 | Gate 2 |
| 状态来源 | `docs/tasks/TODO.md` |
| 依赖 | `TASK-004`, `TASK-008` |
| 参考文档 | `docs/agent-identity-permission-api-spec.md`, `docs/agent-identity-permission-state-machine.md`, `docs/agent-identity-permission-development-guide.md` |
| 建议写入范围 | `packages/policy/**`、`config/policy/**`、评估规则相关测试 |
| 禁止改动范围 | 四份冻结基线文档、审批回调适配、前端页面实现 |

## 任务目标

建立资源识别、动作映射、最小权限建议、风险评分和审批链推荐规则。

## 范围

- `permission_mappings`
- `risk_rules`
- `approval_rules`
- 规则读取与版本化
- 规则优先于 LLM 的决策框架

## 交付物

- 策略配置文件
- 规则引擎或规则服务
- 规则测试样例

## 完成定义

- 主案例可稳定映射为只读权限建议
- 风险等级与审批链可解释
- 无法判定时默认走更安全路径

## 协作要求

- 后续评估流程必须复用本任务的规则结果和 `policy_version`
