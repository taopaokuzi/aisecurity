import { AdminFailedTaskConsole } from "../../../components/admin-failed-task-console";
import { AdminShell } from "../../../components/admin-shell";
import styles from "../../../components/employee-request-ui.module.css";
import { getAdminSessionContext } from "../../../lib/web-auth-context";

export default function AdminFailedTasksPage() {
  const authContext = getAdminSessionContext();
  return (
    <AdminShell
      eyebrow="Failed Tasks"
      title="失败任务列表页"
      description="聚合展示失败中的 connector task、审批回调异常和会话撤销失败，便于管理员快速定位问题。"
      activeHref="/admin/failed-tasks"
      aside={
        <>
          <h2 className={styles.sectionTitle}>定位建议</h2>
          <ul className={styles.helperList}>
            <li>先看 task_type 判断失败属于开通、撤销还是审批回调。</li>
            <li>再看 task_status、request_id、grant_id 和最近错误文本。</li>
            <li>若允许 retry，可跳转补偿页执行安全重试。</li>
          </ul>
        </>
      }
    >
      <AdminFailedTaskConsole authContext={authContext} />
    </AdminShell>
  );
}
