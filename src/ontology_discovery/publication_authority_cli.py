"""Default-off manual read-only validator for signed publication reviews."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO
from uuid import UUID

from ontology_discovery.maintenance_release import (
    MaintenanceConfigError,
    MaintenanceDenied,
    MaintenanceReleaseReader,
    build_production_reader,
)
from ontology_discovery.publication_authority import PublicationAuthorityIssuer
from ontology_discovery.sql_publication_control import (
    FabricSqlControlTarget,
    SqlPublicationControl,
    SqlPublicationError,
)

_CONFIG_ENV = "ONTOLOGY_PUBLICATION_VALIDATION_CONFIG"
_SCHEMA = "publication-authority-validation/v1"
_TARGET_FIELDS = frozenset(
    {
        "tenant_id",
        "subscription_id",
        "connection_id",
        "workspace_id",
        "item_id",
        "definition_fingerprint",
    }
)


class ValidationConfigError(ValueError):
    """Sanitized invalid or unavailable server-owned validator configuration."""


@dataclass(frozen=True)
class ValidationConfig:
    """Strict operator-owned inputs for the read-only validation command."""

    reader_client_id: str
    target_id: str
    sql_target: FabricSqlControlTarget
    expected_target: Mapping[str, str]
    review_path: Path
    revocation_path: Path


def _read_object(path: Path, reason: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValidationConfigError(reason) from None
    if not isinstance(value, Mapping):
        raise ValidationConfigError(reason)
    return value


def _absolute_path(value: object, reason: str) -> Path:
    if type(value) is not str or not value:
        raise ValidationConfigError(reason)
    path = Path(value)
    if not path.is_absolute():
        raise ValidationConfigError(reason)
    return path


def load_validation_config(path: Path) -> ValidationConfig:
    """Load exact config fields and verify SQLDatabase metadata pins."""

    raw = _read_object(path, "publication_validation_config_unavailable")
    required = {
        "schema",
        "reader_client_id",
        "target_id",
        "sql_target",
        "fabric_item_metadata",
        "expected_target",
        "review_path",
        "revocation_path",
    }
    if set(raw) != required or raw.get("schema") != _SCHEMA:
        raise ValidationConfigError("publication_validation_config_invalid")

    reader_client_id = raw.get("reader_client_id")
    target_id = raw.get("target_id")
    if (
        type(reader_client_id) is not str
        or type(target_id) is not str
        or not reader_client_id
        or not target_id
    ):
        raise ValidationConfigError("publication_validation_config_invalid")
    try:
        if (
            str(UUID(reader_client_id)) != reader_client_id
            or str(UUID(target_id)) != target_id
        ):
            raise ValueError
    except ValueError:
        raise ValidationConfigError("publication_validation_config_invalid") from None

    sql_raw = raw.get("sql_target")
    sql_fields = {"workspace_id", "item_id", "server", "database"}
    if not isinstance(sql_raw, Mapping) or set(sql_raw) != sql_fields:
        raise ValidationConfigError("publication_validation_config_invalid")
    target_values = tuple(sql_raw[field] for field in sorted(sql_fields))
    if any(type(value) is not str for value in target_values):
        raise ValidationConfigError("publication_validation_config_invalid")
    try:
        sql_target = FabricSqlControlTarget(
            workspace_id=sql_raw["workspace_id"],
            item_id=sql_raw["item_id"],
            server=sql_raw["server"],
            database=sql_raw["database"],
        )
    except (KeyError, TypeError, ValueError, SqlPublicationError):
        raise ValidationConfigError(
            "publication_validation_sql_target_invalid"
        ) from None
    metadata = raw.get("fabric_item_metadata")
    if not isinstance(metadata, Mapping):
        raise ValidationConfigError("publication_validation_sql_target_invalid")
    try:
        sql_target.verify_item(metadata)
    except (AttributeError, SqlPublicationError):
        raise ValidationConfigError(
            "publication_validation_sql_target_invalid"
        ) from None

    expected_target = raw.get("expected_target")
    if (
        not isinstance(expected_target, Mapping)
        or set(expected_target) != _TARGET_FIELDS
        or any(
            type(value) is not str or not value for value in expected_target.values()
        )
    ):
        raise ValidationConfigError("publication_validation_target_invalid")

    return ValidationConfig(
        reader_client_id=reader_client_id,
        target_id=target_id,
        sql_target=sql_target,
        expected_target=dict(expected_target),
        review_path=_absolute_path(
            raw.get("review_path"), "publication_validation_review_path_invalid"
        ),
        revocation_path=_absolute_path(
            raw.get("revocation_path"),
            "publication_validation_revocation_path_invalid",
        ),
    )


def _source(path: Path, reason: str) -> Callable[[], Mapping[str, Any]]:
    def read() -> Mapping[str, Any]:
        return _read_object(path, reason)

    return read


def _emit(
    stream: TextIO, *, status: str, reason: str | None = None, **values: Any
) -> None:
    result: dict[str, Any] = {"status": status, **values}
    if reason is not None:
        result["reason"] = reason
    stream.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")


def run_validation(
    config: ValidationConfig,
    release_reader: MaintenanceReleaseReader,
    credential_factory: Callable[[str], Any],
) -> str:
    """Run only the signed-review validation using the reader identity."""

    credential = credential_factory(config.reader_client_id)
    try:
        control = SqlPublicationControl(
            config.sql_target,
            credential,
            expected_client_id=config.reader_client_id,
        )
        validator = PublicationAuthorityIssuer(
            trust=release_reader.trust_context,
            release_reader=release_reader,
            control=control,
            target_id=config.target_id,
            expected_target=config.expected_target,
            review_source=_source(
                config.review_path, "publication_validation_review_unavailable"
            ),
            revocation_source=_source(
                config.revocation_path,
                "publication_validation_revocation_unavailable",
            ),
        )
        return validator.validate("admit")
    finally:
        close = getattr(credential, "close", None)
        if callable(close):
            close()


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    reader_factory: Callable[[Mapping[str, str]], Any] | None = None,
    credential_factory: Callable[[str], Any] | None = None,
) -> int:
    """Run the default-off manual validator and return its process exit code."""

    arguments = sys.argv[1:] if argv is None else argv
    env = os.environ if environ is None else environ
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    if arguments:
        _emit(err, status="FAIL", reason="publication_validation_arguments_unsupported")
        return 2
    config_path = str(env.get(_CONFIG_ENV) or "").strip()
    if not config_path:
        _emit(err, status="FAIL", reason="publication_validation_config_required")
        return 2
    try:
        config = load_validation_config(Path(config_path))
        configured_identity = str(env.get("AZURE_CLIENT_ID") or "").strip()
        if (
            configured_identity
            and configured_identity.lower() != config.reader_client_id.lower()
        ):
            raise ValidationConfigError("publication_validation_identity_mismatch")
        runtime_env = dict(env)
        runtime_env["AZURE_CLIENT_ID"] = config.reader_client_id

        import pyodbc

        pyodbc.pooling = False
        if reader_factory is None:
            release_reader = build_production_reader(runtime_env)
        else:
            release_reader = reader_factory(runtime_env)
        if release_reader is None:
            raise MaintenanceConfigError("maintenance_trust_config_required")

        if credential_factory is None:
            from azure.identity import ManagedIdentityCredential

            credential_factory = lambda client_id: ManagedIdentityCredential(
                client_id=client_id
            )
        envelope_digest = run_validation(config, release_reader, credential_factory)
        _emit(
            out,
            status="PASS",
            operation="admit",
            envelope_digest=envelope_digest,
            authority_write=False,
        )
        return 0
    except (
        ValidationConfigError,
        MaintenanceConfigError,
        MaintenanceDenied,
        SqlPublicationError,
    ) as exc:
        _emit(err, status="FAIL", reason=str(exc))
        return 1
    except ImportError:
        _emit(
            err,
            status="FAIL",
            reason="publication_validation_runtime_dependency_missing",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
