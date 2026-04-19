import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EmployeeRequestForm } from "./employee-request-form";

describe("EmployeeRequestForm", () => {
  it("submits a permission request and shows the created request id", async () => {
    const apiClient = {
      submitPermissionRequest: vi.fn().mockResolvedValue({
        data: {
          permission_request_id: "req_123",
          request_status: "Submitted",
          evaluation: {
            approval_status: "Pending",
            risk_level: "Low",
          },
          evaluation_error: null,
        },
      }),
    };

    render(
      <EmployeeRequestForm
        apiClient={apiClient}
        authContext={{ userId: "user_001", operatorType: "User", source: "dev_stub" }}
      />
    );

    expect(screen.getAllByText("user_001")).not.toHaveLength(0);
    expect(screen.getByText(/不接受页面手工覆盖/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "员工 user_id" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Agent ID"), {
      target: { value: "agent_perm_assistant_v1" },
    });
    expect(
      JSON.parse(window.localStorage.getItem("aisecurity.employee_request_context"))
    ).not.toHaveProperty("userId");

    fireEvent.change(screen.getByLabelText("Delegation ID"), {
      target: { value: "dlg_123" },
    });
    fireEvent.change(screen.getByLabelText("自然语言申请"), {
      target: { value: "我需要查看销售部 Q3 报表，但不需要修改权限。" },
    });

    fireEvent.click(screen.getByRole("button", { name: "提交申请" }));

    await waitFor(() => {
      expect(apiClient.submitPermissionRequest).toHaveBeenCalledWith({
        agentId: "agent_perm_assistant_v1",
        delegationId: "dlg_123",
        conversationId: "",
        message: "我需要查看销售部 Q3 报表，但不需要修改权限。",
      });
    });

    expect(await screen.findByText("申请已提交")).toBeInTheDocument();
    expect(screen.getByText("req_123")).toBeInTheDocument();
  });
});
