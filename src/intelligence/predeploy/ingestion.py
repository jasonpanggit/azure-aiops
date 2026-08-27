"""Change ingestion: five source formats, one normalized model.

Each parser is deliberately defensive. A change-review tool that throws on an
unfamiliar payload is useless precisely when it matters most, so an unreadable
fragment becomes an ``ingestion_warning`` (which downstream turns into a
declared unknown and suppresses confidence) instead of an exception. The only
hard failures are structural: a payload that is not the format it claims to be.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .models import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_NOOP,
    ACTION_REPLACE,
    ACTION_UNKNOWN,
    ACTION_UPDATE,
    SOURCE_ARM,
    SOURCE_AZURE_DEVOPS,
    SOURCE_BICEP,
    SOURCE_GITHUB,
    SOURCE_TERRAFORM,
    ProposedChange,
    ProposedResourceChange,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _changed_properties(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[str, ...]:
    """Top-level property names whose values differ between before and after."""
    names = sorted(set(before) | set(after))
    return tuple(name for name in names if before.get(name) != after.get(name))


# --------------------------------------------------------------------------
# Terraform
# --------------------------------------------------------------------------

# Terraform encodes intent as an ordered action list. ``["delete", "create"]``
# is a replace; the pair must be read together, not as two separate changes.
_TERRAFORM_ACTIONS: dict[tuple[str, ...], str] = {
    ("create",): ACTION_CREATE,
    ("update",): ACTION_UPDATE,
    ("delete",): ACTION_DELETE,
    ("no-op",): ACTION_NOOP,
    ("read",): ACTION_NOOP,
    ("delete", "create"): ACTION_REPLACE,
    ("create", "delete"): ACTION_REPLACE,
}


def parse_terraform_plan(payload: Mapping[str, Any], *, change_id: str = "") -> ProposedChange:
    """Normalize `terraform show -json <plan>` output."""
    data = _mapping(payload)
    warnings: list[str] = []
    changes: list[ProposedResourceChange] = []
    subscriptions: list[str] = []

    raw_changes = _sequence(data.get("resource_changes"))
    if not raw_changes and "resource_changes" not in data:
        warnings.append(
            "Terraform payload has no resource_changes array; the plan may not be JSON plan output."
        )

    for index, entry in enumerate(raw_changes):
        item = _mapping(entry)
        address = _text(item.get("address"))
        if not address:
            warnings.append(f"Terraform resource change at index {index} has no address and was skipped.")
            continue
        change_block = _mapping(item.get("change"))
        actions = tuple(_text(action).casefold() for action in _sequence(change_block.get("actions")))
        action = _TERRAFORM_ACTIONS.get(actions, ACTION_UNKNOWN)
        if action is ACTION_UNKNOWN and actions:
            warnings.append(f"Unrecognized Terraform action {list(actions)!r} for {address}.")
        before = _mapping(change_block.get("before"))
        after = _mapping(change_block.get("after"))
        # after_unknown marks values Terraform cannot resolve until apply. They
        # are real changes with unknowable values, so they count as changed
        # properties but are also surfaced as an explicit unknown.
        after_unknown = _mapping(change_block.get("after_unknown"))
        properties = list(_changed_properties(before, after))
        for name, unknown in after_unknown.items():
            if unknown and name not in properties:
                properties.append(name)
        if after_unknown:
            warnings.append(
                f"{address}: {len(after_unknown)} propert"
                f"{'y is' if len(after_unknown) == 1 else 'ies are'} unknown until apply."
            )
        resource_id = _text(after.get("id")) or _text(before.get("id"))
        if resource_id:
            subscription = _subscription_from_arm_id(resource_id)
            if subscription:
                subscriptions.append(subscription)
        changes.append(
            ProposedResourceChange(
                address=address,
                action=action,
                resource_type=_text(item.get("type")),
                resource_id=resource_id,
                name=_text(item.get("name")),
                provider=_text(item.get("provider_name")),
                changed_properties=tuple(properties),
                before=before,
                after=after,
                source_ref=f"resource_changes[{index}]",
            )
        )

    return ProposedChange(
        change_id=change_id or _text(data.get("terraform_version")) or "terraform-plan",
        source=SOURCE_TERRAFORM,
        resource_changes=tuple(changes),
        title=_text(data.get("title")),
        target_subscriptions=tuple(subscriptions),
        ingestion_warnings=tuple(warnings),
    )


# --------------------------------------------------------------------------
# Bicep what-if / ARM
# --------------------------------------------------------------------------

_WHAT_IF_ACTIONS: dict[str, str] = {
    "create": ACTION_CREATE,
    "modify": ACTION_UPDATE,
    "deploy": ACTION_UPDATE,
    "delete": ACTION_DELETE,
    "ignore": ACTION_NOOP,
    "nochange": ACTION_NOOP,
    "unsupported": ACTION_UNKNOWN,
}


def parse_bicep_what_if(payload: Mapping[str, Any], *, change_id: str = "") -> ProposedChange:
    """Normalize `az deployment ... what-if --no-pretty-print` JSON."""
    data = _mapping(payload)
    warnings: list[str] = []
    changes: list[ProposedResourceChange] = []
    subscriptions: list[str] = []

    entries = _sequence(data.get("changes")) or _sequence(
        _mapping(data.get("properties")).get("changes")
    )
    if not entries:
        warnings.append("What-if payload contained no changes array.")

    for index, entry in enumerate(entries):
        item = _mapping(entry)
        resource_id = _text(item.get("resourceId"))
        if not resource_id:
            warnings.append(f"What-if change at index {index} has no resourceId and was skipped.")
            continue
        change_type = _text(item.get("changeType")).casefold()
        action = _WHAT_IF_ACTIONS.get(change_type, ACTION_UNKNOWN)
        if action is ACTION_UNKNOWN:
            warnings.append(
                f"{resource_id}: what-if changeType {change_type or 'missing'!r} is not "
                "supported for prediction."
            )
        before = _mapping(item.get("before"))
        after = _mapping(item.get("after"))
        # what-if reports a structured delta; prefer it over diffing before/after
        # because it already resolved ARM's property-level semantics.
        deltas = [
            _text(_mapping(delta).get("path"))
            for delta in _sequence(item.get("delta"))
            if _text(_mapping(delta).get("path"))
        ]
        properties = tuple(deltas) if deltas else _changed_properties(before, after)
        subscription = _subscription_from_arm_id(resource_id)
        if subscription:
            subscriptions.append(subscription)
        changes.append(
            ProposedResourceChange(
                address=resource_id,
                action=action,
                resource_type=_resource_type_from_arm_id(resource_id),
                resource_id=resource_id,
                name=resource_id.rsplit("/", 1)[-1],
                provider="azure",
                changed_properties=properties,
                before=before,
                after=after,
                source_ref=f"changes[{index}]",
            )
        )

    return ProposedChange(
        change_id=change_id or "bicep-what-if",
        source=SOURCE_BICEP,
        resource_changes=tuple(changes),
        target_subscriptions=tuple(subscriptions),
        ingestion_warnings=tuple(warnings),
    )


def parse_arm_diff(payload: Mapping[str, Any], *, change_id: str = "") -> ProposedChange:
    """Normalize a raw ARM template diff.

    Shares the what-if vocabulary but reports ``source`` as ``arm_diff`` so
    provenance stays honest about which pipeline produced the assessment.
    """
    normalized = parse_bicep_what_if(payload, change_id=change_id or "arm-diff")
    return ProposedChange(
        change_id=normalized.change_id,
        source=SOURCE_ARM,
        resource_changes=normalized.resource_changes,
        title=normalized.title,
        target_subscriptions=normalized.target_subscriptions,
        ingestion_warnings=normalized.ingestion_warnings,
    )


# --------------------------------------------------------------------------
# GitHub / Azure DevOps
# --------------------------------------------------------------------------

# Infrastructure-as-code file suffixes. A pull request that touches none of
# these still ingests, but yields no resource-level intent — which is reported
# as an unknown rather than as "no impact".
_IAC_SUFFIXES = (".tf", ".tfvars", ".bicep", ".json", ".yaml", ".yml")

_PR_STATUS_ACTIONS = {
    "added": ACTION_CREATE,
    "add": ACTION_CREATE,
    "modified": ACTION_UPDATE,
    "edit": ACTION_UPDATE,
    "changed": ACTION_UPDATE,
    "removed": ACTION_DELETE,
    "delete": ACTION_DELETE,
    "renamed": ACTION_UPDATE,
}


def _parse_code_review(
    payload: Mapping[str, Any],
    *,
    source: str,
    change_id: str,
    files_key: str,
    path_key: str,
    status_key: str,
    path_container: str = "",
) -> ProposedChange:
    data = _mapping(payload)
    warnings: list[str] = []
    changes: list[ProposedResourceChange] = []

    files = _sequence(data.get(files_key))
    iac_files = 0
    for index, entry in enumerate(files):
        item = _mapping(entry)
        # Azure DevOps nests the path inside an ``item`` object while keeping the
        # change type on the entry itself, so the two are read from different levels.
        path_source = _mapping(item.get(path_container)) if path_container else item
        path = _text(path_source.get(path_key))
        if not path:
            continue
        if not path.casefold().endswith(_IAC_SUFFIXES):
            continue
        iac_files += 1
        action = _PR_STATUS_ACTIONS.get(_text(item.get(status_key)).casefold(), ACTION_UNKNOWN)
        changes.append(
            ProposedResourceChange(
                address=path,
                action=action,
                resource_type="iac_file",
                name=path.rsplit("/", 1)[-1],
                provider=source,
                changed_properties=(path,),
                source_ref=f"{files_key}[{index}]",
            )
        )

    if not files:
        warnings.append("No changed files were provided; resource-level intent is unknown.")
    elif not iac_files:
        warnings.append(
            "No infrastructure-as-code files were changed; infrastructure impact cannot be "
            "derived from this pull request alone."
        )
    # A code-review payload names files, not Azure resources. Attaching a plan
    # is the only way to know what those files actually deploy, so this is
    # always declared rather than inferred.
    warnings.append(
        "Source control changes describe files, not resource state; attach a Terraform plan "
        "or what-if result for resource-level assessment."
    )

    return ProposedChange(
        change_id=change_id or _text(data.get("number")) or _text(data.get("pullRequestId")) or "pull-request",
        source=source,
        resource_changes=tuple(changes),
        title=_text(data.get("title")),
        author=_text(_mapping(data.get("user")).get("login"))
        or _text(_mapping(data.get("createdBy")).get("displayName")),
        submitted_at=_text(data.get("created_at")) or _text(data.get("creationDate")),
        repository=_text(_mapping(data.get("repository")).get("full_name"))
        or _text(_mapping(data.get("repository")).get("name")),
        target_environment=_text(data.get("environment")),
        ingestion_warnings=tuple(warnings),
    )


def parse_github_pull_request(payload: Mapping[str, Any], *, change_id: str = "") -> ProposedChange:
    """Normalize a GitHub pull request plus its changed-file list."""
    return _parse_code_review(
        payload,
        source=SOURCE_GITHUB,
        change_id=change_id,
        files_key="files",
        path_key="filename",
        status_key="status",
    )


def parse_azure_devops_change(payload: Mapping[str, Any], *, change_id: str = "") -> ProposedChange:
    """Normalize an Azure DevOps pull request plus its change entries."""
    return _parse_code_review(
        payload,
        source=SOURCE_AZURE_DEVOPS,
        change_id=change_id,
        files_key="changes",
        path_key="path",
        status_key="changeType",
        path_container="item",
    )


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------

_PARSERS = {
    SOURCE_TERRAFORM: parse_terraform_plan,
    SOURCE_BICEP: parse_bicep_what_if,
    SOURCE_ARM: parse_arm_diff,
    SOURCE_GITHUB: parse_github_pull_request,
    SOURCE_AZURE_DEVOPS: parse_azure_devops_change,
}


def ingest(source: str, payload: Mapping[str, Any], *, change_id: str = "") -> ProposedChange:
    """Normalize any supported change payload into a :class:`ProposedChange`."""
    key = _text(source).casefold()
    parser = _PARSERS.get(key)
    if parser is None:
        raise ValueError(
            f"Unsupported change source {source!r}. Supported: {', '.join(sorted(_PARSERS))}"
        )
    return parser(payload, change_id=change_id)


def _subscription_from_arm_id(resource_id: str) -> str:
    parts = [part for part in _text(resource_id).split("/") if part]
    for index, part in enumerate(parts):
        if part.casefold() == "subscriptions" and index + 1 < len(parts):
            return parts[index + 1].casefold()
    return ""


def _resource_type_from_arm_id(resource_id: str) -> str:
    parts = [part for part in _text(resource_id).split("/") if part]
    for index, part in enumerate(parts):
        if part.casefold() == "providers" and index + 2 < len(parts):
            namespace = parts[index + 1]
            remainder = parts[index + 2 :]
            # Type segments alternate type/name; keep only the type segments.
            types = remainder[::2]
            return f"{namespace}/{'/'.join(types)}"
    return ""
