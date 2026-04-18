import { NextResponse } from "next/server";

import {
  createEmployeePermissionRequest,
  evaluatePermissionRequestAsSystem,
  listPermissionRequests,
} from "../../../../lib/employee-request-api";

function missingField(field) {
  return NextResponse.json(
    {
      error: {
        code: "BAD_REQUEST",
        message: `${field} is required`,
      },
    },
    { status: 400 }
  );
}

export async function GET(request) {
  const searchParams = request.nextUrl.searchParams;
  const userId = searchParams.get("userId");
  if (!userId) {
    return missingField("userId");
  }

  try {
    const result = await listPermissionRequests({
      userId,
      page: Number(searchParams.get("page") ?? "1"),
      pageSize: Number(searchParams.get("pageSize") ?? "20"),
      requestStatus: searchParams.get("requestStatus") ?? undefined,
      approvalStatus: searchParams.get("approvalStatus") ?? undefined,
    });
    return NextResponse.json(result.payload, { status: result.status });
  } catch (error) {
    return NextResponse.json(
      {
        error: {
          code: "UPSTREAM_UNAVAILABLE",
          message: error instanceof Error ? error.message : "Backend request failed",
        },
      },
      { status: 502 }
    );
  }
}

export async function POST(request) {
  const body = await request.json();
  const { userId, agentId, delegationId, conversationId, message } = body;

  if (!userId) {
    return missingField("userId");
  }
  if (!agentId) {
    return missingField("agentId");
  }
  if (!delegationId) {
    return missingField("delegationId");
  }
  if (!message) {
    return missingField("message");
  }

  try {
    const createResult = await createEmployeePermissionRequest({
      userId,
      agentId,
      delegationId,
      conversationId,
      message,
    });

    if (createResult.status >= 400) {
      return NextResponse.json(createResult.payload, { status: createResult.status });
    }

    const permissionRequestId = createResult.payload?.data?.permission_request_id;
    let evaluation = null;
    let evaluationError = null;

    if (permissionRequestId) {
      const evaluationResult = await evaluatePermissionRequestAsSystem(permissionRequestId);
      if (evaluationResult.status >= 400) {
        evaluationError = evaluationResult.payload?.error ?? {
          code: "EVALUATION_FAILED",
          message: "Evaluation could not be completed",
        };
      } else {
        evaluation = evaluationResult.payload?.data ?? null;
      }
    }

    return NextResponse.json(
      {
        request_id: createResult.payload.request_id,
        data: {
          ...createResult.payload.data,
          evaluation,
          evaluation_error: evaluationError,
        },
      },
      { status: createResult.status }
    );
  } catch (error) {
    return NextResponse.json(
      {
        error: {
          code: "UPSTREAM_UNAVAILABLE",
          message: error instanceof Error ? error.message : "Backend request failed",
        },
      },
      { status: 502 }
    );
  }
}
