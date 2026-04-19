import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EmployeeRequestList } from "./employee-request-list";

describe("EmployeeRequestList", () => {
  it("loads and renders the employee request list", async () => {
    const apiClient = {
      listPermissionRequests: vi.fn().mockResolvedValue({
        data: {
          total: 1,
          items: [
            {
              request_id: "req_001",
              raw_text: "我需要查看销售部 Q3 报表",
              created_at: "2026-04-18T08:00:00Z",
              suggested_permission: "report:sales.q3:read",
              request_status: "PendingApproval",
              approval_status: "Pending",
              grant_status: "NotCreated",
            },
          ],
        },
      }),
    };

    render(
      <EmployeeRequestList
        apiClient={apiClient}
        authContext={{ userId: "user_001", operatorType: "User", source: "dev_stub" }}
      />
    );

    await waitFor(() => {
      expect(apiClient.listPermissionRequests).toHaveBeenCalledWith(
        expect.not.objectContaining({
          userId: expect.any(String),
        })
      );
    });

    expect(screen.getAllByText("user_001")).not.toHaveLength(0);
    expect(screen.getByText(/不会再通过手工输入 user_id/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "员工 user_id" })).not.toBeInTheDocument();
    expect(await screen.findByText("req_001")).toBeInTheDocument();
    expect(screen.getByText("我需要查看销售部 Q3 报表")).toBeInTheDocument();
    expect(screen.getByText("待审批")).toBeInTheDocument();
    expect(screen.getByText("审批中")).toBeInTheDocument();
    expect(screen.getByText("未创建授权")).toBeInTheDocument();
  });
});
