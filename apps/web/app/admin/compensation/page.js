import { AdminCompensationConsole } from "../../../components/admin-compensation-console";
import { AdminShell } from "../../../components/admin-shell";
import styles from "../../../components/employee-request-ui.module.css";
import { getAdminSessionContext } from "../../../lib/web-auth-context";

export default function AdminCompensationPage() {
  const authContext = getAdminSessionContext();
  return (
    <AdminShell
      eyebrow="Compensation"
      title="补偿 / Retry 操作页"
      description="展示任务当前状态、最近错误与 retry 提示，只通过后端补偿 API 发起重试，不在前端直接改状态。"
      activeHref="/admin/compensation"
      aside={
        <>
          <h2 className={styles.sectionTitle}>安全约束</h2>
          <ul className={styles.helperList}>
            <li>retry 前会做二次确认，避免误触发。</li>
            <li>仅允许 retry 的任务会展示可点击操作。</li>
            <li>非 ITAdmin 或不支持 retry 的任务会给出清晰提示。</li>
          </ul>
        </>
      }
    >
      <AdminCompensationConsole authContext={authContext} />
    </AdminShell>
  );
}
