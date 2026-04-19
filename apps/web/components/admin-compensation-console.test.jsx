import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AdminCompensationConsole } from "./admin-compensation-console";

describe("AdminCompensationConsole", () => {
  it("retries an allowed failed task", async () => {
    window.confirm = vi.fn().mockReturnValue(true);

    const apiClient = {
      listFailedTasks: vi
        .fn()
        .mockResolvedValueOnce({
          data: {
            items: [
              {
                task_id: "ctk_failed_001",
                task_type: "provision",
                task_status: "Failed",
                request_id: "req_failed_001",
                grant_id: "grt_failed_001",
                occurred_at: "2026-04-18T08:00:00Z",
                failure_reason: "Connector timeout",
                retryable: true,
                request: {
                  request_status: "Failed",
                  grant_status: "ProvisionFailed",
                },
              },
            ],
          },
        })
        .mockResolvedValueOnce({
          data: {
            items: [],
          },
        }),
      retryConnectorTask: vi.fn().mockResolvedValue({
        data: {
          original_task_id: "ctk_failed_001",
          retry_task_id: "ctk_retry_001",
          grant_status: "Active",
        },
      }),
    };

    render(
      <AdminCompensationConsole
        apiClient={apiClient}
        authContext={{
          userId: "it_admin_001",
          operatorType: "ITAdmin",
          source: "dev_stub",
        }}
      />
    );

    expect(await screen.findByText("ctk_failed_001")).toBeInTheDocument();
    expect(screen.getAllByText("it_admin_001")).not.toHaveLength(0);
    expect(screen.getByText(/页面不会透传任意输入身份/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "管理员 user_id" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("例如 Manual retry after connector recovery"), {
      target: { value: "Manual retry after connector recovery" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发起 retry" }));

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalled();
      expect(apiClient.retryConnectorTask).toHaveBeenCalledWith({
        taskId: "ctk_failed_001",
        reason: "Manual retry after connector recovery",
      });
    });

    expect(await screen.findByText(/补偿已提交/)).toBeInTheDocument();
    expect(screen.getByText(/ctk_retry_001/)).toBeInTheDocument();
  });

  it("shows a clear hint when retry is not available", async () => {
    const apiClient = {
      listFailedTasks: vi.fn().mockResolvedValue({
        data: {
          items: [
            {
              task_id: "ctk_done_001",
              task_type: "provision",
              task_status: "Succeeded",
              request_id: "req_done_001",
              grant_id: "grt_done_001",
              occurred_at: "2026-04-18T08:00:00Z",
              failure_reason: "No failure",
              retryable: false,
              request: {
                request_status: "Active",
                grant_status: "Active",
              },
            },
          ],
        },
      }),
      retryConnectorTask: vi.fn(),
    };

    render(
      <AdminCompensationConsole
        apiClient={apiClient}
        authContext={{
          userId: "it_admin_001",
          operatorType: "ITAdmin",
          source: "dev_stub",
        }}
      />
    );

    expect(await screen.findByText("ctk_done_001")).toBeInTheDocument();
    expect(
      screen.getByText("当前任务不允许 retry，请结合状态与错误信息继续排查。")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发起 retry" })).toBeDisabled();
  });
});
