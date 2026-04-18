const REQUEST_STATUS_META = {
  Draft: { label: "草稿", tone: "neutral" },
  Submitted: { label: "已提交", tone: "info" },
  Evaluating: { label: "评估中", tone: "info" },
  PendingApproval: { label: "待审批", tone: "warning" },
  Approved: { label: "已批准", tone: "success" },
  Provisioning: { label: "开通中", tone: "info" },
  Active: { label: "已生效", tone: "success" },
  Expiring: { label: "即将到期", tone: "warning" },
  Expired: { label: "已过期", tone: "neutral" },
  Revoked: { label: "已撤销", tone: "neutral" },
  Failed: { label: "处理失败", tone: "danger" },
};

const APPROVAL_STATUS_META = {
  NotRequired: { label: "无需审批", tone: "neutral" },
  Pending: { label: "审批中", tone: "warning" },
  Approved: { label: "审批通过", tone: "success" },
  Rejected: { label: "审批驳回", tone: "danger" },
  Withdrawn: { label: "已撤回", tone: "neutral" },
  Expired: { label: "审批过期", tone: "neutral" },
  CallbackFailed: { label: "审批回调失败", tone: "danger" },
};

const GRANT_STATUS_META = {
  NotCreated: { label: "未创建授权", tone: "neutral" },
  ProvisioningRequested: { label: "已提交开通", tone: "info" },
  Provisioning: { label: "开通中", tone: "info" },
  Active: { label: "已开通", tone: "success" },
  Expiring: { label: "即将到期", tone: "warning" },
  Expired: { label: "已过期", tone: "neutral" },
  Revoking: { label: "撤销中", tone: "warning" },
  Revoked: { label: "已撤销", tone: "neutral" },
  ProvisionFailed: { label: "开通失败", tone: "danger" },
  RevokeFailed: { label: "撤销失败", tone: "danger" },
};

const RISK_LEVEL_META = {
  Low: { label: "低", tone: "success" },
  Medium: { label: "中", tone: "warning" },
  High: { label: "高", tone: "danger" },
  Critical: { label: "极高", tone: "danger" },
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

export function getStatusMeta(kind, value) {
  const fallback = { label: humanizeToken(value), tone: "neutral" };

  if (kind === "request") {
    return REQUEST_STATUS_META[value] ?? fallback;
  }

  if (kind === "approval") {
    return APPROVAL_STATUS_META[value] ?? fallback;
  }

  if (kind === "grant") {
    return GRANT_STATUS_META[value] ?? fallback;
  }

  if (kind === "task") {
    return TASK_STATUS_META[value] ?? fallback;
  }

  return fallback;
}

export function getRiskMeta(value) {
  return RISK_LEVEL_META[value] ?? { label: value ?? "待评估", tone: "neutral" };
}

export function formatDateTime(value) {
  if (!value) {
    return "未提供";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatValue(value) {
  if (value === null || value === undefined || value === "") {
    return "未提供";
  }

  return String(value);
}

export function summarizeNextStep(requestStatus, approvalStatus, grantStatus) {
  if (grantStatus === "Active") {
    return "权限已经生效，可以继续跟进到期与撤销状态。";
  }

  if (approvalStatus === "Pending") {
    return "申请已经进入审批链路，当前等待审批人处理。";
  }

  if (requestStatus === "PendingApproval" && approvalStatus === "NotRequired") {
    return "申请已完成评估，当前等待授权开通或后续编排。";
  }

  if (requestStatus === "Submitted") {
    return "申请已提交，正在等待评估结果。";
  }

  if (requestStatus === "Failed" || grantStatus === "ProvisionFailed") {
    return "当前流程存在失败状态，建议结合详情页信息继续排查。";
  }

  return "可以继续关注申请、审批和授权三条状态线是否推进。";
}
