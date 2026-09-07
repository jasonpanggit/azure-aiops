from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from intelligence.vulnerability.acquisition import (
    AcquisitionFailure,
    AcquisitionOutcome,
    AcquisitionSuccess,
    PagingProof,
    classify_provider_error,
    event_watermark,
    safe_error_summary,
)

from .azure_clients import (
    AzureCliArgClient,
    AzureCostManagementClient,
    AzureMcpClient,
    PagedArgQueryResult,
)

logger = logging.getLogger(__name__)


@dataclass
class AzureResourceGraphSource:
    mcp: AzureMcpClient | None
    arg: AzureCliArgClient
    tenant_id: str = ""
    max_workers: int = 5
    management_group_ids: tuple[str, ...] = ()
    connection_id: str = ""
    discovery_timeout_seconds: float = 120
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def list_subscriptions(self) -> list[dict]:
        if self.mcp is None:
            return []
        return self.mcp.list_subscriptions(self.tenant_id)

    def fetch(
        self,
        specs,
        subscription_ids: list[str],
    ) -> dict[str, AcquisitionOutcome]:
        """Return one typed outcome per executable query specification."""

        if not specs:
            return {}
        workers = max(1, min(self.max_workers, len(specs)))
        results: dict[str, AcquisitionOutcome] = {}
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="arg-query")
        attempted_at_by_name: dict[str, datetime] = {}
        scope_by_name: dict[str, tuple[str, ...]] = {}
        executable_specs = []
        for spec in specs:
            if spec.scope == "management_groups" and not self.management_group_ids:
                continue
            executable_specs.append(spec)
            attempted_at_by_name[spec.name] = self.clock()
            scope_by_name[spec.name] = tuple(
                sorted(
                    self.management_group_ids
                    if spec.scope == "management_groups"
                    else subscription_ids
                )
            )
        futures = {
            executor.submit(
                self._query_with_metadata,
                spec,
                list(scope_by_name[spec.name]),
            ): spec
            for spec in executable_specs
        }
        try:
            # Bound the whole discovery batch as well as each individual CLI
            # invocation; a provider can otherwise leave a future unresolved.
            for future in as_completed(
                futures,
                timeout=self.discovery_timeout_seconds,
            ):
                spec = futures[future]
                completed_at = self.clock()
                try:
                    query_result = future.result()
                    rows = tuple(query_result.rows)
                    results[spec.name] = AcquisitionSuccess(
                        connection_id=self.connection_id,
                        query_name=spec.name,
                        source_family=getattr(spec, "source_family", "") or spec.name,
                        scope=scope_by_name[spec.name],
                        attempted_at=attempted_at_by_name[spec.name],
                        completed_at=completed_at,
                        paging=PagingProof(
                            pages_fetched=query_result.pages_fetched,
                            page_size=query_result.page_size,
                            max_pages=query_result.max_pages,
                            row_count=len(rows),
                            complete=query_result.complete,
                        ),
                        watermark=event_watermark(rows),
                        sequence=f"{spec.version}:{query_result.pages_fetched}:{len(rows)}",
                        rows=rows,
                    )
                except Exception as exc:
                    logger.warning(
                        "ARG acquisition failed for query %s; protected details follow",
                        spec.name,
                        exc_info=True,
                    )
                    code = classify_provider_error(exc)
                    results[spec.name] = AcquisitionFailure(
                        connection_id=self.connection_id,
                        query_name=spec.name,
                        source_family=getattr(spec, "source_family", "") or spec.name,
                        scope=scope_by_name[spec.name],
                        attempted_at=attempted_at_by_name[spec.name],
                        completed_at=completed_at,
                        error_code=code,
                        error_summary=safe_error_summary(code),
                    )
        except FutureTimeoutError:
            for future, spec in futures.items():
                if future.done():
                    continue
                future.cancel()
                code = classify_provider_error(TimeoutError())
                results[spec.name] = AcquisitionFailure(
                    connection_id=self.connection_id,
                    query_name=spec.name,
                    source_family=spec.source_family or spec.name,
                    scope=scope_by_name[spec.name],
                    attempted_at=attempted_at_by_name[spec.name],
                    completed_at=self.clock(),
                    error_code=code,
                    error_summary=safe_error_summary(code),
                )
        finally:
            # A provider subprocess can outlive its caller despite its own
            # timeout. Do not wait for that worker before returning the sync.
            executor.shutdown(wait=False)
        return results

    def _query_with_metadata(
        self,
        spec: Any,
        scope_ids: list[str],
    ) -> PagedArgQueryResult:
        query_with_metadata = getattr(self.arg, "query_with_metadata", None)
        if callable(query_with_metadata):
            result = query_with_metadata(spec, scope_ids)
            if not isinstance(result, PagedArgQueryResult):
                raise TypeError("ARG client returned invalid paging metadata")
            if not result.complete:
                raise RuntimeError("ARG query paging incomplete")
            return result

        # Compatibility for test doubles and custom readers that predate the
        # paging-proof API. This proves only one adapter-returned page and is
        # not used by the production ARG clients.
        rows = self.arg.query(spec, scope_ids)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise TypeError("ARG client returned an invalid page")
        return PagedArgQueryResult(
            rows=tuple(rows),
            pages_fetched=1,
            page_size=max(1, len(rows)),
            max_pages=1,
            complete=True,
        )


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
