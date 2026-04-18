import { formatDateTime, formatValue } from "./employee-request-presenters";

export { formatDateTime, formatValue };

const RESULT_META = {
  Success: { label: "成功", tone: "success" },
  Failed: { label: "失败", tone: "danger" },
  Denied: { label: "拒绝", tone: "warning" },
};

const TASK_STATUS_META = {
  Pending: { label: "待处理", tone: "warning" },
  Running: { label: "执行中", tone: "info" },
  Retrying: { label: "重试中", tone: "warning" },
  Failed: { label: "失败", tone: "danger" },
  Succeeded: { label: "成功", tone: "success" },
};

function humanizeToken(value) {
  if (!value) {
    return "未提供";
  }

  return value.replace(/([a-z0-9])([A-Z])/g, "$1 $2");
}

export function getResultMeta(value) {
  return RESULT_META[value] ?? { label: humanizeToken(value), tone: "neutral" };
}

export function getTaskStatusMeta(value) {
  return TASK_STATUS_META[value] ?? { label: humanizeToken(value), tone: "neutral" };
}

export function getFailureSummary(item) {
  return (
    item.failure_reason ??
    item.connector_task?.last_error_message ??
    item.request?.failed_reason ??
    item.session_context?.revocation_reason ??
    item.approval_record?.approval_status ??
    "未提供"
  );
}

export function getCompensationHint(item, operatorType) {
  if (operatorType !== "ITAdmin") {
    return "当前操作人不是 ITAdmin，页面仅展示状态，不允许发起 retry。";
  }

  if (!item.retryable) {
    return "当前任务不允许 retry，请结合状态与错误信息继续排查。";
  }

  return "允许 retry。点击后会再次向 TASK-015 提供的补偿 API 发起重试。";
}
