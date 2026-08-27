"""Change risk and pre-deployment impact engine.

Assesses proposed infrastructure and application changes *before* they are
deployed. This is deliberately separate from :mod:`intelligence.change`, which
analyses changes that have already happened: nothing here observes the estate's
response to a change, because the change has not occurred yet.

Pipeline::

    ingest -> compare against discovered state -> blast radius
           -> simulate -> score risk -> CAB recommendation
"""

from __future__ import annotations

from .blast_radius import analyze_blast_radius
from .cab import (
    VERDICT_APPROVE,
    VERDICT_APPROVE_WITH_CONDITIONS,
    VERDICT_REQUIRE_REVIEW,
    recommend,
)
from .ingestion import (
    ingest,
    parse_arm_diff,
    parse_azure_devops_change,
    parse_bicep_what_if,
    parse_github_pull_request,
    parse_terraform_plan,
)
from .models import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_NOOP,
    ACTION_REPLACE,
    ACTION_UPDATE,
    CHANGE_ACTIONS,
    CHANGE_SOURCES,
    DESTRUCTIVE_ACTIONS,
    SOURCE_ARM,
    SOURCE_AZURE_DEVOPS,
    SOURCE_BICEP,
    SOURCE_GITHUB,
    SOURCE_TERRAFORM,
    DiscoveredResource,
    ProposedChange,
    ProposedResourceChange,
    dependents_of,
    index_by_resource_id,
)
from .risk import risk_level, score_change
from .service import SOURCE_ENGINE, PreDeploymentImpactService
from .simulation import SIMULATION_DOMAINS, classify_domain, simulate
from .state_comparison import (
    FINDING_MATCHED,
    FINDING_MISSING_TARGET,
    FINDING_UNMANAGED_DRIFT,
    FINDING_UNTRACKED_CREATE,
    compare_states,
)

__all__ = [
    "ACTION_CREATE",
    "ACTION_DELETE",
    "ACTION_NOOP",
    "ACTION_REPLACE",
    "ACTION_UPDATE",
    "CHANGE_ACTIONS",
    "CHANGE_SOURCES",
    "DESTRUCTIVE_ACTIONS",
    "FINDING_MATCHED",
    "FINDING_MISSING_TARGET",
    "FINDING_UNMANAGED_DRIFT",
    "FINDING_UNTRACKED_CREATE",
    "SIMULATION_DOMAINS",
    "SOURCE_ARM",
    "SOURCE_AZURE_DEVOPS",
    "SOURCE_BICEP",
    "SOURCE_ENGINE",
    "SOURCE_GITHUB",
    "SOURCE_TERRAFORM",
    "VERDICT_APPROVE",
    "VERDICT_APPROVE_WITH_CONDITIONS",
    "VERDICT_REQUIRE_REVIEW",
    "DiscoveredResource",
    "PreDeploymentImpactService",
    "ProposedChange",
    "ProposedResourceChange",
    "analyze_blast_radius",
    "classify_domain",
    "compare_states",
    "dependents_of",
    "index_by_resource_id",
    "ingest",
    "parse_arm_diff",
    "parse_azure_devops_change",
    "parse_bicep_what_if",
    "parse_github_pull_request",
    "parse_terraform_plan",
    "recommend",
    "risk_level",
    "score_change",
    "simulate",
]
