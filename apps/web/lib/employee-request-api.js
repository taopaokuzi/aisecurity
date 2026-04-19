import "server-only";

import {
  getEmployeeEvaluationServiceContext,
  getEmployeeSessionContext,
} from "./web-auth-context";

const API_BASE_URL =
  process.env.API_BASE_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://127.0.0.1:8000";

function buildRequestId(prefix) {
  const token =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID().slice(0, 12)
      : Math.random().toString(16).slice(2, 14);
  return `${prefix}_${token}`;
}

async function parseResponse(response) {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }

  const text = await response.text();
  return text ? { message: text } : {};
}

async function callBackend(path, { method = "GET", body, headers = {} } = {}) {
  const requestHeaders = new Headers(headers);
  if (body !== undefined) {
    requestHeaders.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: requestHeaders,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });

  return {
    status: response.status,
    payload: await parseResponse(response),
  };
}

function buildHeadersForContext(context, { requestId, idempotencyKey }) {
  return {
    "X-Request-Id": requestId ?? buildRequestId("webreq"),
    "X-User-Id": context.userId,
    "X-Operator-Type": context.operatorType,
    ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
  };
}

export async function createEmployeePermissionRequest({
  agentId,
  delegationId,
  conversationId,
  message,
}) {
  const context = getEmployeeSessionContext();
  return callBackend("/permission-requests", {
    method: "POST",
    headers: buildHeadersForContext(context, {
      requestId: buildRequestId("webreq_create"),
      idempotencyKey: buildRequestId("idem_permission_request"),
    }),
    body: {
      message,
      agent_id: agentId,
      delegation_id: delegationId,
      conversation_id: conversationId || null,
    },
  });
}

export async function evaluatePermissionRequestAsTrustedService(permissionRequestId) {
  const context = getEmployeeEvaluationServiceContext();
  return callBackend(`/permission-requests/${permissionRequestId}/evaluate`, {
    method: "POST",
    headers: buildHeadersForContext(context, {
      requestId: buildRequestId("webreq_evaluate"),
    }),
    body: {
      force_re_evaluate: false,
    },
  });
}

export async function getPermissionRequestDetail({ permissionRequestId }) {
  const context = getEmployeeSessionContext();
  return callBackend(`/permission-requests/${permissionRequestId}`, {
    headers: buildHeadersForContext(context, {
      requestId: buildRequestId("webreq_detail"),
    }),
  });
}

export async function getPermissionRequestEvaluation({ permissionRequestId }) {
  const context = getEmployeeSessionContext();
  return callBackend(`/permission-requests/${permissionRequestId}/evaluation`, {
    headers: buildHeadersForContext(context, {
      requestId: buildRequestId("webreq_evaluation"),
    }),
  });
}

export async function listPermissionRequests({
  page = 1,
  pageSize = 20,
  requestStatus,
  approvalStatus,
}) {
  const context = getEmployeeSessionContext();
  const searchParams = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    mine_only: "true",
  });

  if (requestStatus) {
    searchParams.set("request_status", requestStatus);
  }
  if (approvalStatus) {
    searchParams.set("approval_status", approvalStatus);
  }

  return callBackend(`/permission-requests?${searchParams.toString()}`, {
    headers: buildHeadersForContext(context, {
      requestId: buildRequestId("webreq_list"),
    }),
  });
}
