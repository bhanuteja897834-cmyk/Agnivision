"""
AGNIVISION-GIS: Unit and Integration Tests for NASA FIRMS Spatio-Temporal Clustering (Stage 3)
"""
import unittest
from fastapi.testclient import TestClient

try:
    from backend.data.firms.clustering import (
        FIRMSSpatioTemporalClusteringService,
        classify_frp_intensity,
        classify_operational_state,
        haversine_distance,
        FRP_THRESHOLDS
    )
    import backend.main as main_module
except ImportError:
    from data.firms.clustering import (
        FIRMSSpatioTemporalClusteringService,
        classify_frp_intensity,
        classify_operational_state,
        haversine_distance,
        FRP_THRESHOLDS
    )
    import main as main_module


class TestFIRMSSpatioTemporalClustering(unittest.TestCase):
    def setUp(self):
        self.service = FIRMSSpatioTemporalClusteringService()
        self.client = TestClient(main_module.app)

    def test_01_haversine_distance(self):
        self.assertEqual(haversine_distance(20.0, 80.0, 20.0, 80.0), 0.0)
        d = haversine_distance(20.0, 80.0, 21.0, 80.0)
        self.assertTrue(110.0 < d < 112.0)

    def test_02_classify_frp_intensity(self):
        self.assertEqual(classify_frp_intensity(0.0), "LOW")
        self.assertEqual(classify_frp_intensity(14.9), "LOW")
        self.assertEqual(classify_frp_intensity(15.0), "MODERATE")
        self.assertEqual(classify_frp_intensity(49.9), "MODERATE")
        self.assertEqual(classify_frp_intensity(50.0), "HIGH")
        self.assertEqual(classify_frp_intensity(149.9), "HIGH")
        self.assertEqual(classify_frp_intensity(150.0), "VERY_HIGH")
        self.assertEqual(classify_frp_intensity(500.0), "VERY_HIGH")

    def test_03_classify_operational_state(self):
        self.assertEqual(classify_operational_state(1, 0.0, 1), "ISOLATED_ACTIVITY")
        self.assertEqual(classify_operational_state(1, 0.8, 1), "ISOLATED_ACTIVITY")
        self.assertEqual(classify_operational_state(2, 1.0, 1), "REPEATED_ACTIVITY")
        self.assertEqual(classify_operational_state(3, 8.5, 1), "REPEATED_ACTIVITY")
        self.assertEqual(classify_operational_state(3, 12.0, 1), "REPEATED_ACTIVITY")
        self.assertEqual(classify_operational_state(5, 24.5, 1), "PERSISTENT_ACTIVITY")
        self.assertEqual(classify_operational_state(5, 36.0, 2), "PERSISTENT_ACTIVITY")

    def test_04_single_observation_clustering(self):
        obs = [{
            "latitude": 22.5000,
            "longitude": 85.2000,
            "acq_date": "2026-09-20",
            "acq_time": "0630",
            "frp": 35.5,
            "confidence": "h",
            "satellite": "NOAA-20",
            "source": "VIIRS_NOAA20_NRT"
        }]

        result = self.service.cluster_hotspots(
            observations=obs,
            start_date="2026-09-20",
            end_date="2026-09-20",
            spatial_radius_km=3.0,
            min_observations=1
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_clusters"], 1)
        self.assertEqual(result["total_observations_analyzed"], 1)
        
        cluster = result["clusters"][0]
        self.assertEqual(cluster["cluster_id"], "CLU-20260920-0001")
        self.assertEqual(cluster["observation_count"], 1)
        self.assertEqual(cluster["total_frp"], 35.5)
        self.assertEqual(cluster["mean_frp"], 35.5)
        self.assertEqual(cluster["max_frp"], 35.5)
        self.assertEqual(cluster["frp_intensity"], "MODERATE")
        self.assertEqual(cluster["operational_state"], "ISOLATED_ACTIVITY")
        self.assertEqual(cluster["persistence_duration_hours"], 0.0)
        self.assertEqual(cluster["temporal_span_days"], 1)
        self.assertEqual(cluster["satellites"], ["NOAA-20"])
        self.assertEqual(cluster["centroid"]["latitude"], 22.5000)
        self.assertEqual(cluster["centroid"]["longitude"], 85.2000)

    def test_05_spatial_grouping_and_persistence(self):
        obs = [
            {
                "latitude": 22.5000,
                "longitude": 85.2000,
                "acq_date": "2026-09-20",
                "acq_time": "0600",
                "frp": 15.0,
                "satellite": "NOAA-20"
            },
            {
                "latitude": 22.5050,
                "longitude": 85.2050,
                "acq_date": "2026-09-20",
                "acq_time": "0830",
                "frp": 45.0,
                "satellite": "NOAA-21"
            },
            {
                "latitude": 24.5000,
                "longitude": 86.2000,
                "acq_date": "2026-09-20",
                "acq_time": "0610",
                "frp": 160.0,
                "satellite": "NOAA-20"
            }
        ]

        result = self.service.cluster_hotspots(
            observations=obs,
            start_date="2026-09-20",
            end_date="2026-09-20",
            spatial_radius_km=3.0,
            min_observations=1
        )

        self.assertEqual(result["total_clusters"], 2)
        
        # Check close cluster (2 observations)
        cluster_multi = next(c for c in result["clusters"] if c["observation_count"] == 2)
        self.assertEqual(cluster_multi["total_frp"], 60.0)
        self.assertEqual(cluster_multi["mean_frp"], 30.0)
        self.assertEqual(cluster_multi["max_frp"], 45.0)
        self.assertEqual(cluster_multi["frp_intensity"], "MODERATE")
        self.assertEqual(cluster_multi["persistence_duration_hours"], 2.5)
        self.assertEqual(cluster_multi["operational_state"], "REPEATED_ACTIVITY")
        self.assertEqual(set(cluster_multi["satellites"]), {"NOAA-20", "NOAA-21"})

        # Check distant cluster (1 observation)
        cluster_single = next(c for c in result["clusters"] if c["observation_count"] == 1)
        self.assertEqual(cluster_single["total_frp"], 160.0)
        self.assertEqual(cluster_single["frp_intensity"], "VERY_HIGH")
        self.assertEqual(cluster_single["operational_state"], "ISOLATED_ACTIVITY")

    def test_06_min_observations_filter(self):
        obs = [
            {"latitude": 22.5000, "longitude": 85.2000, "acq_date": "2026-09-20", "acq_time": "0600", "frp": 10.0},
            {"latitude": 22.5020, "longitude": 85.2020, "acq_date": "2026-09-20", "acq_time": "0700", "frp": 20.0},
            {"latitude": 25.0000, "longitude": 86.0000, "acq_date": "2026-09-20", "acq_time": "0600", "frp": 50.0}
        ]

        result = self.service.cluster_hotspots(
            observations=obs,
            start_date="2026-09-20",
            end_date="2026-09-20",
            spatial_radius_km=3.0,
            min_observations=2
        )

        self.assertEqual(result["total_clusters"], 1)
        self.assertEqual(result["clusters"][0]["observation_count"], 2)

    def test_07_empty_dataset(self):
        result = self.service.cluster_hotspots(
            observations=[],
            start_date="2026-09-20",
            end_date="2026-09-20",
            spatial_radius_km=3.0,
            min_observations=1
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_clusters"], 0)
        self.assertEqual(result["total_observations_analyzed"], 0)
        self.assertEqual(result["clusters"], [])

    def test_08_api_clusters_endpoint(self):
        response = self.client.get("/api/v1/hotspots/clusters?start_date=2026-09-20&end_date=2026-09-21&spatial_radius_km=3.0")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("total_clusters", data)
        self.assertIn("total_observations_analyzed", data)
        self.assertIsInstance(data["clusters"], list)

        if data["clusters"]:
            first = data["clusters"][0]
            self.assertIn("cluster_id", first)
            self.assertIn("centroid", first)
            self.assertIn("observation_count", first)
            self.assertIn("total_frp", first)
            self.assertIn("mean_frp", first)
            self.assertIn("max_frp", first)
            self.assertIn("frp_intensity", first)
            self.assertIn("operational_state", first)
            self.assertIn("persistence_duration_hours", first)
            self.assertIn("temporal_span_days", first)
            self.assertIn("satellites", first)

    def test_09_api_clusters_invalid_date(self):
        resp = self.client.get("/api/v1/hotspots/clusters?start_date=invalid&end_date=2026-09-21")
        self.assertEqual(resp.status_code, 400)

        resp2 = self.client.get("/api/v1/hotspots/clusters?start_date=2026-09-25&end_date=2026-09-20")
        self.assertEqual(resp2.status_code, 400)


if __name__ == "__main__":
    unittest.main()
