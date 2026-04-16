# TASK-001 仓库脚手架与目录骨架

| 字段 | 内容 |
| --- | --- |
| Task ID | `TASK-001` |
| 阶段 | Gate 0 |
| 状态来源 | `docs/tasks/TODO.md` |
| 依赖 | 无 |
| 参考文档 | `docs/agent-identity-permission-development-guide.md` |
| 建议写入范围 | 仓库根目录基础工程文件、目录占位文件、`apps/`、`packages/`、`tests/`、`docker/` 的骨架初始化 |
| 禁止改动范围 | 四份冻结基线文档、具体业务实现文件、已被其他任务领取的专属模块 |

## 任务目标

初始化单仓多应用目录结构，为后续 API、Worker、Web、共享包和测试目录提供统一落点。

## 范围

- 创建 `apps/api`、`apps/worker`、`apps/web`
- 创建 `packages/domain`、`packages/application`、`packages/infrastructure`、`packages/policy`、`packages/prompts`、`packages/audit`
- 创建 `migrations`、`tests/unit`、`tests/integration`、`tests/e2e`、`docker`
- 创建根级基础工程文件，例如 Python 工程文件、Node 工程文件或工作区配置

## 不在范围

- 具体业务逻辑
- 接口实现
- 连接器实现

## 交付物

- 可见的目录骨架
- 根工程配置文件
- 基础忽略文件与脚本入口占位

## 完成定义

- 目录结构与开发实施文档一致
- 后续任务可以在固定路径继续开发
- 不修改四份冻结基线文档

## 协作要求

- 开始前更新 `docs/tasks/TODO.md`
- 完成后在总表备注中写明新增目录与工程文件
