import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusPill } from "./status-pill";

describe("StatusPill", () => {
  it("renders translated status labels for request, approval, and grant", () => {
    render(
      <div>
        <StatusPill kind="request" value="PendingApproval" />
        <StatusPill kind="approval" value="Pending" />
        <StatusPill kind="grant" value="Provisioning" />
      </div>
    );

    expect(screen.getByText("待审批")).toBeInTheDocument();
    expect(screen.getByText("审批中")).toBeInTheDocument();
    expect(screen.getByText("开通中")).toBeInTheDocument();
  });
});
