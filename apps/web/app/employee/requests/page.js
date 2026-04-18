import { EmployeeRequestList } from "../../../components/employee-request-list";
import { EmployeeShell } from "../../../components/employee-shell";
import styles from "../../../components/employee-request-ui.module.css";

export default function EmployeeRequestsPage() {
  return (
    <EmployeeShell
      eyebrow="TASK-016 Employee UI"
      title="申请状态与列表"
      description="按员工视角查询本人申请，优先保证状态信息完整、可读，并在桌面端和移动端都能快速判断流程推进到哪一步。"
      activeHref="/employee/requests"
      aside={
        <>
          <h2 className={styles.sectionTitle}>状态字段</h2>
          <ul className={styles.helperList}>
            <li>`request_status` 表示申请主流程阶段。</li>
            <li>`approval_status` 表示审批链路状态。</li>
            <li>`grant_status` 表示授权开通或回收状态。</li>
          </ul>
        </>
      }
    >
      <EmployeeRequestList />
    </EmployeeShell>
  );
}
