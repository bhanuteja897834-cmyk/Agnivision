"""
backend/test_classification_engine.py

Comprehensive unit test suite for Step 8: Thermal Event Classification Engine.
Validates all 16 required test scenarios across deterministic rule evaluation,
explanation generation, rule traceability, and separation from human verification.
"""

import unittest
try:
    from backend.classification_engine import (
        classify_thermal_event,
        CLASSIFICATION_THRESHOLDS,
        RULES_METADATA,
    )
except ModuleNotFoundError:
    from classification_engine import (
        classify_thermal_event,
        CLASSIFICATION_THRESHOLDS,
        RULES_METADATA,
    )


class TestThermalEventClassificationEngine(unittest.TestCase):

    def setUp(self):
        # Base realistic event mock (replicates real EVT-000029 data)
        self.base_event = {
            "event_id": "EVT-000029",
            "observation_count": 133,
            "persistence_days": 5,
            "first_detected": "2026-09-16T20:57:00Z",
            "last_detected": "2026-09-21T19:25:00Z",
            "geographic_domain": "LAND",
            "state": "Jharkhand",
            "district": "Dhanbad",
            "geographic_validation": {
                "domain": "LAND",
                "state": "Jharkhand",
                "district": "Dhanbad",
            },
            "centroid": {"latitude": 23.76127, "longitude": 86.39550},
            "temporal_summary": {
                "duration_hours": 120.0,
                "distinct_days": 5,
                "persistence_days": 5,
                "observation_count": 133,
            },
            "brightness_summary": {
                "min": 296.43,
                "max": 340.62,
                "avg": 313.54,
            },
            "frp_summary": {
                "min": 0.85,
                "max": 6.88,
                "avg": 2.11,
            },
            "spatial_summary": {
                "centroid": {"latitude": 23.76127, "longitude": 86.39550},
                "min_latitude": 23.7091,
                "max_latitude": 23.80749,
                "min_longitude": 86.3129,
                "max_longitude": 86.45193,
            }
        }

    # 1. Strong industrial event (EVT-000029)
    def test_01_strong_industrial_event(self):
        asset_data = {
            "counts": {"industrial": 2, "power": 2, "substation": 0},
            "assets": [{"name": "Steel Plant"}, {"name": "Thermal Power Station"}]
        }
        res = classify_thermal_event(self.base_event, asset_data=asset_data)
        self.assertEqual(res["classification"], "INDUSTRIAL_HEAT")
        self.assertEqual(res["method"], "RULE_BASED")
        rule_ids = [r["rule_id"] for r in res["rules_triggered"]]
        self.assertIn("RULE_IND_001_FACILITY_PROXIMITY", rule_ids)
        self.assertIn("RULE_IND_002_STATIONARY_PERSISTENCE", rule_ids)
        self.assertIn("RULE_IND_003_THERMAL_CONSISTENCY", rule_ids)
        self.assertIn("Steel Plant", " ".join(res["supporting_evidence"]) + res["primary_explanation"] or "")

    # 2. Single observation event (e.g. EVT-000002)
    def test_02_single_observation_event(self):
        single_event = dict(self.base_event)
        single_event["event_id"] = "EVT-000002"
        single_event["observation_count"] = 1
        single_event["temporal_summary"] = {"duration_hours": 0.0, "distinct_days": 1}
        res = classify_thermal_event(single_event)
        self.assertEqual(res["classification"], "UNKNOWN")
        rule_ids = [r["rule_id"] for r in res["rules_triggered"]]
        self.assertIn("RULE_UNK_001_SINGLE_OBSERVATION_SAMPLE", rule_ids)
        self.assertTrue(any("single observation" in r["reason"].lower() or "single" in res["primary_explanation"].lower() for r in res["alternative_explanations"]))

    # 3. Event with no facility context (isolated multi-pass land fire)
    def test_03_event_with_no_facility_context(self):
        fire_event = dict(self.base_event)
        fire_event["event_id"] = "EVT-000055"
        fire_event["observation_count"] = 8
        fire_event["temporal_summary"] = {"duration_hours": 18.0, "distinct_days": 2}
        asset_data = {"counts": {"industrial": 0, "power": 0}, "assets": []}
        res = classify_thermal_event(fire_event, asset_data=asset_data)
        self.assertEqual(res["classification"], "ACTIVE_FIRE")
        rule_ids = [r["rule_id"] for r in res["rules_triggered"]]
        self.assertIn("RULE_FIRE_001_SIGNIFICANT_RADIATIVE_POWER", rule_ids)
        self.assertIn("RULE_FIRE_002_MULTI_PASS_DETECTION", rule_ids)

    # 4. Offshore marine event
    def test_04_offshore_marine_event(self):
        marine_event = dict(self.base_event)
        marine_event["geographic_domain"] = "OFFSHORE_MARINE"
        marine_event["geographic_validation"] = {"domain": "OFFSHORE_MARINE", "state": "Offshore"}
        # Without offshore facility -> UNKNOWN with contradiction/unverified
        res = classify_thermal_event(marine_event, asset_data={"counts": {"industrial": 0, "power": 0}})
        self.assertEqual(res["classification"], "UNKNOWN")
        rule_ids = [r["rule_id"] for r in res["rules_triggered"]]
        self.assertIn("RULE_GEO_002_NON_TERRESTRIAL_CONSTRAINT", rule_ids)

        # With offshore oil/gas platform -> INDUSTRIAL_HEAT
        res_platform = classify_thermal_event(marine_event, asset_data={"counts": {"industrial": 1, "power": 0}})
        self.assertEqual(res_platform["classification"], "INDUSTRIAL_HEAT")

    # 5. Inland water event
    def test_05_inland_water_event(self):
        water_event = dict(self.base_event)
        water_event["geographic_domain"] = "INLAND_WATER"
        water_event["geographic_validation"] = {"domain": "INLAND_WATER", "state": "Inland Water"}
        res = classify_thermal_event(water_event)
        self.assertEqual(res["classification"], "UNKNOWN")
        rule_ids = [r["rule_id"] for r in res["rules_triggered"]]
        self.assertIn("RULE_GEO_002_NON_TERRESTRIAL_CONSTRAINT", rule_ids)

    # 6. Missing historical baseline
    def test_06_missing_historical_baseline(self):
        # Baseline is optional, engine must not crash or fail if anomaly_result is None
        res = classify_thermal_event(self.base_event, anomaly_result=None)
        self.assertIn(res["classification"], ["INDUSTRIAL_HEAT", "ACTIVE_FIRE", "UNKNOWN"])
        self.assertIsInstance(res["rules_triggered"], list)

    # 7. Missing FRP
    def test_07_missing_frp(self):
        no_frp_event = dict(self.base_event)
        no_frp_event["frp_summary"] = {"avg": None, "max": None}
        no_frp_event["brightness_summary"] = {"avg": 335.0, "max": 340.0}
        res = classify_thermal_event(no_frp_event, asset_data={"counts": {"industrial": 0, "power": 0}})
        self.assertEqual(res["classification"], "ACTIVE_FIRE")
        rule_ids = [r["rule_id"] for r in res["rules_triggered"]]
        self.assertIn("RULE_FIRE_001_SIGNIFICANT_RADIATIVE_POWER", rule_ids)

    # 8. Strong thermal + weak context
    def test_08_strong_thermal_weak_context(self):
        intense_event = dict(self.base_event)
        intense_event["observation_count"] = 5
        intense_event["brightness_summary"] = {"avg": 365.0, "max": 378.0}
        intense_event["frp_summary"] = {"avg": 55.0, "max": 120.0}
        intense_event["temporal_summary"] = {"duration_hours": 8.0, "distinct_days": 1}
        # No industrial facility
        res = classify_thermal_event(intense_event, asset_data={"counts": {"industrial": 0, "power": 0}})
        self.assertEqual(res["classification"], "ACTIVE_FIRE")
        self.assertGreaterEqual(len(res["alternative_explanations"]), 1)

    # 9. Agricultural without land-use data
    def test_09_agricultural_without_land_use_data(self):
        agri_candidate = dict(self.base_event)
        agri_candidate["observation_count"] = 3
        agri_candidate["temporal_summary"] = {"duration_hours": 6.0, "distinct_days": 1}
        res = classify_thermal_event(agri_candidate, asset_data={"counts": {"industrial": 0, "power": 0}})
        rule_ids = [r["rule_id"] for r in res["rules_triggered"]]
        self.assertIn("RULE_AGRI_001_LAND_USE_DATA_UNAVAILABLE", rule_ids)
        # Primary cannot be AGRICULTURAL_BURNING because land cover data is unavailable
        self.assertNotEqual(res["classification"], "AGRICULTURAL_BURNING")
        alt_candidates = [a["candidate"] for a in res["alternative_explanations"]]
        self.assertIn("AGRICULTURAL_BURNING", alt_candidates)

    # 10. Wildland without vegetation data
    def test_10_wildland_without_vegetation_data(self):
        wild_candidate = dict(self.base_event)
        wild_candidate["observation_count"] = 4
        wild_candidate["temporal_summary"] = {"duration_hours": 12.0, "distinct_days": 1}
        res = classify_thermal_event(wild_candidate, asset_data={"counts": {"industrial": 0, "power": 0}})
        rule_ids = [r["rule_id"] for r in res["rules_triggered"]]
        self.assertIn("RULE_WILD_001_VEGETATION_CANOPY_UNAVAILABLE", rule_ids)
        # Primary cannot be WILDLAND_FIRE because canopy data is unavailable
        self.assertNotEqual(res["classification"], "WILDLAND_FIRE")
        alt_candidates = [a["candidate"] for a in res["alternative_explanations"]]
        self.assertIn("WILDLAND_FIRE", alt_candidates)

    # 11. Conflicting evidence (e.g. low thermal, low persistence, no facility)
    def test_11_conflicting_or_weak_evidence(self):
        weak_event = dict(self.base_event)
        weak_event["observation_count"] = 2
        weak_event["brightness_summary"] = {"avg": 305.0, "max": 308.0}
        weak_event["frp_summary"] = {"avg": 0.3, "max": 0.5}
        weak_event["temporal_summary"] = {"duration_hours": 1.0, "distinct_days": 1}
        res = classify_thermal_event(weak_event, asset_data={"counts": {"industrial": 0, "power": 0}})
        self.assertEqual(res["classification"], "UNKNOWN")
        rule_ids = [r["rule_id"] for r in res["rules_triggered"]]
        self.assertIn("RULE_UNK_003_INCONCLUSIVE_EVIDENCE", rule_ids)

    # 12. UNKNOWN fallback
    def test_12_unknown_fallback(self):
        inconclusive = dict(self.base_event)
        inconclusive["observation_count"] = 2
        inconclusive["brightness_summary"] = {"avg": 310.0, "max": 312.0}
        inconclusive["frp_summary"] = {"avg": 0.4, "max": 0.6}
        res = classify_thermal_event(inconclusive, asset_data={"counts": {"industrial": 0, "power": 0}})
        self.assertEqual(res["classification"], "UNKNOWN")
        self.assertTrue(len(res["primary_explanation"]) > 20)

    # 13. API endpoint response structure
    def test_13_response_structure(self):
        res = classify_thermal_event(self.base_event)
        required_keys = [
            "status", "event_id", "classification", "method", "evaluated_at_utc",
            "primary_explanation", "supporting_evidence", "alternative_explanations",
            "limitations", "rules_triggered", "rules_triggered_count"
        ]
        for key in required_keys:
            self.assertIn(key, res, f"Missing key '{key}' in classification output")
        self.assertEqual(res["method"], "RULE_BASED")

    # 14. Primary explanation generation
    def test_14_explanation_generation(self):
        res = classify_thermal_event(self.base_event, asset_data={"counts": {"industrial": 1, "power": 1}})
        self.assertIsInstance(res["primary_explanation"], str)
        self.assertGreater(len(res["primary_explanation"]), 30)
        self.assertIsInstance(res["supporting_evidence"], list)
        self.assertGreater(len(res["supporting_evidence"]), 0)

    # 15. Rule traceability
    def test_15_rule_traceability(self):
        res = classify_thermal_event(self.base_event, asset_data={"counts": {"industrial": 2, "power": 2}})
        for rule in res["rules_triggered"]:
            self.assertIn("rule_id", rule)
            self.assertIn("rule_name", rule)
            self.assertIn("description", rule)
            self.assertTrue(rule["matched"])
            self.assertIn(rule["rule_id"], RULES_METADATA)

    # 16. Human verification separation
    def test_16_human_verification_separation(self):
        # Verification state should NEVER be returned as part of or modified by analytical classification
        res = classify_thermal_event(self.base_event)
        self.assertNotIn("verified_by", res)
        self.assertNotIn("is_human_verified", res)
        self.assertNotIn("verified_status", res)
        self.assertEqual(res["method"], "RULE_BASED")


if __name__ == "__main__":
    unittest.main()
