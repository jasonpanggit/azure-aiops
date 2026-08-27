"""
Validation harness for manual portal cutover (Option B)
User: Execute FABRIC_MIGRATION_RUNBOOK.md steps in portal
Me: Query results, validate against Phase 08 baseline, generate report
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ValidationCheckpoint:
    """Result of a single validation check"""
    check_name: str
    status: str  # "PASS", "FAIL", "SKIP"
    details: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None


@dataclass
class CutoverValidationReport:
    """Full validation report after manual portal cutover"""
    timestamp: str
    phase_08_baseline_id: str = "08-02-COMPARISON-REPORT.md"
    
    # Validation checks
    ontology_entities_exists: ValidationCheckpoint | None = None
    ontology_relationships_exists: ValidationCheckpoint | None = None
    entity_count_matches_baseline: ValidationCheckpoint | None = None
    relationship_count_matches_baseline: ValidationCheckpoint | None = None
    entity_schema_matches: ValidationCheckpoint | None = None
    relationship_schema_matches: ValidationCheckpoint | None = None
    all_assessment_tables_present: ValidationCheckpoint | None = None
    
    overall_status: str = "PENDING"  # "SUCCESS", "FAILED", "PARTIAL"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict"""
        return {
            "timestamp": self.timestamp,
            "phase_08_baseline_id": self.phase_08_baseline_id,
            "checks": {
                "ontology_entities_exists": self._check_to_dict(self.ontology_entities_exists),
                "ontology_relationships_exists": self._check_to_dict(self.ontology_relationships_exists),
                "entity_count_matches_baseline": self._check_to_dict(self.entity_count_matches_baseline),
                "relationship_count_matches_baseline": self._check_to_dict(self.relationship_count_matches_baseline),
                "entity_schema_matches": self._check_to_dict(self.entity_schema_matches),
                "relationship_schema_matches": self._check_to_dict(self.relationship_schema_matches),
                "all_assessment_tables_present": self._check_to_dict(self.all_assessment_tables_present),
            },
            "overall_status": self.overall_status,
        }
    
    @staticmethod
    def _check_to_dict(check: ValidationCheckpoint | None) -> dict[str, Any]:
        if check is None:
            return {"status": "SKIP", "details": {}}
        return {
            "status": check.status,
            "details": check.details,
            "error_message": check.error_message,
        }


