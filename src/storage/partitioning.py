from __future__ import annotations


class PartitioningPolicy:
    """Low-cardinality partition policy shared by every inventory table."""

    def columns_for(self, table_name: str) -> tuple[str, ...]:
        if table_name.startswith(("metadata_", "ontology_")):
            return ()
        return ("tenant_id", "subscription_id")
