from __future__ import annotations

from typing import Any, ClassVar


class ChangeClassifier:
    """Deterministically classifies governed change evidence."""

    CATEGORIES: ClassVar[set[str]] = {
        "Security",
        "Network",
        "Identity",
        "Compute",
        "Storage",
        "Governance",
        "Platform",
        "Application",
    }

    def classify(self, change: dict[str, Any]) -> str:
        explicit = str(change.get("category") or "").strip().title()
        if explicit in self.CATEGORIES:
            return explicit
        fields = {
            str(field).casefold().replace("_", "")
            for field in change.get("changed_fields") or []
        }
        text = " ".join(
            str(change.get(name) or "").casefold()
            for name in ("source", "summary", "change_type")
        )
        if fields & {
            "securityrules",
            "nsgRules".casefold(),
            "routes",
            "firewall",
            "dns",
            "privateendpoint",
            "loadbalancer",
            "applicationgateway",
            "publicnetworkaccess",
        } or any(token in text for token in ("network", "firewall", "nsg", "route", "dns")):
            return "Network"
        if fields & {"roleassignments", "managedidentity", "serviceprincipal", "privilegedaccess"} or any(token in text for token in ("identity", "role assignment", "service principal")):
            return "Identity"
        if fields & {"encryption", "tls", "secrets", "certificates"} or "security" in text:
            return "Security"
        if fields & {"sku", "size", "image", "osdisk", "extensions"}:
            return "Compute"
        if fields & {"replication", "networkacls", "blobpublicaccess", "storagekind"} or "storage" in text:
            return "Storage"
        if fields & {"policy", "policyexemption", "tags", "owner"} or "policy" in text:
            return "Governance"
        if any(token in text for token in ("terraform", "bicep", "arm template", "pipeline", "github actions", "azure devops")):
            return "Platform"
        return "Application"
