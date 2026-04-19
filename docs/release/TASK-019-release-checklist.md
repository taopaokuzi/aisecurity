# TASK-019 发布检查清单

- 任务：`TASK-019`
- 日期：`2026-04-19`
- 最终结论：`PASS WITH RISKS`
- 是否允许进入上线准备：`是，需满足生产身份注入条件`

## 1. 关键项核查

| 检查项 | 证据 | 结论 |
| --- | --- | --- |
| 状态机枚举已冻结并与实现一致 | `packages/domain/enums.py` 与 `tests/unit/test_domain_enums.py` 对 `Request/Approval/Grant/Session/Task` 全量枚举做断言；实现值与 `docs/agent-identity-permission-state-machine.md` 一致 | `PASS` |
| 风险规则和最小权限映射已审校 | `config/policy/permission_mappings.toml`、`config/policy/risk_rules.toml`、`config/policy/approval_rules.toml` 与 `tests/unit/test_policy_engine.py` 覆盖同部门只读、跨部门、高敏资源、兜底人工复核 | `PASS` |
| 审批回调签名校验通过 | `packages/infrastructure/approval_adapter.py` 实现 `timestamp + signature + source` 校验；`tests.integration.test_approval_callback_api::test_callback_rejects_invalid_signature` 通过 | `PASS` |
| 开通接口具备幂等控制 | `tests/unit/test_provisioning_service.py::test_duplicate_provision_request_returns_existing_state_without_new_task` 验证重复开通不重复建任务；失败后 `force_retry` 走显式重试分支 | `PASS` |
| 撤销链路已验证 | `tests.integration.test_session_revoke_api`、`tests.integration.test_worker_session_revoke_task`、`tests.integration.test_feishu_flow_integration`、`tests/e2e/test_permission_workflows_e2e.py` 覆盖人工撤销、到期回收、Agent 停用撤销、撤销失败补偿 | `PASS` |
| 审计日志可查询 | `apps/api/audit_records.py` 提供 `GET /audit-records`；`tests.integration.test_audit_admin_api` 校验单链路查询、分页、失败任务查询与补偿重试 | `PASS` |

## 2. 核心场景结论

| 场景 | 结果 | 说明 |
| --- | --- | --- |
| 同部门员工申请销售 Q3 报表只读权限 | `PASS` | 映射到 `report:sales.q3:read`，无需审批，状态停留在可继续后续流程的 `PendingApproval/NotRequired` 结果 |
| 跨部门员工申请高敏资源访问 | `PASS` | 风险等级 `High`，审批链 `manager -> security_admin`，审批后可正常生效 |
| 审批通过但飞书开通失败 | `PASS` | 请求进入 `Failed`，grant 进入 `ProvisionFailed`，失败写回存在 |
| 授权到期后自动回收 | `PASS` | grant / request 进入 `Expired`，session 进入 `Revoked` |
| Agent 被停用后撤销生效 | `PASS` | Agent 停用后联动撤销任务创建并收敛到 `Revoked` |

## 3. 阻断项关闭情况

| 级别 | 项目 | 证据 | 结论 |
| --- | --- | --- | --- |
| Closed | Web 管理端身份上下文曾由页面直接填写并透传 `X-User-Id` / `X-Operator-Type` | `apps/web/lib/web-auth-context.js` 提供服务端受控 admin context；`apps/web/lib/admin-api.js` 不再接收页面 `userId/operatorType`，由 Next route 侧统一注入；`apps/web/components/admin-*.jsx` 仅只读展示当前上下文；`apps/web/app/api/admin/audit-records/route.test.js` 覆盖伪造 query 身份被忽略 | 阻断项已关闭 |
| Closed | 员工端评估链路曾由 Web 代理以页面路径直接伪装 `System` 身份触发 | `apps/web/lib/employee-request-api.js` 移除 `evaluatePermissionRequestAsSystem()`，改为 `evaluatePermissionRequestAsTrustedService()` 使用受控服务端 evaluation context；员工端浏览器与 route 不再传入 `userId`；`apps/web/app/api/employee/permission-requests/route.test.js` 覆盖伪造 body/query 身份被忽略且评估走受控 hook | 阻断项已关闭 |

## 4. 非阻断项

| 级别 | 项目 | 说明 |
| --- | --- | --- |
| Risk | 生产仍需接入真实 SSO / Gateway / 统一身份注入层 | 本次修复关闭 Web 页面手工身份透传与浏览器伪造 System 链路；当前实现仍提供受控 dev stub，真实上线前必须通过环境与网关策略确保后端不暴露给可伪造 `X-User-Id` / `X-Operator-Type` 的不可信客户端 |
| Risk | 当前 TASK-019 的 PostgreSQL 集成 / E2E 在本沙箱内需要提权才能拉起嵌入式 PostgreSQL | 这是当前执行环境限制，不是仓库业务缺陷；在普通宿主机终端或已有 PostgreSQL 环境下可正常执行 |
| Risk | Web 组件测试依赖显式 `TMPDIR=/tmp` | 属于当前 Node 运行时的临时目录问题，不影响生产构建结果，但建议在 CI 固化该环境变量 |
| Risk | `SessionAuthority` 目前无独立外部 `/agents/{id}/disable` API | 已有服务与测试闭环，能力存在；如果上线阶段要求外部运维入口，再补接口更稳妥 |

## 5. 最终判断

- 测试层面：`PASS`
- 发布放行层面：`PASS WITH RISKS`
- 原因：核心业务链路和状态机已验证通过；TASK-019 验收指出的两个 Web 侧生产身份边界阻断项已关闭。
- 上线条件：进入上线准备前必须确认生产流量经过可信身份注入层，禁止不可信客户端直连后端并伪造身份头；受控 dev stub 仅用于本地/测试环境。
