"""
Test Suite for Geographic & Land-Cover Domain Validation Integration
====================================================================
Tests the four canonical verification cases:
1. Dhanbad (Land, Jharkhand): 23.7957, 86.4304
2. Bay of Bengal (Offshore Marine): 18.0, 88.0
3. Inland Water (Hirakud Dam): 21.6468, 83.7596
4. Invalid Coordinates: lat=abc, lon=999
"""

import sys
import os
import unittest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from geo_validation import validate_geographic_domain
from fastapi.testclient import TestClient
from main import app


class TestGeographicValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_01_dhanbad_land(self):
        """Case 1: Dhanbad (23.7957, 86.4304) -> LAND in Jharkhand"""
        res = validate_geographic_domain(23.7957, 86.4304)
        self.assertEqual(res["domain"], "LAND")
        self.assertEqual(res["status"], "validated")
        self.assertEqual(res["state"], "Jharkhand")
        self.assertEqual(res["district"], "Dhanbad")
        self.assertEqual(res["city"], "Dhanbad")
        self.assertIsNone(res["confidence"])

        # Test endpoint
        resp = self.client.get("/geo-validate?lat=23.7957&lon=86.4304")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["domain"], "LAND")
        self.assertEqual(data["state"], "Jharkhand")

    def test_02_bay_of_bengal_marine(self):
        """Case 2: Bay of Bengal (18.0, 88.0) -> OFFSHORE_MARINE with Not applicable"""
        res = validate_geographic_domain(18.0, 88.0)
        self.assertEqual(res["domain"], "OFFSHORE_MARINE")
        self.assertEqual(res["status"], "validated")
        self.assertEqual(res["state"], "Not applicable")
        self.assertEqual(res["district"], "Not applicable")
        self.assertEqual(res["city"], "Not applicable")
        self.assertIsNone(res["confidence"])

        # Test endpoint
        resp = self.client.get("/geo-validate?lat=18.0&lon=88.0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["domain"], "OFFSHORE_MARINE")
        self.assertEqual(data["state"], "Not applicable")

    def test_03_inland_water(self):
        """Case 3: Inland water / Hirakud Dam (21.6468, 83.7596) -> INLAND_WATER"""
        res = validate_geographic_domain(21.6468, 83.7596)
        self.assertEqual(res["domain"], "INLAND_WATER")
        self.assertEqual(res["status"], "validated")
        self.assertEqual(res["state"], "Odisha")
        self.assertIn("Dam", res["city"])
        self.assertIsNone(res["confidence"])

        # Test endpoint
        resp = self.client.get("/geo-validate?lat=21.6468&lon=83.7596")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["domain"], "INLAND_WATER")
        self.assertEqual(data["state"], "Odisha")

    def test_04_invalid_coordinates(self):
        """Case 4: Invalid coordinates (lat=abc, lon=999) -> UNKNOWN_UNRESOLVED"""
        res = validate_geographic_domain("abc", "999")
        self.assertEqual(res["domain"], "UNKNOWN_UNRESOLVED")
        self.assertEqual(res["status"], "unresolved")
        self.assertIsNone(res["state"])
        self.assertIsNone(res["district"])
        self.assertIsNone(res["city"])

        # Test endpoint
        resp = self.client.get("/geo-validate?lat=abc&lon=999")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["domain"], "UNKNOWN_UNRESOLVED")
        self.assertEqual(data["status"], "unresolved")


if __name__ == "__main__":
    unittest.main()
