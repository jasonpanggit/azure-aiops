from operations.page_context import PageSnapshot


def test_snapshot_rejects_non_canonical_resource_ids():
    snapshot = PageSnapshot(
        page_kind="network", page_id="network", question="Review network",
        selected_resources=[{"resource_id": "not-an-azure-id", "resource_type": "vnet"}],
    )
    try:
        snapshot.validate_effective_scope(__import__("api.scope", fromlist=["Scope"]).Scope.unrestricted())
    except ValueError as exc:
        assert "canonical" in str(exc)
    else:
        raise AssertionError("non-canonical resource was accepted")
