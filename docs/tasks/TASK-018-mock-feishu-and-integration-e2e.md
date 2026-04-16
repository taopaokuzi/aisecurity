# TASK-018 Mock Feishu 与集成 / E2E 用例

| 字段 | 内容 |
| --- | --- |
| Task ID | `TASK-018` |
| 阶段 | Gate 6 |
| 状态来源 | `docs/tasks/TODO.md` |
| 依赖 | `TASK-011`, `TASK-012`, `TASK-013`, `TASK-014` |
| 参考文档 | `docs/agent-identity-permission-integration-spec.md`, `docs/agent-identity-permission-development-guide.md` |
| 建议写入范围 | `tests/integration/**`、`tests/e2e/**`、Mock 服务文件、必要的测试脚本和联调配置 |
| 禁止改动范围 | 四份冻结基线文档、核心业务逻辑的大范围重构、员工端和管理端页面结构性改造 |

## 任务目标

提供本地和测试环境联调所需的 Mock Feishu，并补齐审批、开通、续期、撤销的集成与 E2E 用例。

## 范围

- `mock-feishu` 服务
- 审批通过 / 驳回 / 重复回调模拟
- 开通成功 / 失败 / 延迟生效模拟
- 自动回收与撤销失败模拟
- 集成测试与 E2E 场景

## 交付物

- Mock 服务
- 集成测试
- 端到端测试脚本

## 完成定义

- 五个核心业务场景至少可在 mock 环境复现
- 审批、开通、撤销、补偿的关键异常有自动化验证

## 协作要求

- Mock 协议字段尽量贴近真实飞书适配层
