"""Fabric-hosted topology derivation pipeline (D-04a comparison arm).

This package builds a genuine Fabric-hosted Spark/notebook pipeline that
reproduces ``hermes_arg_connector.normalize``'s deterministic
entity/edge-derivation predicate vocabulary directly against inventory-owned
identity data, plus new NSG-rule + flow-log-derived directional network
topology (D-11). It is the technical comparison arm the Phase 8 viability
gate (08-03) measures Hermes against — not a Hermes replacement by itself.
"""

from __future__ import annotations