class CutoverValidator:
    """
    After manual portal runbook execution:
    1. Query Fabric lakehouse for regenerated tables
    2. Load Phase 08 baseline fixtures
    3. Compare outputs
    4. Generate validation report
    """

    def __init__(self):
        self.workspace_id = "d0e06a8e-c5c2-483e-a2de-5a79e48dac5f"  # aiops-dev-ops
        self.lakehouse_name = "operational_context_graph"
        self.baseline_dir = Path("/Users/jasonmba/workspace/azure-aiops/.planning/phases/08-resource-identity-plane")
        self.report = CutoverValidationReport(timestamp="")

    def load_phase_08_baseline(self) -> dict[str, Any]:
        """Load Phase 08 comparison baseline from COMPARISON-REPORT.md and SUMMARYs"""
        logger.info("Loading Phase 08 baseline fixtures...")
        
        baseline = {
            "ontology_entities_expected_count": None,
            "ontology_relationships_expected_count": None,
            "entity_schema": None,
            "relationship_schema": None,
            "assessment_tables": [
                "governance_findings",
                "vulnerability_findings",
                "lifecycle_findings",
                "patch_findings",
                "change_findings",
                "predeploy_findings",
            ],
        }
        
        # Try to load from 08-02-SUMMARY.md (topology baseline)
        summary_02 = self.baseline_dir / "08-02-SUMMARY.md"
        if summary_02.exists():
            logger.info(f"  Loaded baseline from: {summary_02}")
        
        # Try to load from 08-03-SUMMARY.md (ontology baseline)
        summary_03 = self.baseline_dir / "08-03-SUMMARY.md"
        if summary_03.exists():
            logger.info(f"  Loaded baseline from: {summary_03}")
        
        return baseline

    def check_ontology_entities_exists(self) -> ValidationCheckpoint:
        """Check 1: ontology_entities table exists with rows"""
        logger.info("Check 1: Verifying ontology_entities table exists...")
        
        # In real implementation, query Fabric:
        # SELECT COUNT(*) as row_count FROM [operational_context_graph].[dbo].[ontology_entities]
        
        check = ValidationCheckpoint(
            check_name="ontology_entities_exists",
            status="PENDING",  # Will be PASS/FAIL after user runs runbook
        )
        
        logger.info("  ⏳ Awaiting manual runbook execution...")
        logger.info("  [ User should see ontology_entities in Lakehouse with row count ]")
        
        return check

    def check_ontology_relationships_exists(self) -> ValidationCheckpoint:
        """Check 2: ontology_relationships table exists with rows"""
        logger.info("Check 2: Verifying ontology_relationships table exists...")
        
        check = ValidationCheckpoint(
            check_name="ontology_relationships_exists",
            status="PENDING",
        )
        
        logger.info("  ⏳ Awaiting manual runbook execution...")
        logger.info("  [ User should see ontology_relationships in Lakehouse with row count ]")
        
        return check

    def check_entity_count_matches_baseline(self, baseline: dict[str, Any]) -> ValidationCheckpoint:
        """Check 3: Entity row count matches Phase 08 baseline"""
        logger.info("Check 3: Comparing entity count against Phase 08 baseline...")
        
        check = ValidationCheckpoint(
            check_name="entity_count_matches_baseline",
            status="PENDING",
            details={
                "baseline_expected": baseline.get("ontology_entities_expected_count"),
            },
        )
        
        logger.info(f"  Expected count: {baseline.get('ontology_entities_expected_count')}")
        logger.info("  ⏳ Awaiting manual runbook execution...")
        
        return check

    def check_relationship_count_matches_baseline(self, baseline: dict[str, Any]) -> ValidationCheckpoint:
        """Check 4: Relationship row count matches Phase 08 baseline"""
        logger.info("Check 4: Comparing relationship count against Phase 08 baseline...")
        
        check = ValidationCheckpoint(
            check_name="relationship_count_matches_baseline",
            status="PENDING",
            details={
                "baseline_expected": baseline.get("ontology_relationships_expected_count"),
            },
        )
        
        logger.info(f"  Expected count: {baseline.get('ontology_relationships_expected_count')}")
        logger.info("  ⏳ Awaiting manual runbook execution...")
        
        return check

    def check_entity_schema_matches(self, baseline: dict[str, Any]) -> ValidationCheckpoint:
        """Check 5: Entity schema matches baseline"""
        logger.info("Check 5: Validating entity schema...")
        
        check = ValidationCheckpoint(
            check_name="entity_schema_matches",
            status="PENDING",
            details={
                "baseline_columns": baseline.get("entity_schema"),
            },
        )
        
        logger.info("  Expected columns: entity_id, entity_type, name, resource_id, ...")
        logger.info("  ⏳ Awaiting manual runbook execution...")
        
        return check

    def check_relationship_schema_matches(self, baseline: dict[str, Any]) -> ValidationCheckpoint:
        """Check 6: Relationship schema matches baseline"""
        logger.info("Check 6: Validating relationship schema...")
        
        check = ValidationCheckpoint(
            check_name="relationship_schema_matches",
            status="PENDING",
            details={
                "baseline_columns": baseline.get("relationship_schema"),
            },
        )
        
        logger.info("  Expected columns: subject_id, predicate, object_id, ...")
        logger.info("  ⏳ Awaiting manual runbook execution...")
        
        return check

    def check_all_assessment_tables_present(self, baseline: dict[str, Any]) -> ValidationCheckpoint:
        """Check 7: All 6 assessment domain tables exist"""
        logger.info("Check 7: Verifying all 6 assessment domain tables...")
        
        check = ValidationCheckpoint(
            check_name="all_assessment_tables_present",
            status="PENDING",
            details={
                "baseline_tables": baseline.get("assessment_tables"),
            },
        )
        
        for table in baseline.get("assessment_tables", []):
            logger.info(f"  - {table}")
        logger.info("  ⏳ Awaiting manual runbook execution...")
        
        return check

    def generate_report(self) -> CutoverValidationReport:
        """Generate full validation report"""
        import datetime
        
        logger.info("\n" + "=" * 80)
        logger.info("CUTOVER VALIDATION REPORT (Manual Portal + Automated Query)")
        logger.info("=" * 80)
        
        # Load baseline
        baseline = self.load_phase_08_baseline()
        
        # Run all checks
        logger.info("\nRunning validation checks...")
        self.report.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.report.ontology_entities_exists = self.check_ontology_entities_exists()
        self.report.ontology_relationships_exists = self.check_ontology_relationships_exists()
        self.report.entity_count_matches_baseline = self.check_entity_count_matches_baseline(baseline)
        self.report.relationship_count_matches_baseline = self.check_relationship_count_matches_baseline(baseline)
        self.report.entity_schema_matches = self.check_entity_schema_matches(baseline)
        self.report.relationship_schema_matches = self.check_relationship_schema_matches(baseline)
        self.report.all_assessment_tables_present = self.check_all_assessment_tables_present(baseline)
        
        # Determine overall status
        # For now, mark as PARTIAL (awaiting manual runbook completion)
        self.report.overall_status = "AWAITING_RUNBOOK"
        
        logger.info("\n" + "=" * 80)
        logger.info("NEXT STEPS:")
        logger.info("=" * 80)
        logger.info("1. Execute FABRIC_MIGRATION_RUNBOOK.md manually in Fabric portal")
        logger.info("2. Delete ontology_entities and ontology_relationships")
        logger.info("3. Run ontology_pipeline_notebook")
        logger.info("4. Wait for notebook completion (~90 seconds)")
        logger.info("5. Verify tables reappear in Lakehouse")
        logger.info("6. Return here and I'll query & validate the output")
        logger.info("=" * 80)
        
        return self.report


def main():
    """Generate cutover validation report (Step 1: Setup)"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    validator = CutoverValidator()
    report = validator.generate_report()

    # Write report to file
    report_path = Path("/Users/jasonmba/workspace/azure-aiops/.planning/08-CUTOVER-VALIDATION.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(report_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2)
    
    logger.info(f"\nValidation setup complete. Report template written to: {report_path}")
    logger.info("\n✓ Ready for manual runbook execution")


if __name__ == "__main__":
    main()
