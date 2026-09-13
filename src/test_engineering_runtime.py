import unittest

from engineering_runtime import ExecutionPolicy, ResourceProfile, WorkloadSpec, authorize_workload
from engineering_vv import mesh_convergence, relative_error, require_all, scalar_balance


class TestEngineeringRuntime(unittest.TestCase):
    def test_workload_fingerprint_is_stable(self):
        first = WorkloadSpec("pressure study", "simulation", {"pressure": 10.0})
        second = WorkloadSpec("pressure study", "simulation", {"pressure": 10.0})
        self.assertEqual(first.fingerprint(), second.fingerprint())
        self.assertEqual(len(first.fingerprint()), 64)

    def test_policy_blocks_remote_and_network_by_default(self):
        spec = WorkloadSpec("local run", "calculation")
        with self.assertRaises(PermissionError):
            authorize_workload(spec, remote=True)
        with self.assertRaises(PermissionError):
            authorize_workload(spec, network=True)

    def test_policy_can_allow_remote_network(self):
        spec = WorkloadSpec(
            "remote run",
            "simulation",
            resource_profile=ResourceProfile(network_required=True, execution_tiers=("hpc",)),
            policy=ExecutionPolicy(allow_remote=True, allow_network=True),
        )
        authorize_workload(spec, remote=True, network=True)

    def test_invalid_resource_and_policy_combinations_rejected(self):
        with self.assertRaises(ValueError):
            ResourceProfile(cpu_cores=0)
        with self.assertRaises(ValueError):
            ExecutionPolicy(allow_network=True, allow_remote=False)


class TestEngineeringVerification(unittest.TestCase):
    def test_relative_error(self):
        self.assertAlmostEqual(relative_error(101.0, 100.0), 0.01)

    def test_scalar_balance(self):
        passed = scalar_balance("mass", 100.00001, 100.0, 1e-6)
        failed = scalar_balance("mass", 101.0, 100.0, 1e-6)
        self.assertTrue(passed.passed)
        self.assertFalse(failed.passed)

    def test_mesh_convergence_requires_three_levels(self):
        self.assertTrue(mesh_convergence([10.0, 10.01, 10.0101], 0.01).passed)
        with self.assertRaises(ValueError):
            mesh_convergence([10.0, 10.01])

    def test_require_all(self):
        require_all([scalar_balance("mass", 1.0, 1.0)])
        with self.assertRaises(ValueError):
            require_all([scalar_balance("mass", 2.0, 1.0, 1e-6)])


if __name__ == "__main__":
    unittest.main()
