from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta

from .azure import AzureCliArgClient, AzureCostManagementClient, AzureMcpClient


@dataclass
class AzureResourceGraphSource:
    mcp: AzureMcpClient | None
    arg: AzureCliArgClient
    tenant_id: str = ""
    max_workers: int = 5
    management_group_ids: tuple[str, ...] = ()

    def list_subscriptions(self) -> list[dict]:
        if self.mcp is None:
            return []
        return self.mcp.list_subscriptions(self.tenant_id)

    def fetch(self, specs, subscription_ids: list[str]) -> dict[str, list[dict]]:
        workers = max(1, min(self.max_workers, len(specs)))
        results: dict[str, list[dict]] = {}
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="arg-query") as executor:
            futures = {
                executor.submit(
                    self.arg.query,
                    spec,
                    (
                        list(self.management_group_ids)
                        if spec.scope == "management_groups"
                        else subscription_ids
                    ),
                ): spec.name
                for spec in specs
                if spec.scope != "management_groups" or self.management_group_ids
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results[name] = future.result()
                except Exception as exc:  # noqa: BLE001 - preserve provider failure as data
                    results[name] = [
                        {
                            "status": "failed",
                            "provider_status": "failed",
                            "error": str(exc)[:2048],
                        }
                    ]
        return results


@dataclass
class CostActualsSource:
    """Fetches Azure Cost Management actuals, independent of ARG discovery.

    Cost Management is a distinct Azure API/service (billing) with its own
    throttling and outage characteristics. It is intentionally kept as a
    separate adapter from :class:`AzureResourceGraphSource` (semantic graph
    discovery) so ingestion can treat it as an optional, best-effort side
    channel rather than a dependency of graph discovery.
    """

    cost: AzureCostManagementClient | None = None

    def fetch(
        self,
        subscription_ids: list[str],
        *,
        end: datetime,
        lookback: timedelta,
    ) -> list[dict]:
        if self.cost is None:
            return []
        return self.cost.query_actual_costs(
            subscription_ids,
            end=end,
            lookback=lookback,
        )
