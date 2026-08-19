"""Public ontology synchronization validation contract."""

from .ontology_validator import OntologyValidationReport, OntologyValidator

SyncValidator = OntologyValidator

__all__ = ["OntologyValidationReport", "OntologyValidator", "SyncValidator"]
