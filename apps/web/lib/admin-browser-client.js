async function parseJson(response) {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }

  const text = await response.text();
  return text ? { message: text } : {};
}

export class AdminClientError extends Error {
  constructor(message, { status, code, details } = {}) {
    super(message);
    this.name = "AdminClientError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request(path, { method = "GET", body, searchParams } = {}) {
  const suffix = searchParams ? `?${new URLSearchParams(searchParams).toString()}` : "";
  const response = await fetch(`${path}${suffix}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await parseJson(response);

  if (!response.ok) {
    throw new AdminClientError(
      payload?.error?.message ?? payload?.message ?? "管理后台请求失败，请稍后重试。",
      {
        status: response.status,
        code: payload?.error?.code,
        details: payload?.error?.details,
      }
    );
  }

  return payload;
}

export const adminBrowserClient = {
  listAuditRecords(input) {
    return request("/api/admin/audit-records", {
      searchParams: input,
    });
  },

  listFailedTasks(input) {
    return request("/api/admin/failed-tasks", {
      searchParams: input,
    });
  },

  retryConnectorTask(input) {
    return request(`/api/admin/connector-tasks/${input.taskId}/retry`, {
      method: "POST",
      body: { reason: input.reason },
    });
  },
};

export function getAdminErrorMessage(error) {
  if (error instanceof AdminClientError) {
    return error.message;
  }

  return "管理后台请求失败，请检查前后端联调环境。";
}
