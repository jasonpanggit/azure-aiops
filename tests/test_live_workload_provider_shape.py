from __future__ import annotations

import json

import pytest

from intelligence.vulnerability.workload_inventory import (
    WORKLOAD_QUERY_VERSIONS,
    WorkloadFailureCode,
    WorkloadQueryFailure,
    WorkloadQuerySuccess,
    activate_workload_partitions,
)
from onboarding.ingestion_service import _workload_defender_rows

DIGEST = "sha256:3f507e55ae28e2e1a87934bd39b21dcb8699cf7c8b7c6c0a59dc01d31fb458f9"


@pytest.mark.parametrize("optional_image_query", ["absent", "empty", "failed"])
@pytest.mark.parametrize("encoded_resource_data", [False, True])
def test_captured_defender_and_ama_default_stream_shape_produces_exact_deployment(
    optional_image_query: str,
    encoded_resource_data: bool,
) -> None:
    """Redacted provider rows preserve the captured Defender/Container Insights shape."""
    resource_data = {
        "Digest": DIGEST,
        "ImageUri": f"example.azurecr.io/validation/correlation@{DIGEST}",
    }
    defender_row = {
        "properties": {
            "resourceAdditionalData": (
                json.dumps(resource_data) if encoded_resource_data else resource_data
            ),
            "status": {
                "code": "Unhealthy",
                "statusChangeDate": "2026-11-01T08:38:59.0443508Z",
            },
        }
    }
    defender_rows = _workload_defender_rows(
        {"defender_subassessments": [defender_row]}
    )
    assert defender_rows == [defender_row]
    container_row = {
        "TimeGenerated": "2026-11-01T08:46:57Z",
        "ImageID": DIGEST,
        "Image": "validation/correlation",
        "ContainerID": "a" * 64,
    }
    pod_row = {
        "TimeGenerated": "2026-11-01T08:47:57Z",
        "ContainerID": "a" * 64,
        "ClusterId": "/subscriptions/example/resourceGroups/example/providers/"
        "Microsoft.ContainerService/managedClusters/example",
        "Namespace": "default",
        "ControllerKind": "Job",
        "ControllerName": "defender-correlation",
        "Name": "defender-correlation-example",
    }

    outcomes: tuple[WorkloadQuerySuccess | WorkloadQueryFailure, ...] = (
        WorkloadQuerySuccess(
            connection_id="connection-example",
            workspace_id="workspace-example",
            subscription_id="subscription-example",
            source_family="container_inventory",
            source_table="ContainerInventory",
            query_version=WORKLOAD_QUERY_VERSIONS["container_inventory"],
            attempted_at="2026-11-01T08:48:00Z",
            completed_at="2026-11-01T08:48:00Z",
            rows=(container_row,),
        ),
        WorkloadQuerySuccess(
            connection_id="connection-example",
            workspace_id="workspace-example",
            subscription_id="subscription-example",
            source_family="kube_pod_inventory",
            source_table="KubePodInventory",
            query_version=WORKLOAD_QUERY_VERSIONS["kube_pod_inventory"],
            attempted_at="2026-11-01T08:48:00Z",
            completed_at="2026-11-01T08:48:00Z",
            rows=(pod_row,),
        ),
    )
    if optional_image_query != "absent":
        common = {
            "connection_id": "connection-example",
            "workspace_id": "workspace-example",
            "subscription_id": "subscription-example",
            "source_family": "container_image_inventory",
            "source_table": "ContainerImageInventory",
            "query_version": WORKLOAD_QUERY_VERSIONS["container_image_inventory"],
            "attempted_at": "2026-11-01T08:48:00Z",
            "completed_at": "2026-11-01T08:48:00Z",
        }
        optional_outcome = (
            WorkloadQuerySuccess(**common, rows=())
            if optional_image_query == "empty"
            else WorkloadQueryFailure(
                **common,
                error_code=WorkloadFailureCode.PROVIDER_UNAVAILABLE,
                error_summary="Container Insights query is unavailable.",
            )
        )
        outcomes = (*outcomes, optional_outcome)
    projection = activate_workload_partitions(
        outcomes=outcomes,
        defender_rows=defender_rows,
        attempted_generation="captured-source-sample",
        completed_at="2026-11-01T08:48:00Z",
    )

    container_observation = next(
        row for row in projection.observations
        if row["source_family"] == "container_inventory"
    )
    pod_observation = next(
        row for row in projection.observations
        if row["source_family"] == "kube_pod_inventory"
    )
    assert container_observation["image_digest"] == DIGEST
    assert container_observation["container_id"] == pod_observation["container_id"]
    assert pod_observation["controller_kind"] == "Job"
    assert pod_observation["controller_name"] == "defender-correlation"

    assert len(projection.deployments) == 1
    deployment = projection.deployments[0]
    assert deployment["image_digest"] == DIGEST
    assert deployment["defender_observed_at"] == "2026-11-01T08:38:59.0443508Z"
    assert deployment["observed_at"] == pod_row["TimeGenerated"]
    assert deployment["container_id"] == container_row["ContainerID"]
    assert deployment["controller_name"] == pod_row["ControllerName"]
    assert deployment["effective_generation"] == "captured-source-sample"
    assert deployment["carried_forward"] is False
    provenance = json.loads(deployment["provenance_json"])
    assert provenance["container_observation_id"] == container_observation["observation_id"]
    assert provenance["pod_observation_id"] == pod_observation["observation_id"]
    assert provenance["image_observation_id"] is None
    assert projection.unknown_reasons == ()
    if optional_image_query != "absent":
        optional_checkpoint = next(
            row for row in projection.checkpoints
            if row["source_family"] == "container_image_inventory"
        )
        assert optional_checkpoint["status"] == (
            "healthy-empty" if optional_image_query == "empty" else "unavailable"
        )

    # Removing either supported family still fails closed without a deployment.
    for required_family in ("container_inventory", "kube_pod_inventory"):
        missing_required = activate_workload_partitions(
            outcomes=tuple(
                outcome for outcome in outcomes
                if outcome.source_family != required_family
            ),
            defender_rows=defender_rows,
            attempted_generation="captured-source-sample",
            completed_at="2026-11-01T08:48:00Z",
        )
        assert missing_required.deployments == ()
        assert missing_required.unknown_reasons == ("source_unavailable",)

    no_queries = activate_workload_partitions(
        outcomes=(),
        defender_rows=defender_rows,
        attempted_generation="captured-source-sample",
        completed_at="2026-11-01T08:48:00Z",
    )
    assert no_queries.deployments == ()
    assert no_queries.unknown_reasons == ("source_unavailable",)
