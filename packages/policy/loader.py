from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import Any

from packages.domain import RiskLevel

from .models import (
    ApprovalRule,
    PermissionMappingRule,
    PolicyBundle,
    PolicyLoaderError,
    PolicyManifest,
    RiskRule,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_DIR = ROOT_DIR / "config" / "policy"


def load_policy_bundle(policy_dir: str | Path | None = None) -> PolicyBundle:
    base_dir = Path(policy_dir) if policy_dir is not None else DEFAULT_POLICY_DIR
    manifest_path = base_dir / "policy_manifest.toml"
    manifest_data = _load_toml_file(manifest_path)

    policy_section = _require_table(manifest_data, "policy", manifest_path)
    files_section = _require_table(manifest_data, "files", manifest_path)

    manifest = PolicyManifest(
        policy_id=_require_text(policy_section, "policy_id", manifest_path),
        policy_version=_require_text(policy_section, "version", manifest_path),
        permission_mappings_file=_require_text(
            files_section,
            "permission_mappings",
            manifest_path,
        ),
        risk_rules_file=_require_text(files_section, "risk_rules", manifest_path),
        approval_rules_file=_require_text(files_section, "approval_rules", manifest_path),
    )

    permission_path = base_dir / manifest.permission_mappings_file
    risk_path = base_dir / manifest.risk_rules_file
    approval_path = base_dir / manifest.approval_rules_file

    permission_data = _load_toml_file(permission_path)
    risk_data = _load_toml_file(risk_path)
    approval_data = _load_toml_file(approval_path)

    action_terms_section = _require_table(permission_data, "action_terms", permission_path)
    action_terms = {
        action_name: _normalize_terms(
            _require_list_of_text(action_terms_section, action_name, permission_path)
        )
        for action_name in ("read", "write", "request_edit")
    }
    readonly_priority_terms = _normalize_terms(
        _require_list_of_text(action_terms_section, "readonly_priority_terms", permission_path)
    )
    permission_mappings = tuple(
        _parse_permission_mapping(entry, permission_path)
        for entry in _require_list_of_tables(permission_data, "resources", permission_path)
    )

    base_risk_scores = _parse_int_mapping(
        _require_table(risk_data, "base_scores", risk_path),
        risk_path,
    )
    risk_level_thresholds = _parse_int_mapping(
        _require_table(risk_data, "level_thresholds", risk_path),
        risk_path,
    )
    risk_rules = tuple(
        _parse_risk_rule(entry, risk_path)
        for entry in _require_list_of_tables(risk_data, "rules", risk_path)
    )

    approval_rules = tuple(
        _parse_approval_rule(entry, approval_path)
        for entry in _require_list_of_tables(approval_data, "routes", approval_path)
    )

    source_files = (manifest_path, permission_path, risk_path, approval_path)
    return PolicyBundle(
        manifest=manifest,
        policy_dir=base_dir,
        source_files=source_files,
        policy_digest=_compute_policy_digest(source_files),
        action_terms=action_terms,
        readonly_priority_terms=readonly_priority_terms,
        permission_mappings=permission_mappings,
        base_risk_scores=base_risk_scores,
        risk_level_thresholds=risk_level_thresholds,
        risk_rules=risk_rules,
        approval_rules=approval_rules,
    )


def get_policy_version(policy_dir: str | Path | None = None) -> str:
    return load_policy_bundle(policy_dir).policy_version


def _parse_permission_mapping(entry: dict[str, Any], source_path: Path) -> PermissionMappingRule:
    permission_map_raw = entry.get("permission_map")
    if not isinstance(permission_map_raw, dict):
        raise PolicyLoaderError(
            f"{source_path}: permission_map must be an inline table for mapping {entry!r}"
        )
    permission_map = {
        _normalize_token(action): _require_scalar_text(permission, source_path, "permission_map value")
        for action, permission in permission_map_raw.items()
    }
    if "read" not in permission_map:
        raise PolicyLoaderError(
            f"{source_path}: permission mapping {entry.get('name', '<unknown>')} must define read permission"
        )
    return PermissionMappingRule(
        name=_require_entry_text(entry, "name", source_path),
        resource_key=_require_entry_text(entry, "resource_key", source_path),
        resource_type=_normalize_token(_require_entry_text(entry, "resource_type", source_path)),
        department=_normalize_optional_text(entry.get("department"), source_path, "department"),
        sensitivity=_normalize_token(_require_entry_text(entry, "sensitivity", source_path)),
        resource_terms=_normalize_terms(
            _require_entry_text_list(entry, "resource_terms", source_path)
        ),
        permission_map=permission_map,
    )


def _parse_risk_rule(entry: dict[str, Any], source_path: Path) -> RiskRule:
    minimum_level = entry.get("minimum_level")
    return RiskRule(
        name=_require_entry_text(entry, "name", source_path),
        score_delta=_require_entry_int(entry, "score_delta", source_path),
        minimum_level=_parse_risk_level(minimum_level, source_path, allow_none=True),
        reason=_require_entry_text(entry, "reason", source_path),
        cross_department=_optional_bool(entry.get("cross_department"), source_path, "cross_department"),
        sensitivities=_normalize_terms(
            _optional_entry_text_list(entry, "sensitivities", source_path)
        ),
        fallback_only=_optional_bool(entry.get("fallback_only"), source_path, "fallback_only"),
    )


def _parse_approval_rule(entry: dict[str, Any], source_path: Path) -> ApprovalRule:
    return ApprovalRule(
        name=_require_entry_text(entry, "name", source_path),
        approval_required=_require_entry_bool(entry, "approval_required", source_path),
        route=tuple(_normalize_token(item) for item in _require_entry_text_list(entry, "route", source_path)),
        requires_manager_approval=_require_entry_bool(
            entry,
            "requires_manager_approval",
            source_path,
        ),
        requires_escalated_approval=_require_entry_bool(
            entry,
            "requires_escalated_approval",
            source_path,
        ),
        recommended_path=_require_entry_text(entry, "recommended_path", source_path),
        reason=_require_entry_text(entry, "reason", source_path),
        risk_levels=tuple(
            _parse_risk_level(level, source_path)
            for level in _optional_entry_text_list(entry, "risk_levels", source_path)
        ),
        actions=_normalize_terms(_optional_entry_text_list(entry, "actions", source_path)),
        sensitivities=_normalize_terms(
            _optional_entry_text_list(entry, "sensitivities", source_path)
        ),
        cross_department=_optional_bool(entry.get("cross_department"), source_path, "cross_department"),
        fallback_only=_optional_bool(entry.get("fallback_only"), source_path, "fallback_only"),
    )


def _load_toml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise PolicyLoaderError(f"{path}: policy file not found")
    with path.open("rb") as handle:
        loaded = tomllib.load(handle)
    if not isinstance(loaded, dict):
        raise PolicyLoaderError(f"{path}: top-level TOML value must be a table")
    return loaded


def _require_table(data: dict[str, Any], key: str, source_path: Path) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise PolicyLoaderError(f"{source_path}: [{key}] table is required")
    return value


def _require_list_of_tables(data: dict[str, Any], key: str, source_path: Path) -> list[dict[str, Any]]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise PolicyLoaderError(f"{source_path}: [[{key}]] entries are required")
    return value


def _require_list_of_text(data: dict[str, Any], key: str, source_path: Path) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list):
        raise PolicyLoaderError(f"{source_path}: {key} must be an array of strings")
    normalized: list[str] = []
    for item in value:
        normalized.append(_require_scalar_text(item, source_path, key))
    return normalized


