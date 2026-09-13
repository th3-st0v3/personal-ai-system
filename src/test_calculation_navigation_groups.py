import unittest

from calculation_navigation import major, majors


EXPECTED = {
    "Mechanical Engineering": {"Aerospace Engineering", "Automotive Engineering", "Electromechanical Engineering", "Manufacturing Engineering", "Mechatronics Engineering", "Robotics Engineering", "Mechanical Engineering"},
    "Electrical & Computer Engineering": {"Computer Engineering", "Electrical Engineering", "Photonics Engineering", "Optical Engineering", "Software Engineering", "Telecommunications Engineering"},
    "Chemical & Biological Engineering": {"Biochemical Engineering", "Bioengineering", "Biological Systems Engineering", "Biomedical Engineering", "Ceramics Engineering", "Chemical Engineering", "Materials Science and Engineering", "Metallurgical Engineering", "Plastics Engineering"},
    "Civil & Environmental Engineering": {"Architectural Engineering", "Civil Engineering", "Construction Engineering", "Environmental Engineering", "Fire Protection Engineering", "Geomatics Engineering", "Geotechnical Engineering", "Structural Engineering", "Transportation Engineering"},
    "Energy & Earth Resources Engineering": {"Mining Engineering", "Nuclear Engineering", "Ocean Engineering", "Petroleum Engineering", "Marine Engineering", "Wind Energy Engineering"},
    "Applied Sciences & Management": {"Engineering Management", "Engineering Physics", "Industrial Engineering", "Nanotechnology Engineering", "Systems Engineering", "Agricultural Engineering"},
}


class CalculationNavigationGroupTests(unittest.TestCase):
    def test_all_requested_majors_are_present_once(self):
        groups = majors()
        self.assertEqual(tuple(item["name"] for item in groups), tuple(EXPECTED))
        assigned = [major_name for item in groups for major_name in item["includes"]]
        self.assertEqual(len(assigned), len(set(assigned)))
        self.assertEqual(set(assigned), set().union(*EXPECTED.values()))

    def test_reservoir_is_no_longer_a_public_major(self):
        with self.assertRaises(ValueError):
            major("Reservoir Engineering")
        energy = major("Energy & Earth Resources Engineering")
        self.assertGreater(len(energy["calculations"]), 0)


if __name__ == "__main__":
    unittest.main()
