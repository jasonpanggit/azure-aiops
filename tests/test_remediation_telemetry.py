from remediation_scenario import remediation_planner


class Recorder:
    def __init__(self):
        self.values = []

    def record(self, value, *args):
        self.values.append(value)


class FakeTelemetry:
    def __init__(self):
        self.plan_generation_latency = Recorder()
        self.simulation_duration = Recorder()
        self.dependency_traversal_latency = Recorder()
        self.risk_analysis_duration = Recorder()
        self.approval_generation_time = Recorder()
        self.rollback_generation_time = Recorder()


def test_required_remediation_telemetry_is_recorded():
    telemetry = FakeTelemetry()
    remediation_planner(telemetry=telemetry).generate_plans()

    assert telemetry.plan_generation_latency.values
    assert telemetry.simulation_duration.values
    assert telemetry.dependency_traversal_latency.values
    assert telemetry.risk_analysis_duration.values
    assert telemetry.approval_generation_time.values
    assert telemetry.rollback_generation_time.values
