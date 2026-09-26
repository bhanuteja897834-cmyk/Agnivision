"""
backend/test_verification.py

Comprehensive unit test suite for Step 9: Human Verification & Analyst Workflow Hardening.
Tests all 16 scenarios, verifying strict data integrity, isolation of human verification
from automated system analyses, and non-pollution of production records.
"""

import unittest
try:
    import backend.main as main_module
except ModuleNotFoundError:
    import main as main_module
from fastapi.testclient import TestClient


class TestHumanVerificationWorkflow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main_module.app)
        # Pre-warm events
        cls.client.get("/fires")
        cls.client.get("/events")

    def setUp(self):
        # Isolate VERIFIED_EVENTS in memory for each test
        self.original_verified_events = list(main_module.VERIFIED_EVENTS)
        self.original_save_verified_events = main_module.save_verified_events
        self.save_called_count = 0

        def fake_save(*args, **kwargs):
            self.save_called_count += 1

        main_module.save_verified_events = fake_save

        # Create an isolated test list
        main_module.VERIFIED_EVENTS = [
            # Keep a sample unverified event (EVT-000003 is not in verified list)
            # Add EVT-000002 as already verified
            {
                "event_id": "EVT-000002",
                "label": "INDUSTRIAL_HEAT",
                "verified": True,
                "verified_at": "2026-09-25T11:15:54Z",
                "updated_at": None,
                "notes": "Initial test note",
                "system_classification_at_review": "UNKNOWN",
                "source_context": "AGNIVISION Event Evaluation Station",
                "event": {"latitude": 22.37662, "longitude": 87.28043, "source": "NASA FIRMS"},
                "features": {"event_id": "EVT-000002", "observation_count": 1}
            }
        ]

    def tearDown(self):
        # Restore original list and save function, ensuring no pollution of production file
        main_module.VERIFIED_EVENTS = self.original_verified_events
        main_module.save_verified_events = self.original_save_verified_events

    # 1. Unverified event state
    def test_01_unverified_event_state(self):
        # EVT-000003 is unverified
        res = self.client.get("/events/EVT-000003/verification")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["event_id"], "EVT-000003")
        self.assertEqual(data["status"], "UNVERIFIED")
        self.assertFalse(data["verified"])
        self.assertIsNone(data["label"])
        self.assertIsNone(data["record"])

    # 2. Valid human verification
    def test_02_valid_human_verification(self):
        payload = {
            "event_id": "EVT-000003",
            "label": "ACTIVE_FIRE",
            "notes": "Analyst verified visible plume signature.",
            "system_classification_at_review": "ACTIVE_FIRE"
        }
        res = self.client.post("/verify-event", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], "VERIFIED")
        self.assertEqual(data["label"], "ACTIVE_FIRE")
        self.assertFalse(data["replaced_existing"])
        self.assertIn("verified_at", data["record"])
        self.assertGreaterEqual(self.save_called_count, 1)

    # 3. Invalid event ID
    def test_03_invalid_event_id(self):
        payload = {
            "event_id": "EVT-999999",
            "label": "ACTIVE_FIRE"
        }
        res = self.client.post("/verify-event", json=payload)
        self.assertEqual(res.status_code, 404)
        self.assertIn("not found", res.json()["detail"].lower())

    # 4. Invalid label
    def test_04_invalid_label(self):
        payload = {
            "event_id": "EVT-000003",
            "label": "RANDOM_FIRE_LABEL"
        }
        res = self.client.post("/verify-event", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("allowed_labels", str(res.json()))

    # 5. Missing label
    def test_05_missing_label(self):
        payload = {
            "event_id": "EVT-000003",
            "notes": "Forgot to supply label"
        }
        res = self.client.post("/verify-event", json=payload)
        self.assertEqual(res.status_code, 400)

    # 6. Verification notes
    def test_06_verification_notes(self):
        notes_text = "Corroborated with Sentinel-2 optical imagery."
        payload = {
            "event_id": "EVT-000003",
            "label": "WILDLAND_FIRE",
            "notes": notes_text
        }
        res = self.client.post("/verify-event", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["record"]["notes"], notes_text)
        self.assertEqual(data["record"]["features"]["analyst_notes"], notes_text)

    # 7. Duplicate / update verification
    def test_07_duplicate_verification(self):
        # EVT-000002 is already verified as INDUSTRIAL_HEAT in setUp
        payload = {
            "event_id": "EVT-000002",
            "label": "UNKNOWN",
            "notes": "Updated decision upon closer inspection."
        }
        res = self.client.post("/verify-event", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["replaced_existing"])
        self.assertEqual(data["label"], "UNKNOWN")
        self.assertIsNotNone(data["record"]["updated_at"])
        # Original verified_at should be preserved
        self.assertEqual(data["record"]["verified_at"], "2026-09-25T11:15:54Z")

    # 8. Existing verification retrieval
    def test_08_existing_verification_retrieval(self):
        res = self.client.get("/events/EVT-000002/verification")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "VERIFIED")
        self.assertTrue(data["verified"])
        self.assertEqual(data["label"], "INDUSTRIAL_HEAT")

    # 9. System classification remains unchanged after human verification
    def test_09_system_classification_remains_unchanged(self):
        # Check system classification before
        cls_before = self.client.get("/events/EVT-000003/classification").json()
        sys_class_before = cls_before["classification"]

        # Human verifies with a conflicting or different label
        payload = {
            "event_id": "EVT-000003",
            "label": "AGRICULTURAL_BURNING",
            "notes": "Human analyst verification decision."
        }
        self.client.post("/verify-event", json=payload)

        # Check system classification after
        cls_after = self.client.get("/events/EVT-000003/classification").json()
        self.assertEqual(cls_after["classification"], sys_class_before)
        self.assertEqual(cls_after["method"], "RULE_BASED")

    # 10. Event history remains unchanged
    def test_10_event_history_remains_unchanged(self):
        hist_before = self.client.get("/events/EVT-000003/history").json()
        payload = {
            "event_id": "EVT-000003",
            "label": "WILDLAND_FIRE"
        }
        self.client.post("/verify-event", json=payload)
        hist_after = self.client.get("/events/EVT-000003/history").json()
        self.assertEqual(hist_after["observation_count"], hist_before["observation_count"])
        self.assertEqual(hist_after["brightness_summary"], hist_before["brightness_summary"])
        self.assertEqual(hist_after["frp_summary"], hist_before["frp_summary"])

    # 11. Evidence profile remains unchanged
    def test_11_evidence_profile_remains_unchanged(self):
        evi_before = self.client.get("/events/EVT-000003/evidence").json()
        payload = {
            "event_id": "EVT-000003",
            "label": "INDUSTRIAL_HEAT"
        }
        self.client.post("/verify-event", json=payload)
        evi_after = self.client.get("/events/EVT-000003/evidence").json()
        self.assertEqual(evi_after["thermal"], evi_before["thermal"])
        self.assertEqual(evi_after["temporal"], evi_before["temporal"])

    # 12. Anomaly analysis remains unchanged
    def test_12_anomaly_analysis_remains_unchanged(self):
        anom_before = self.client.get("/events/EVT-000003/anomaly").json()
        payload = {
            "event_id": "EVT-000003",
            "label": "ACTIVE_FIRE"
        }
        self.client.post("/verify-event", json=payload)
        anom_after = self.client.get("/events/EVT-000003/anomaly").json()
        self.assertEqual(anom_after["interpretation"], anom_before["interpretation"])

    # 13. Verification endpoint response structure
    def test_13_verification_endpoint_response(self):
        res = self.client.get("/events/EVT-000002/verification")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        keys = ["event_id", "status", "verified", "label", "verified_at", "updated_at", "notes", "system_classification_at_review", "record"]
        for k in keys:
            self.assertIn(k, data)

    # 14. Multiple verified events in dataset
    def test_14_multiple_verified_events(self):
        payload = {
            "event_id": "EVT-000001",
            "label": "ACTIVE_FIRE"
        }
        res = self.client.post("/verify-event", json=payload)
        self.assertEqual(res.status_code, 200)
        list_res = self.client.get("/verified-events").json()
        self.assertGreaterEqual(len(list_res), 2)

    # 15. UNKNOWN human verification
    def test_15_unknown_human_verification(self):
        payload = {
            "event_id": "EVT-000003",
            "label": "UNKNOWN",
            "notes": "Insufficient resolution to verify source."
        }
        res = self.client.post("/verify-event", json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["label"], "UNKNOWN")

    # 16. All five human labels allowed
    def test_16_all_five_human_labels(self):
        labels = ["ACTIVE_FIRE", "INDUSTRIAL_HEAT", "AGRICULTURAL_BURNING", "WILDLAND_FIRE", "UNKNOWN"]
        for lbl in labels:
            payload = {
                "event_id": "EVT-000003",
                "label": lbl
            }
            res = self.client.post("/verify-event", json=payload)
            self.assertEqual(res.status_code, 200, f"Failed for label: {lbl}")
            self.assertEqual(res.json()["label"], lbl)

    # 17. New verification stores complete AI snapshot
    def test_17_new_verification_stores_ai_snapshot(self):
        payload = {
            "event_id": "EVT-000029",
            "label": "INDUSTRIAL_HEAT",
            "notes": "Analyst verified recurring industrial heat source."
        }
        res = self.client.post("/verify-event", json=payload)
        self.assertEqual(res.status_code, 200)
        rec = res.json()["record"]
        self.assertTrue(rec["ai_snapshot_available"])
        self.assertIsNotNone(rec["ai_snapshot"])
        self.assertIn("ml_class", rec["ai_snapshot"])
        self.assertIn("ml_confidence", rec["ai_snapshot"])
        self.assertIn("assessment", rec["ai_snapshot"])
        self.assertIn("assessment_confidence", rec["ai_snapshot"])
        self.assertIn("evidence", rec["ai_snapshot"])

    # 18. ML probabilities are preserved in AI snapshot
    def test_18_ml_probabilities_preserved(self):
        payload = {
            "event_id": "EVT-000029",
            "label": "INDUSTRIAL_HEAT"
        }
        res = self.client.post("/verify-event", json=payload)
        self.assertEqual(res.status_code, 200)
        ai_snap = res.json()["record"]["ai_snapshot"]
        self.assertIsNotNone(ai_snap["ml_probabilities"])
        for cls_name in ["AGRICULTURAL_BURNING", "INDUSTRIAL_HEAT", "WILDLAND_FIRE"]:
            self.assertIn(cls_name, ai_snap["ml_probabilities"])
            self.assertIsInstance(ai_snap["ml_probabilities"][cls_name], (int, float))

    # 19. Assessment explanation is preserved in AI snapshot
    def test_19_assessment_explanation_preserved(self):
        payload = {
            "event_id": "EVT-000029",
            "label": "INDUSTRIAL_HEAT"
        }
        res = self.client.post("/verify-event", json=payload)
        self.assertEqual(res.status_code, 200)
        ai_snap = res.json()["record"]["ai_snapshot"]
        self.assertIsNotNone(ai_snap["assessment_explanation"])
        self.assertGreater(len(ai_snap["assessment_explanation"]), 10)

    # 20. Human label remains independent and is NOT overwritten by ML class
    def test_20_human_label_not_overwritten_by_ml(self):
        # EVT-000029 has ML predicted class WILDLAND_FIRE, but analyst verifies as INDUSTRIAL_HEAT
        payload = {
            "event_id": "EVT-000029",
            "label": "INDUSTRIAL_HEAT",
            "notes": "Analyst confirms physical industrial facility despite spectral ML class."
        }
        res = self.client.post("/verify-event", json=payload)
        self.assertEqual(res.status_code, 200)
        rec = res.json()["record"]
        # Human label remains strictly what analyst provided
        self.assertEqual(rec["label"], "INDUSTRIAL_HEAT")
        # ML class remains independent
        self.assertEqual(rec["ai_snapshot"]["ml_class"], "WILDLAND_FIRE")

    # 21. Historical records without AI snapshot remain readable without errors
    def test_21_historical_records_readable_without_ai_snapshot(self):
        # In setUp, EVT-000002 has no ai_snapshot
        res = self.client.get("/events/EVT-000002/verification")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "VERIFIED")
        self.assertIsNone(data["ai_snapshot"])
        self.assertFalse(data["ai_snapshot_available"])

    # 22. Dedicated read-only dataset endpoint returns correct structure and summaries
    def test_22_verified_dataset_endpoint(self):
        res = self.client.get("/verified-events/dataset")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        for k in ["ok", "total_records", "complete_ai_snapshots", "complete_feature_vectors", "historical_incomplete_records", "human_label_distribution", "records"]:
            self.assertIn(k, data)
        self.assertEqual(data["total_records"], len(data["records"]))

    # 23. Enhanced /verified-events endpoint includes summary counts
    def test_23_enhanced_verified_events_endpoint(self):
        res = self.client.get("/verified-events")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("count", data)
        self.assertIn("ai_snapshots_count", data)
        self.assertIn("feature_vectors_count", data)
        self.assertIn("events", data)


if __name__ == "__main__":
    unittest.main()

