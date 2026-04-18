async function parseJson(response) {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }

  const text = await response.text();
  return text ? { message: text } : {};
}

export class EmployeeRequestClientError extends Error {
  constructor(message, { status, code, details } = {}) {
    super(message);
    this.name = "EmployeeRequestClientError";
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
    throw new EmployeeRequestClientError(
      payload?.error?.message ?? payload?.message ?? "请求失败，请稍后重试。",
      {
        status: response.status,
        code: payload?.error?.code,
        details: payload?.error?.details,
      }
    );
  }

  return payload;
}

export const employeeRequestBrowserClient = {
  submitPermissionRequest(input) {
    return request("/api/employee/permission-requests", {
      method: "POST",
      body: input,
    });
  },

  listPermissionRequests(input) {
    return request("/api/employee/permission-requests", {
      searchParams: input,
    });
  },

  getPermissionRequestDetail({ requestId, userId }) {
    return request(`/api/employee/permission-requests/${requestId}`, {
      searchParams: { userId },
    });
  },

  evaluatePermissionRequest({ requestId }) {
    return request(`/api/employee/permission-requests/${requestId}/evaluate`, {
      method: "POST",
    });
  },
};

export function getErrorMessage(error) {
  if (error instanceof EmployeeRequestClientError) {
    return error.message;
  }

  return "请求失败，请检查后端联调环境是否可用。";
}
