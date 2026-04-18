import { EmployeeRequestForm } from "../../../../components/employee-request-form";
import { EmployeeShell } from "../../../../components/employee-shell";
import styles from "../../../../components/employee-request-ui.module.css";

export default function EmployeeRequestNewPage() {
  return (
    <EmployeeShell
      eyebrow="TASK-016 Employee UI"
      title="员工权限申请入口"
      description="输入自然语言需求、Agent 上下文和委托凭证后，前端会通过 API 客户端提交申请，并把后端返回的状态和评估结果展示出来。"
      activeHref="/employee/requests/new"
      aside={
        <>
          <h2 className={styles.sectionTitle}>本页覆盖</h2>
          <ul className={styles.helperList}>
            <li>提交自然语言申请。</li>
            <li>提交 `agent_id`、`delegation_id` 与可选 `conversation_id`。</li>
            <li>联调 `POST /permission-requests`，并在服务端触发评估同步。</li>
          </ul>
        </>
      }
    >
      <EmployeeRequestForm />
    </EmployeeShell>
  );
}
