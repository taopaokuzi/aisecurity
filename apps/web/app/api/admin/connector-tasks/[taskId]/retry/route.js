import { NextResponse } from "next/server";

import { retryConnectorTask } from "../../../../../../lib/admin-api";

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

export async function POST(request, { params }) {
  const body = await request.json();
  const { reason } = body;
  if (!reason) {
    return missingField("reason");
  }

  try {
    const result = await retryConnectorTask({
      taskId: params.taskId,
      reason,
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
