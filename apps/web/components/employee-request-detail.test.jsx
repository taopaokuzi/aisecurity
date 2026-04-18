import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EmployeeRequestDetail } from "./employee-request-detail";

describe("EmployeeRequestDetail", () => {
  it("renders the permission request detail and evaluation fields", async () => {
    window.localStorage.setItem(
      "aisecurity.employee_request_context",
      JSON.stringify({ userId: "user_001" })
    );

    const apiClient = {
      getPermissionRequestDetail: vi.fn().mockResolvedValue({
        data: {
          request: {
            request_id: "req_001",
            raw_text: "我需要查看销售部 Q3 报表",
            agent_id: "agent_perm_assistant_v1",
            delegation_id: "dlg_123",
            risk_level: "Low",
            approval_status: "Pending",
            grant_status: "NotCreated",
            request_status: "PendingApproval",
            created_at: "2026-04-18T08:00:00Z",
            updated_at: "2026-04-18T08:05:00Z",
          },
          evaluation: {
            resource_key: "sales.q3_report",
            resource_type: "report",
            action: "read",
            requested_duration: "P7D",
            suggested_permission: "report:sales.q3:read",
            risk_level: "Low",
            policy_version: "perm-map.v1",
          },
          evaluation_error: null,
        },
      }),
      evaluatePermissionRequest: vi.fn(),
    };

    render(<EmployeeRequestDetail requestId="req_001" apiClient={apiClient} />);

    await waitFor(() => {
      expect(apiClient.getPermissionRequestDetail).toHaveBeenCalledWith({
        requestId: "req_001",
        userId: "user_001",
      });
    });

    expect(await screen.findByText("申请与评估字段")).toBeInTheDocument();
    expect(screen.getByText("我需要查看销售部 Q3 报表")).toBeInTheDocument();
    expect(screen.getByText("sales.q3_report")).toBeInTheDocument();
    expect(screen.getAllByText("report:sales.q3:read")).toHaveLength(2);
    expect(screen.getAllByText("低")).toHaveLength(2);
  });
});
