import { NextResponse } from "next/server";

import { evaluatePermissionRequestAsTrustedService } from "../../../../../../lib/employee-request-api";

export async function POST(_request, { params }) {
  try {
    const result = await evaluatePermissionRequestAsTrustedService(params.requestId);
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
