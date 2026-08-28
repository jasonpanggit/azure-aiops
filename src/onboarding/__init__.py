"""Subscription onboarding, connection registry, validation, and sync lifecycle.

Submodules are resolved lazily so lightweight consumers -- notably the plugin
registration path -- can import this package without pulling in PyArrow, PyYAML,
or the Azure SDKs that the ingestion and storage layers require.
"""

from typing import TYPE_CHECKING

_EXPORTS = {
    "activate_runtime": ".activation",
    "publish_combined_snapshot": ".activation",
    "ChainedSecretProvider": ".credentials",
    "CredentialResolver": ".credentials",
    "EnvironmentSecretProvider": ".credentials",
    "KeyVaultSecretProvider": ".credentials",
    "KeyVaultSecretWriter": ".credentials",
    "SecretNotFoundError": ".credentials",
    "SecretProvider": ".credentials",
    "SecretStorageError": ".credentials",
    "SecretWriter": ".credentials",
    "redact": ".credentials",
    "redact_mapping": ".credentials",
    "HealthEvaluator": ".health",
    "BusinessMetadata": ".metadata",
    "ConnectionNotFoundError": ".registry",
    "ConnectionRegistry": ".registry",
    "DuplicateConnectionError": ".registry",
    "RegistryConflictError": ".registry",
    "OnboardingError": ".service",
    "SubscriptionOnboardingService": ".service",
    "ConnectionSyncCoordinator": ".sync",
    "SyncResult": ".sync",
    "CONNECTION_CHECKS": ".validation",
    "CheckResult": ".validation",
    "ConnectionProbe": ".validation",
    "ConnectionValidator": ".validation",
    "ValidationReport": ".validation",
}

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from .activation import activate_runtime, publish_combined_snapshot
    from .credentials import (
        ChainedSecretProvider,
        CredentialResolver,
        EnvironmentSecretProvider,
        KeyVaultSecretProvider,
        KeyVaultSecretWriter,
        SecretNotFoundError,
        SecretProvider,
        SecretStorageError,
        SecretWriter,
        redact,
        redact_mapping,
    )
    from .health import HealthEvaluator
    from .metadata import BusinessMetadata
    from .registry import (
        ConnectionNotFoundError,
        ConnectionRegistry,
        DuplicateConnectionError,
        RegistryConflictError,
    )
    from .service import OnboardingError, SubscriptionOnboardingService
    from .sync import ConnectionSyncCoordinator, SyncResult
    from .validation import (
        CONNECTION_CHECKS,
        CheckResult,
        ConnectionProbe,
        ConnectionValidator,
        ValidationReport,
    )


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_name, __name__), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = sorted(_EXPORTS)
