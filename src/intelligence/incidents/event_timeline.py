from __future__ import annotations

from datetime import UTC, datetime


class EventTimelineEngine:
    """Normalizes governed facts and produces chronological operational chains."""

    _FIREWALL_FIELDS = frozenset({"firewall", "firewallpolicy", "azfirewall", "azurefirewall", "applicationrulecollections", "networkrulecollections", "natrulecollections"})
    _NSG_FIELDS = frozenset({"securityrules", "nsgrules", "nsg", "networksecuritygroup"})

    def __init__(self, *, max_events: int = 50000) -> None:
        if isinstance(max_events, bool) or not isinstance(max_events, int) or max_events < 1:
            raise ValueError("Timeline max_events must be a positive integer")
        self.max_events = max_events

    def normalize(self, *, incidents=None, alerts=None, changes=None, network_changes=None, cve_exposures=None, patch=None, lifecycle=None):
        collections = (incidents or [], alerts or [], changes or [], network_changes or [], cve_exposures or [], patch or [], lifecycle or [])
        if any(not isinstance(rows, list) for rows in collections):
            raise ValueError("Timeline event collections must be lists")
        if sum(len(rows) for rows in collections) > self.max_events:
            raise ValueError("Timeline event collection exceeds configured bound")
        events = []
        specs = (
            (incidents or [], "incident_id", "started_at", self._incident_type),
            (alerts or [], "alert_id", "fired_at", self._alert_type),
            (changes or [], "change_id", "changed_at", self._change_type),
            (network_changes or [], "change_id", "changed_at", self._network_change_type),
            (cve_exposures or [], "finding_id", "observed_at", self._cve_exposure_type),
            (patch or [], "finding_id", "observed_at", self._patch_type),
            (lifecycle or [], "finding_id", "observed_at", self._lifecycle_type),
        )
        for rows, id_field, time_field, classifier in specs:
            for row in rows:
                if not isinstance(row, dict):
                    raise TypeError("Timeline events must be mappings")
                identity = str(row.get(id_field) or row.get("evidence_id") or "Unknown")
                timestamp = self._timestamp(
                    row.get(time_field) or row.get("observed_at")
                )
                events.append(
                    {
                        "event_id": identity,
                        "event_type": classifier(row),
                        "timestamp": timestamp,
                        "summary": str(row.get("summary") or row.get("title") or row.get("status") or "Operational event")[:512],
                        "source": str(row.get("source") or row.get("evidence_type") or "Governed operational evidence")[:256],
                        "evidence": [f"Normalized from {id_field}: {identity}"],
                        "_resource_key": str(row.get("resource_key") or "").casefold(),
                    }
                )
        return sorted(events, key=lambda event: (event["timestamp"], event["event_id"]))

    def chain(self, events, *, incident_at):
        if not isinstance(events, list) or len(events) > self.max_events:
            raise ValueError("Timeline chain exceeds configured bound")
        preceding = [event for event in events if event["timestamp"] <= incident_at]
        labels = {event["event_type"] for event in preceding}
        chains = []
        if "Patch Failure" in labels:
            chains.append("Missed patch -> exposure increase -> application at risk")
        if "CVE Exposure" in labels:
            chains.append("CVE exposure -> elevated operational risk -> incident")
        if labels & {"Resource Modified", "Configuration Change", "Network Change", "Firewall Rule Change", "NSG Change"}:
            chains.append("Configuration or network change -> service degradation -> incident")
        if "OS EOL Threshold Crossed" in labels:
            chains.append("Lifecycle exposure -> recurring risk -> business service impact")
        if any("Reboot" in event["summary"] for event in preceding):
            chains.append("VM reboot -> service degradation -> incident")
        return chains or ["Observed events -> incident; no deterministic causal chain confirmed"]

    @staticmethod
    def _incident_type(_row):
        return "Incident"

    @staticmethod
    def _alert_type(row):
        source = str(row.get("source") or "").casefold()
        signal = str(row.get("signal") or "").casefold()
        explicit_type = str(row.get("event_type") or "").casefold()
        if "advisor" in source:
            return "Advisor Alert"
        if explicit_type == "service degradation" or signal in {
            "availability",
            "degradation",
            "health degradation",
            "service health",
        }:
            return "Service Degradation"
        return "Alert"

    @staticmethod
    def _lifecycle_type(row):
        status = str(row.get("status") or "").casefold()
        return (
            "OS EOL Threshold Crossed"
            if any(token in status for token in ("eol", "end of support", "near eol"))
            else "Lifecycle Status"
        )

    @staticmethod
    def _change_type(row):
        changed_fields = row.get("changed_fields") or []
        if not isinstance(changed_fields, list):
            raise TypeError("Timeline changed_fields must be a list")
        fields = {str(field).casefold() for field in changed_fields}
        if "owner" in fields or "ownership" in fields:
            return "Ownership Change"
        value = str(row.get("change_type") or "").casefold()
        return "Resource Created" if value in {"create", "created"} else "Resource Deleted" if value in {"delete", "deleted"} else "Configuration Change" if fields else "Resource Modified"


    @classmethod
    def _network_change_type(cls, row):
        fields = {
            str(field).casefold().replace("_", "")
            for field in (row.get("changed_fields") or [])
        }
        text = " ".join(
            str(row.get(name) or "").casefold()
            for name in ("summary", "source", "change_type", "category")
        )
        if fields & cls._FIREWALL_FIELDS or "firewall" in text:
            return "Firewall Rule Change"
        if fields & cls._NSG_FIELDS or "nsg" in text or "network security group" in text:
            return "NSG Change"
        return "Network Change"

    @staticmethod
    def _cve_exposure_type(_row):
        return "CVE Exposure"

    @staticmethod
    def _patch_type(row):
        status = str(row.get("status") or "").casefold()
        return "Patch Failure" if status in {"failed", "failure", "noncompliant", "error"} else "Patch Success" if status in {"succeeded", "success", "compliant", "installed"} else "Patch Event"

    @staticmethod
    def _timestamp(value):
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("Operational event timestamp must be ISO-8601") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
