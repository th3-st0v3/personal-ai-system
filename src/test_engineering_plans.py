import unittest

from engineering_plans import build_test_plan, build_weekly_report, verification_method


class TestEngineeringPlans(unittest.TestCase):
    def test_verification_method_is_deterministic(self):
        self.assertEqual(verification_method("Measure pressure at the outlet"), "measurement")
        self.assertEqual(verification_method("Calculate bending stress"), "analysis/calculation")
        self.assertEqual(verification_method("Simulate thermal behavior"), "simulation")

    def test_test_plan_maps_requirement_to_evidence_type(self):
        plan = build_test_plan([{"id": 1, "title": "Pressure limit", "description": "Measure pressure", "acceptance_criteria": "< 5 MPa"}])
        self.assertEqual(plan[0]["verification_method"], "measurement")
        self.assertEqual(plan[0]["evidence_types"], ["test_result"])

    def test_weekly_report_flags_missing_evidence(self):
        report = build_weekly_report(
            [{"id": 1, "status": "Verified", "description": "A"}, {"id": 2, "status": "Unverified", "description": "B"}],
            [{"id": 4}], [{"id": 5}], {1: [{"lifecycle_status": "Active"}], 2: []},
        )
        self.assertEqual(report["requirements"]["total"], 2)
        self.assertEqual(report["requirements"]["by_status"]["Verified"], 1)
        self.assertEqual(report["unclear_statuses"][0]["requirement_id"], 2)


if __name__ == "__main__":
    unittest.main()
