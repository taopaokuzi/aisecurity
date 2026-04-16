# agent 协作入口

本文是小写文件名兼容入口，供只识别 `agent.md` 的运行器使用。

规范主文件为 [AGENT.md](./AGENT.md)。

如果当前运行器只读取本文，请至少遵守以下规则：

1. 先读 `docs/tasks/TODO.md`，再读对应的 `docs/tasks/TASK-xxx-*.md`
2. 任务状态唯一来源是 `docs/tasks/TODO.md`
3. 四份冻结基线文档不得修改：
   - `docs/agent-identity-permission-prd.md`
   - `docs/agent-identity-permission-srs.md`
   - `docs/agent-identity-permission-technical-design.md`
   - `docs/agent-identity-permission-development-guide.md`
4. 开始任务前先把 `实现状态` 改为 `IN_PROGRESS`
5. 只有当依赖任务满足 `DONE + PASS` 时，当前任务才允许启动
6. 完成实现后把 `实现状态` 改为 `DONE`，把 `验收状态` 改为 `PENDING`
7. 通过验收后再把 `验收状态` 改为 `PASS`
8. 修改前先看任务文件里的 `建议写入范围` 和 `禁止改动范围`
