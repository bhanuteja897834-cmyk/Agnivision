"""
backend/test_event_engine.py

Unit tests for rule-based spatiotemporal event clustering engine and event history (event_engine.py).
These tests use small deterministic synthetic fixtures strictly for unit testing.
These fixtures NEVER appear in the production API or dashboard.
"""

import unittest
from fastapi.testclient import TestClient
from main import app
from event_engine import (
    cluster_observations_into_events,
    get_event_history_payload,
    haversine_distance,
    parse_observation_datetime,
    EVENT_SPATIAL_RADIUS_KM,
    EVENT_TEMPORAL_GAP_HOURS,
)


class TestEventEngine(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    def test_haversine_distance(self):
        # Distance between Dhanbad (23.7957, 86.4304) and nearby point ~1.1 km away
        d = haversine_distance(23.7957, 86.4304, 23.8057, 86.4304)
        self.assertAlmostEqual(d, 1.11, delta=0.1)

    def test_case_a_single_observation_event(self):
        """
        Test A: Event with one observation.
        """
        obs = [
            {
                "latitude": "23.7957",
                "longitude": "86.4304",
                "acq_date": "2026-09-21",
                "acq_time": "1200",
                "bright_ti4": "330.0",
                "frp": "4.5",
                "risk_score": 45.0,
                "geographic_validation": {"domain": "LAND", "state": "Jharkhand", "district": "Dhanbad", "city": "Dhanbad"},
            }
        ]
        events, fires = cluster_observations_into_events(obs)
        self.assertEqual(len(events), 1)
        evt = events[0]
        self.assertEqual(evt["event_id"], "EVT-000001")
        self.assertEqual(evt["observation_count"], 1)
        self.assertEqual(evt["persistence_days"], 1)
        self.assertEqual(evt["centroid"]["latitude"], 23.7957)
        self.assertEqual(evt["centroid"]["longitude"], 86.4304)
        self.assertEqual(evt["spatial_summary"]["min_latitude"], 23.7957)
        self.assertEqual(evt["spatial_summary"]["max_latitude"], 23.7957)
        self.assertEqual(evt["brightness_summary"]["min"], 330.0)
        self.assertEqual(evt["brightness_summary"]["max"], 330.0)
        self.assertEqual(evt["brightness_summary"]["avg"], 330.0)
        self.assertEqual(evt["frp_summary"]["min"], 4.5)
        self.assertEqual(evt["frp_summary"]["max"], 4.5)
        self.assertEqual(evt["frp_summary"]["avg"], 4.5)
        self.assertEqual(fires[0]["event_id"], "EVT-000001")

        # Test history payload
        payload = get_event_history_payload(evt)
        self.assertEqual(payload["event_id"], "EVT-000001")
        self.assertEqual(len(payload["observations"]), 1)

    def test_case_b_multiple_observations_event(self):
        """
        Test B: Event with multiple observations.
        """
        obs = [
            {
                "latitude": "23.7957",
                "longitude": "86.4304",
                "acq_date": "2026-09-21",
                "acq_time": "0600",
                "bright_ti4": "320.0",
                "frp": "2.0",
                "risk_score": 50.0,
                "geographic_validation": {"domain": "LAND", "state": "Jharkhand", "district": "Dhanbad"},
            },
            {
                "latitude": "23.7965",
                "longitude": "86.4310",
                "acq_date": "2026-09-21",
                "acq_time": "1800",
                "bright_ti4": "340.0",
                "frp": "6.0",
                "risk_score": 70.0,
                "geographic_validation": {"domain": "LAND", "state": "Jharkhand", "district": "Dhanbad"},
            },
            {
                "latitude": "23.7960",
                "longitude": "86.4308",
                "acq_date": "2026-09-22",
                "acq_time": "0630",
                "bright_ti4": "360.0",
                "frp": "10.0",
                "risk_score": 90.0,
                "geographic_validation": {"domain": "LAND", "state": "Jharkhand", "district": "Dhanbad"},
            },
        ]
        events, fires = cluster_observations_into_events(obs, spatial_radius_km=3.0, temporal_gap_hours=36.0)
        self.assertEqual(len(events), 1)
        evt = events[0]
        self.assertEqual(evt["observation_count"], 3)
        self.assertEqual(evt["persistence_days"], 2)
        self.assertEqual(evt["brightness_summary"]["min"], 320.0)
        self.assertEqual(evt["brightness_summary"]["max"], 360.0)
        self.assertEqual(evt["brightness_summary"]["avg"], 340.0)
        self.assertEqual(evt["frp_summary"]["min"], 2.0)
        self.assertEqual(evt["frp_summary"]["max"], 10.0)
        self.assertEqual(evt["frp_summary"]["avg"], 6.0)

    def test_case_c_chronological_ordering(self):
        """
        Test C: Chronological ordering by acq_date + acq_time.
        Observations provided in shuffled/reverse order must be reconstructed in strict chronological sequence.
        """
        obs = [
            {
                "latitude": "23.7960",
                "longitude": "86.4308",
                "acq_date": "2026-09-23",
                "acq_time": "0700",
                "bright_ti4": "350.0",
                "geographic_validation": {"domain": "LAND"},
            },
            {
                "latitude": "23.7957",
                "longitude": "86.4304",
                "acq_date": "2026-09-21",
                "acq_time": "1900",
                "bright_ti4": "310.0",
                "geographic_validation": {"domain": "LAND"},
            },
            {
                "latitude": "23.7958",
                "longitude": "86.4305",
                "acq_date": "2026-09-21",
                "acq_time": "0650",
                "bright_ti4": "300.0",
                "geographic_validation": {"domain": "LAND"},
            },
            {
                "latitude": "23.7959",
                "longitude": "86.4306",
                "acq_date": "2026-09-22",
                "acq_time": "1800",
                "bright_ti4": "330.0",
                "geographic_validation": {"domain": "LAND"},
            },
        ]
        events, _ = cluster_observations_into_events(obs, spatial_radius_km=3.0, temporal_gap_hours=36.0)
        self.assertEqual(len(events), 1)
        evt = events[0]
        history = get_event_history_payload(evt)
        ordered_obs = history["observations"]

        self.assertEqual(len(ordered_obs), 4)
        # Expected chronological timestamps:
        # 1. 2026-09-21 06:50
        # 2. 2026-09-21 19:00
        # 3. 2026-09-22 18:00
        # 4. 2026-09-23 07:00
        self.assertEqual(ordered_obs[0]["acq_date"], "2026-09-21")
        self.assertEqual(ordered_obs[0]["acq_time"], "0650")

        self.assertEqual(ordered_obs[1]["acq_date"], "2026-09-21")
        self.assertEqual(ordered_obs[1]["acq_time"], "1900")

        self.assertEqual(ordered_obs[2]["acq_date"], "2026-09-22")
        self.assertEqual(ordered_obs[2]["acq_time"], "1800")

        self.assertEqual(ordered_obs[3]["acq_date"], "2026-09-23")
        self.assertEqual(ordered_obs[3]["acq_time"], "0700")

        self.assertEqual(history["first_detected"], "2026-09-21T06:50:00Z")
        self.assertEqual(history["last_detected"], "2026-09-23T07:00:00Z")

    def test_case_d_missing_frp(self):
        """
        Test D: Missing FRP handling.
        When FRP is absent or null, frp_summary must report None rather than fabricating values.
        """
        obs = [
            {
                "latitude": "23.7957",
                "longitude": "86.4304",
                "acq_date": "2026-09-21",
                "acq_time": "1200",
                "bright_ti4": "330.0",
                "frp": None,
                "geographic_validation": {"domain": "LAND"},
            },
            {
                "latitude": "23.7960",
                "longitude": "86.4308",
                "acq_date": "2026-09-21",
                "acq_time": "1800",
                "bright_ti4": "340.0",
                "frp": "",  # Empty string
                "geographic_validation": {"domain": "LAND"},
            },
        ]
        events, _ = cluster_observations_into_events(obs)
        self.assertEqual(len(events), 1)
        evt = events[0]
        self.assertIsNone(evt["frp_summary"]["min"])
        self.assertIsNone(evt["frp_summary"]["max"])
        self.assertIsNone(evt["frp_summary"]["avg"])

    def test_case_e_missing_optional_fields(self):
        """
        Test E: Observations missing optional fields (e.g. confidence_label, bright_ti5, type).
        Calculations and summaries must remain robust.
        """
        obs = [
            {
                "latitude": "23.7957",
                "longitude": "86.4304",
                "acq_date": "2026-09-21",
                "acq_time": "1200",
                # Omit bright_ti4, bright_ti5, confidence, frp, etc.
                "geographic_validation": {"domain": "LAND"},
            }
        ]
        events, fires = cluster_observations_into_events(obs)
        self.assertEqual(len(events), 1)
        evt = events[0]
        self.assertEqual(evt["observation_count"], 1)
        self.assertIsNone(evt["brightness_summary"]["min"])
        self.assertIsNone(evt["frp_summary"]["min"])
        self.assertEqual(evt["first_detected"], "2026-09-21T12:00:00Z")

    def test_case_f_nonexistent_event_id_404(self):
        """
        Test F: Nonexistent event ID lookup returns HTTP 404.
        """
        res = self.client.get("/events/EVT-NONEXISTENT/history")
        self.assertEqual(res.status_code, 404)
        self.assertIn("not found", res.json()["detail"].lower())

    def test_land_vs_offshore_marine_separate_events(self):
        """
        LAND vs OFFSHORE_MARINE are never merged even if proximate in space and time.
        """
        obs = [
            {
                "latitude": "20.5000",
                "longitude": "86.8000",
                "acq_date": "2026-09-21",
                "acq_time": "1200",
                "bright_ti4": "330.0",
                "geographic_validation": {"domain": "LAND", "state": "Odisha"},
            },
            {
                "latitude": "20.5010",
                "longitude": "86.8010",
                "acq_date": "2026-09-21",
                "acq_time": "1200",
                "bright_ti4": "335.0",
                "geographic_validation": {"domain": "OFFSHORE_MARINE", "state": None},
            },
        ]
        events, _ = cluster_observations_into_events(obs, spatial_radius_km=3.0, temporal_gap_hours=36.0)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["geographic_domain"], "LAND")
        self.assertEqual(events[1]["geographic_domain"], "OFFSHORE_MARINE")

    def test_zero_observations(self):
        events, fires = cluster_observations_into_events([])
        self.assertEqual(events, [])
        self.assertEqual(fires, [])

    def test_deterministic_event_ids(self):
        obs = [
            {
                "latitude": "22.0",
                "longitude": "85.0",
                "acq_date": "2026-09-17",
                "acq_time": "0600",
                "geographic_validation": {"domain": "LAND"},
            },
            {
                "latitude": "24.0",
                "longitude": "87.0",
                "acq_date": "2026-09-18",
                "acq_time": "0600",
                "geographic_validation": {"domain": "LAND"},
            },
        ]
        events1, _ = cluster_observations_into_events([dict(x) for x in obs])
        events2, _ = cluster_observations_into_events([dict(x) for x in obs])
        self.assertEqual([e["event_id"] for e in events1], [e["event_id"] for e in events2])
        self.assertEqual(events1[0]["event_id"], "EVT-000001")
        self.assertEqual(events1[1]["event_id"], "EVT-000002")


if __name__ == "__main__":
    unittest.main()
