import { NextResponse } from "next/server";

import {
  getPermissionRequestDetail,
  getPermissionRequestEvaluation,
} from "../../../../../lib/employee-request-api";

export async function GET(_request, { params }) {
  try {
    const detailResult = await getPermissionRequestDetail({
      permissionRequestId: params.requestId,
    });

    if (detailResult.status >= 400) {
      return NextResponse.json(detailResult.payload, { status: detailResult.status });
    }

    const evaluationResult = await getPermissionRequestEvaluation({
      permissionRequestId: params.requestId,
    });

    return NextResponse.json(
      {
        request_id: detailResult.payload.request_id,
        data: {
          request: detailResult.payload.data,
          evaluation:
            evaluationResult.status >= 400 ? null : evaluationResult.payload?.data ?? null,
          evaluation_error:
            evaluationResult.status >= 400
              ? evaluationResult.payload?.error ?? {
                  code: "EVALUATION_NOT_AVAILABLE",
                  message: "Evaluation result is not available yet",
                }
              : null,
        },
      },
      { status: detailResult.status }
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
