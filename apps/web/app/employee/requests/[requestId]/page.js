import { EmployeeRequestDetail } from "../../../../components/employee-request-detail";
import { EmployeeShell } from "../../../../components/employee-shell";
import styles from "../../../../components/employee-request-ui.module.css";

export default function EmployeeRequestDetailPage({ params }) {
  return (
    <EmployeeShell
      eyebrow="TASK-016 Employee UI"
      title="申请详情与评估结果"
      description="详情页聚合原始申请、解析后的资源信息、建议权限、风险等级以及审批和授权状态，方便员工自助判断当前进度。"
      activeHref="/employee/requests"
      aside={
        <>
          <h2 className={styles.sectionTitle}>详情字段</h2>
          <ul className={styles.helperList}>
            <li>`raw_text`、`resource_key`、`resource_type`、`action`。</li>
            <li>`suggested_permission`、`risk_level`。</li>
            <li>`approval_status` 与 `grant_status`。</li>
          </ul>
        </>
      }
    >
      <EmployeeRequestDetail requestId={params.requestId} />
    </EmployeeShell>
  );
}
