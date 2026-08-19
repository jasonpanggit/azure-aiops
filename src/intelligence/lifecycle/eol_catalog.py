from __future__ import annotations

import calendar
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class LifecycleStatus(StrEnum):
    SUPPORTED = "Supported"
    APPROACHING_EOL = "Approaching EOL"
    NEAR_EOL = "Near EOL"
    CRITICAL = "Critical"
    EOL = "EOL"
    UNKNOWN = "Unknown"


@dataclass(frozen=True)
class LifecycleCatalogEntry:
    product: str
    version: str
    release_date: str
    mainstream_support_end: str
    extended_support_end: str
    last_update_date: str
    recommended_upgrade_path: str
    source_url: str
    notes: str = ""
    default_support_channel: str = "mainstream"

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> LifecycleCatalogEntry:
        if not isinstance(row, dict):
            raise TypeError("Lifecycle catalog entry must be a mapping")
        entry = cls(
            product=str(row.get("product") or "").strip(),
            version=str(row.get("version") or "").strip(),
            release_date=_date_string(row.get("release_date"), "release_date"),
            mainstream_support_end=_date_string(
                row.get("mainstream_support_end"), "mainstream_support_end"
            ),
            extended_support_end=_date_string(
                row.get("extended_support_end"), "extended_support_end"
            ),
            last_update_date=_date_string(
                row.get("last_update_date"), "last_update_date"
            ),
            recommended_upgrade_path=str(
                row.get("recommended_upgrade_path") or ""
            ).strip(),
            source_url=str(row.get("source_url") or "").strip(),
            notes=str(row.get("notes") or "").strip(),
            default_support_channel=str(
                row.get("default_support_channel") or "mainstream"
            ).strip().casefold(),
        )
        if not entry.product or not entry.version or not entry.recommended_upgrade_path:
            raise ValueError("Lifecycle catalog entries require product, version, and upgrade path")
        if not (
            date.fromisoformat(entry.release_date)
            <= date.fromisoformat(entry.mainstream_support_end)
            <= date.fromisoformat(entry.extended_support_end)
        ):
            raise ValueError(
                "Lifecycle dates must order release <= mainstream <= extended support"
            )
        if entry.default_support_channel not in {"mainstream", "extended"}:
            raise ValueError(
                "Lifecycle default_support_channel must be mainstream or extended"
            )
        parsed_url = urlparse(entry.source_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ValueError("Lifecycle catalog source_url must use HTTPS")
        allowed_domains = {
            "windows server": {"learn.microsoft.com"},
            "sql server": {"learn.microsoft.com"},
            "azure stack hci": {"learn.microsoft.com", "techcommunity.microsoft.com"},
            "azure local": {"learn.microsoft.com"},
            "ubuntu": {"ubuntu.com"},
            "red hat enterprise linux": {"access.redhat.com"},
            "debian": {"debian.org", "www.debian.org"},
            "kubernetes": {"kubernetes.io", "www.kubernetes.io"},
        }
        expected = allowed_domains.get(" ".join(entry.product.casefold().split()))
        if expected and parsed_url.netloc.casefold() not in expected:
            raise ValueError(
                f"Lifecycle catalog {entry.product} requires an authoritative vendor domain"
            )
        return entry

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LifecycleClassification:
    status: LifecycleStatus
    support_end: str | None
    days_remaining: int | None
    support_channel: str
    confidence: float
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["evidence"] = list(self.evidence)
        return payload


class EOLCatalog:
    """Versioned authoritative lifecycle metadata with deterministic matching."""

    def __init__(
        self,
        entries: list[LifecycleCatalogEntry],
        *,
        approaching_months: int = 24,
        near_months: int = 12,
        critical_months: int = 6,
    ) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (approaching_months, near_months, critical_months)
        ) or not (
            approaching_months > near_months > critical_months > 0
        ):
            raise ValueError(
                "Lifecycle thresholds must descend: approaching > near > critical > 0"
            )
        self.approaching_months = approaching_months
        self.near_months = near_months
        self.critical_months = critical_months
        self._entries: dict[tuple[str, str], LifecycleCatalogEntry] = {}
        for entry in entries:
            key = self._key(entry.product, entry.version)
            if key in self._entries:
                raise ValueError("Duplicate lifecycle catalog product/version")
            self._entries[key] = entry

    @classmethod
    def from_rows(
        cls, rows: list[dict[str, Any]], **kwargs: Any
    ) -> EOLCatalog:
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise TypeError("Lifecycle catalog rows must be a list of mappings")
        return cls([LifecycleCatalogEntry.from_mapping(row) for row in rows], **kwargs)

    @classmethod
    def from_file(cls, path: str | Path, **kwargs: Any) -> EOLCatalog:
        payload = json.loads(Path(path).read_text())
        rows = payload.get("entries") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise TypeError("Lifecycle catalog file must contain an entries list")
        return cls.from_rows(rows, **kwargs)

    @classmethod
    def default(cls, **kwargs: Any) -> EOLCatalog:
        path = files("intelligence.lifecycle").joinpath("default_catalog.json")
        payload = json.loads(path.read_text())
        rows = payload.get("entries") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise TypeError("Default lifecycle catalog must contain entries")
        return cls.from_rows(rows, **kwargs)

    @property
    def freshness(self) -> str:
        return max(
            (entry.last_update_date for entry in self._entries.values()),
            default="",
        )

    def rows(self) -> list[dict[str, Any]]:
        return [
            self._entries[key].to_dict() for key in sorted(self._entries)
        ]

    def lookup(self, product: str, version: str) -> LifecycleCatalogEntry | None:
        return self._entries.get(self._key(product, version))

    def update(self, rows: list[dict[str, Any]]) -> EOLCatalog:
        merged = dict(self._entries)
        for row in rows:
            entry = LifecycleCatalogEntry.from_mapping(row)
            merged[self._key(entry.product, entry.version)] = entry
        return EOLCatalog(
            list(merged.values()),
            approaching_months=self.approaching_months,
            near_months=self.near_months,
            critical_months=self.critical_months,
        )

    def classify_product(
        self,
        product: str,
        version: str,
        *,
        now: datetime,
        support_channel: str | None = None,
    ) -> LifecycleClassification:
        entry = self.lookup(product, version)
        if entry is None:
            return LifecycleClassification(
                LifecycleStatus.UNKNOWN,
                None,
                None,
                support_channel or "mainstream",
                0.0,
                (f"No authoritative lifecycle entry matches {product} {version}.",),
            )
        return self.classify(entry, now=now, support_channel=support_channel)

    def classify(
        self,
        entry: LifecycleCatalogEntry,
        *,
        now: datetime,
        support_channel: str | None = None,
    ) -> LifecycleClassification:
        channel = (support_channel or entry.default_support_channel).strip().casefold()
        if channel not in {"mainstream", "extended"}:
            raise ValueError("support_channel must be mainstream or extended")
        support_end = (
            entry.extended_support_end
            if channel == "extended"
            else entry.mainstream_support_end
        )
        today = now.astimezone(UTC).date() if now.tzinfo else now.date()
        remaining = (date.fromisoformat(support_end) - today).days
        support_date = date.fromisoformat(support_end)
        if remaining < 0:
            status = LifecycleStatus.EOL
        elif support_date < _add_months(today, self.critical_months):
            status = LifecycleStatus.CRITICAL
        elif support_date < _add_months(today, self.near_months):
            status = LifecycleStatus.NEAR_EOL
        elif support_date < _add_months(today, self.approaching_months):
            status = LifecycleStatus.APPROACHING_EOL
        else:
            status = LifecycleStatus.SUPPORTED
        return LifecycleClassification(
            status,
            support_end,
            remaining,
            channel,
            1.0,
            (
                f"{entry.product} {entry.version} {channel} support ends {support_end}.",
                f"Catalog source: {entry.source_url}",
                f"Catalog last updated: {entry.last_update_date}",
                *([entry.notes] if entry.notes else []),
            ),
        )

    @staticmethod
    def _key(product: str, version: str) -> tuple[str, str]:
        return " ".join(product.casefold().split()), " ".join(
            version.casefold().split()
        )


def _date_string(value: Any, field_name: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Lifecycle catalog {field_name} must be an ISO date") from exc


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
