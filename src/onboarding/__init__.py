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
    from .activation import activate_runtime as activate_runtime
    from .activation import publish_combined_snapshot as publish_combined_snapshot
    from .credentials import ChainedSecretProvider as ChainedSecretProvider
    from .credentials import CredentialResolver as CredentialResolver
    from .credentials import EnvironmentSecretProvider as EnvironmentSecretProvider
    from .credentials import KeyVaultSecretProvider as KeyVaultSecretProvider
    from .credentials import KeyVaultSecretWriter as KeyVaultSecretWriter
    from .credentials import SecretNotFoundError as SecretNotFoundError
    from .credentials import SecretProvider as SecretProvider
    from .credentials import SecretStorageError as SecretStorageError
    from .credentials import SecretWriter as SecretWriter
    from .credentials import redact as redact
    from .credentials import redact_mapping as redact_mapping
    from .health import HealthEvaluator as HealthEvaluator
    from .metadata import BusinessMetadata as BusinessMetadata
    from .registry import ConnectionNotFoundError as ConnectionNotFoundError
    from .registry import ConnectionRegistry as ConnectionRegistry
    from .registry import DuplicateConnectionError as DuplicateConnectionError
    from .registry import RegistryConflictError as RegistryConflictError
    from .service import OnboardingError as OnboardingError
    from .service import SubscriptionOnboardingService as SubscriptionOnboardingService
    from .sync import ConnectionSyncCoordinator as ConnectionSyncCoordinator
    from .sync import SyncResult as SyncResult
    from .validation import CONNECTION_CHECKS as CONNECTION_CHECKS
    from .validation import CheckResult as CheckResult
    from .validation import ConnectionProbe as ConnectionProbe
    from .validation import ConnectionValidator as ConnectionValidator
    from .validation import ValidationReport as ValidationReport


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_name, __name__), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = sorted(_EXPORTS)  # noqa: PLE0605 - dynamically built from _EXPORTS keys (all strings)