def _require_text(data: dict[str, Any], key: str, source_path: Path) -> str:
    return _require_scalar_text(data.get(key), source_path, key)


def _require_scalar_text(value: Any, source_path: Path, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyLoaderError(f"{source_path}: {field_name} must be a non-empty string")
    return value.strip()


def _require_entry_text(entry: dict[str, Any], key: str, source_path: Path) -> str:
    return _require_scalar_text(entry.get(key), source_path, key)


def _require_entry_text_list(entry: dict[str, Any], key: str, source_path: Path) -> list[str]:
    value = entry.get(key)
    if not isinstance(value, list):
        raise PolicyLoaderError(f"{source_path}: {key} must be an array of strings")
    return [_require_scalar_text(item, source_path, key) for item in value]


def _optional_entry_text_list(entry: dict[str, Any], key: str, source_path: Path) -> list[str]:
    value = entry.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise PolicyLoaderError(f"{source_path}: {key} must be an array of strings")
    return [_require_scalar_text(item, source_path, key) for item in value]


def _require_entry_int(entry: dict[str, Any], key: str, source_path: Path) -> int:
    value = entry.get(key)
    if not isinstance(value, int):
        raise PolicyLoaderError(f"{source_path}: {key} must be an integer")
    return value


def _require_entry_bool(entry: dict[str, Any], key: str, source_path: Path) -> bool:
    value = entry.get(key)
    if not isinstance(value, bool):
        raise PolicyLoaderError(f"{source_path}: {key} must be a boolean")
    return value


def _optional_bool(value: Any, source_path: Path, key: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise PolicyLoaderError(f"{source_path}: {key} must be a boolean when provided")
    return value


def _normalize_optional_text(value: Any, source_path: Path, key: str) -> str | None:
    if value is None:
        return None
    return _normalize_token(_require_scalar_text(value, source_path, key))


def _normalize_token(value: str) -> str:
    return value.strip().lower()


def _normalize_terms(values: list[str]) -> tuple[str, ...]:
    return tuple(_normalize_token(value) for value in values)


def _parse_int_mapping(data: dict[str, Any], source_path: Path) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for key, value in data.items():
        if not isinstance(value, int):
            raise PolicyLoaderError(f"{source_path}: {key} must be an integer")
        parsed[_normalize_token(key)] = value
    return parsed


def _parse_risk_level(
    value: Any,
    source_path: Path,
    *,
    allow_none: bool = False,
) -> RiskLevel | None:
    if value is None:
        if allow_none:
            return None
        raise PolicyLoaderError(f"{source_path}: risk level is required")
    if not isinstance(value, str):
        raise PolicyLoaderError(f"{source_path}: risk level must be a string")
    try:
        return RiskLevel(value.strip())
    except ValueError as exc:
        allowed = ", ".join(level.value for level in RiskLevel)
        raise PolicyLoaderError(
            f"{source_path}: risk level must be one of {allowed}"
        ) from exc


def _compute_policy_digest(source_files: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in source_files:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]
