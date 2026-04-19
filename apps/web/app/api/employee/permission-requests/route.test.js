import { describe, expect, it, vi } from "vitest";

import {
  createEmployeePermissionRequest,
  evaluatePermissionRequestAsTrustedService,
  listPermissionRequests,
} from "../../../../lib/employee-request-api";
import { GET, POST } from "./route";

vi.mock("../../../../lib/employee-request-api", () => ({
  createEmployeePermissionRequest: vi.fn(),
  evaluatePermissionRequestAsTrustedService: vi.fn(),
  listPermissionRequests: vi.fn(),
}));

describe("/api/employee/permission-requests", () => {
  it("ignores forged list identity parameters", async () => {
    listPermissionRequests.mockResolvedValue({
      status: 200,
      payload: { data: { items: [], total: 0 } },
    });

    const response = await GET({
      nextUrl: new URL(
        "http://localhost/api/employee/permission-requests?userId=evil_user&page=1"
      ),
    });

    expect(response.status).toBe(200);
    expect(listPermissionRequests).toHaveBeenCalledWith(
      expect.not.objectContaining({
        userId: expect.any(String),
      })
    );
  });

  it("creates with employee context and evaluates through the trusted service hook", async () => {
    createEmployeePermissionRequest.mockResolvedValue({
      status: 201,
      payload: {
        request_id: "webreq_create_001",
        data: {
          permission_request_id: "req_123",
          request_status: "Submitted",
        },
      },
    });
    evaluatePermissionRequestAsTrustedService.mockResolvedValue({
      status: 200,
      payload: {
        data: {
          approval_status: "Pending",
          risk_level: "Low",
        },
      },
    });

    const response = await POST(
      new Request("http://localhost/api/employee/permission-requests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId: "evil_user",
          agentId: "agent_perm_assistant_v1",
          delegationId: "dlg_123",
          conversationId: "conv_001",
          message: "我需要查看销售部 Q3 报表",
        }),
      })
    );
    const payload = await response.json();

    expect(response.status).toBe(201);
    expect(createEmployeePermissionRequest).toHaveBeenCalledWith({
      agentId: "agent_perm_assistant_v1",
      delegationId: "dlg_123",
      conversationId: "conv_001",
      message: "我需要查看销售部 Q3 报表",
    });
    expect(createEmployeePermissionRequest).toHaveBeenCalledWith(
      expect.not.objectContaining({
        userId: expect.any(String),
      })
    );
    expect(evaluatePermissionRequestAsTrustedService).toHaveBeenCalledWith("req_123");
    expect(payload.data.evaluation).toEqual({
      approval_status: "Pending",
      risk_level: "Low",
    });
  });
});
