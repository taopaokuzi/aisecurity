import "server-only";

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

function buildAdminHeaders({ userId, operatorType, requestId }) {
  return {
    "X-Request-Id": requestId ?? buildRequestId("webadmin"),
    "X-User-Id": userId,
    "X-Operator-Type": operatorType,
  };
}

export async function listAuditRecords({
  userId,
  operatorType,
  requestId,
  eventType,
  actorType,
  actorId,
  page = 1,
  pageSize = 20,
}) {
  const searchParams = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });

  if (requestId) {
    searchParams.set("request_id", requestId);
  }
  if (eventType) {
    searchParams.set("event_type", eventType);
  }
  if (actorType) {
    searchParams.set("actor_type", actorType);
  }
  if (actorId) {
    searchParams.set("actor_id", actorId);
  }

  return callBackend(`/audit-records?${searchParams.toString()}`, {
    headers: buildAdminHeaders({
      userId,
      operatorType,
      requestId: buildRequestId("webadmin_audit"),
    }),
  });
}

export async function listFailedTasks({
  userId,
  operatorType,
  taskType,
  taskStatus,
  requestId,
  grantId,
  page = 1,
  pageSize = 20,
}) {
  const searchParams = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });

  if (taskType) {
    searchParams.set("task_type", taskType);
  }
  if (taskStatus) {
    searchParams.set("task_status", taskStatus);
  }
  if (requestId) {
    searchParams.set("request_id", requestId);
  }
  if (grantId) {
    searchParams.set("grant_id", grantId);
  }

  return callBackend(`/admin/failed-tasks?${searchParams.toString()}`, {
    headers: buildAdminHeaders({
      userId,
      operatorType,
      requestId: buildRequestId("webadmin_failed"),
    }),
  });
}

export async function retryConnectorTask({ taskId, userId, operatorType, reason }) {
  return callBackend(`/admin/connector-tasks/${taskId}/retry`, {
    method: "POST",
    headers: buildAdminHeaders({
      userId,
      operatorType,
      requestId: buildRequestId("webadmin_retry"),
    }),
    body: { reason },
  });
}
