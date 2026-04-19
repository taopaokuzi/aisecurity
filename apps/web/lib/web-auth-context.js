import "server-only";

const ADMIN_OPERATOR_TYPES = new Set(["ITAdmin", "SecurityAdmin"]);

function readEnv(name, fallback = "") {
  const value = process.env[name];
  if (typeof value !== "string") {
    return fallback;
  }
  return value.trim() || fallback;
}

function requireAdminOperatorType(operatorType) {
  if (ADMIN_OPERATOR_TYPES.has(operatorType)) {
    return operatorType;
  }
  throw new Error(`Unsupported web admin operator type: ${operatorType}`);
}

export function getAdminSessionContext() {
  return {
    userId: readEnv("WEB_DEV_ADMIN_USER_ID", "security_admin_001"),
    operatorType: requireAdminOperatorType(
      readEnv("WEB_DEV_ADMIN_OPERATOR_TYPE", "SecurityAdmin")
    ),
    source: "dev_stub",
  };
}

export function getEmployeeSessionContext() {
  return {
    userId: readEnv("WEB_DEV_EMPLOYEE_USER_ID", "user_001"),
    operatorType: "User",
    source: "dev_stub",
  };
}

export function getEmployeeRequestDefaults() {
  return {
    ...getEmployeeSessionContext(),
    agentId: readEnv("WEB_DEV_EMPLOYEE_AGENT_ID", "agent_perm_assistant_v1"),
    delegationId: readEnv("WEB_DEV_EMPLOYEE_DELEGATION_ID", "dlg_123"),
    conversationId: readEnv("WEB_DEV_EMPLOYEE_CONVERSATION_ID", ""),
  };
}

export function getEmployeeEvaluationServiceContext() {
  return {
    userId: readEnv("WEB_INTERNAL_EVALUATOR_ID", "web_internal_evaluator"),
    operatorType: "System",
    source: "trusted_web_service",
  };
}
