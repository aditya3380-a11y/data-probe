"""Tests for the local web prototype's analysis API."""
import io
import re
import unittest
from unittest.mock import patch
from urllib.error import URLError

import web_app
from web_app import app


class WebAppTests(unittest.TestCase):
    """Check that the web API validates inputs and returns detector results."""

    def setUp(self):
        """Create an isolated Flask test client for each test."""
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_dashboard_loads(self):
        """Check that the local dashboard route serves its page."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Data Probe", response.data)
        self.assertIn(b'value="synthetic" checked', response.data)
        self.assertIn(b'id="evaluation-preview"', response.data)
        self.assertIn(b'id="score-bars"', response.data)
        self.assertIn(b'id="table-page-size"', response.data)
        self.assertIn(b'id="table-sort"', response.data)
        self.assertIn(b'id="row-search"', response.data)
        self.assertIn(b'data-filter="Both"', response.data)
        self.assertIn(b'id="chart-tooltip"', response.data)
        self.assertIn(b'id="health-details-content"', response.data)
        self.assertIn(b'id="z-feature"', response.data)
        self.assertIn(b'Rotatable three-dimensional scatter plot', response.data)
        self.assertIn(b'data-page="map"', response.data)
        self.assertIn(b'data-page="report"', response.data)
        self.assertIn(b'data-page="guide"', response.data)
        self.assertIn(b'data-page="about"', response.data)
        self.assertIn(b'Aditya Pandey', response.data)
        self.assertIn(b'profile-photo.webp', response.data)
        self.assertIn(b'profile-qr.svg', response.data)
        self.assertIn(b'TECHNOLOGY I USED', response.data)
        self.assertIn(b'What I <em>learned</em>', response.data)
        self.assertIn(b'scikit-learn', response.data)
        self.assertIn(b'data leakage', response.data)
        self.assertNotIn(b'START HERE', response.data)
        self.assertNotIn(b'YOUR DATA, DECODED', response.data)
        self.assertNotIn(b'OPTIONAL', response.data)
        self.assertNotIn(b'about-project-icon', response.data)
        self.assertIn(b'AI-ASSISTED', response.data)

    def test_profile_qr_is_served_as_svg(self):
        """Check that the personal-profile QR code is generated locally."""
        response = self.client.get("/profile-qr.svg")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/svg+xml")
        self.assertIn(b"<svg", response.data)

    def test_synthetic_analysis_returns_metrics_and_labels(self):
        """Check that synthetic input returns health and evaluation results."""
        response = self.client.post("/api/analyze", data={"source": "synthetic"})

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["rows"], 2200)
        self.assertTrue(result["has_labels"])
        self.assertEqual(result["iqr_count"], 129)
        self.assertEqual(result["if_count"], 110)
        self.assertEqual(result["chart_rows_shown"], 1200)
        self.assertTrue(result["chart_rows_sampled"])
        self.assertEqual(result["evaluation_target_count"], 120)
        self.assertEqual(result["range_limits"]["exam_score"], [0, 100])
        self.assertEqual(len(result["suspects"]), 155)
        self.assertEqual(
            {row["flagged_by"] for row in result["suspects"]},
            {"Both", "IQR only", "Isolation Forest only"},
        )
        self.assertEqual(len(result["evaluation"]), 4)

    def test_upload_reads_semicolon_csv_without_labels(self):
        """Check that an uploaded UCI-style CSV is analyzed without accuracy."""
        response = self.client.post(
            "/api/analyze",
            data={
                "source": "upload",
                "file": (io.BytesIO(b"age;G1;G2\n16;10;12\n17;8;9\n"), "students.csv"),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["rows"], 2)
        self.assertFalse(result["has_labels"])
        self.assertEqual(result["features"], ["age", "G1", "G2"])
        self.assertEqual(result["chart_rows_shown"], 2)
        self.assertFalse(result["chart_rows_sampled"])

    def test_uploaded_anomaly_type_is_not_treated_as_known_truth(self):
        """Do not score uploaded labels using the synthetic demo's label rules."""
        response = self.client.post(
            "/api/analyze",
            data={
                "source": "upload",
                "file": (
                    io.BytesIO(
                        b"age;G1;G2;anomaly_type\n"
                        b"16;10;12;normal\n"
                        b"17;8;9;review\n"
                        b"18;12;11;normal\n"
                    ),
                    "labeled-students.csv",
                ),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertFalse(result["has_labels"])
        self.assertNotIn("evaluation", result)

    def test_two_numeric_feature_upload_is_still_analyzed(self):
        """A CSV can be analyzed even when it cannot supply three chart axes."""
        response = self.client.post(
            "/api/analyze",
            data={
                "source": "upload",
                "file": (
                    io.BytesIO(b"age;G1\n16;10\n17;8\n18;12\n"),
                    "two-features.csv",
                ),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["features"], ["age", "G1"])
        self.assertEqual(result["rows"], 3)

    def test_uci_dataset_is_not_scored_as_labeled(self):
        """Do not show accuracy for the real UCI file without trusted labels."""
        response = self.client.post("/api/analyze", data={"source": "uci"})

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["rows"], 395)
        self.assertFalse(result["has_labels"])
        self.assertNotIn("evaluation", result)

    def test_invalid_contamination_is_rejected(self):
        """Check that invalid detector settings return a clear client error."""
        response = self.client.post(
            "/api/analyze",
            data={"source": "synthetic", "contamination": "0.8"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("contamination", response.get_json()["error"].lower())

    def test_pdf_report_download_contains_valid_pdf(self):
        summary = {
            "dataset_name": "A small student dataset",
            "rows": 100,
            "columns": 5,
            "numeric_features": 4,
            "rows_with_missing": 2,
            "duplicates": 1,
            "range_violations": 0,
            "iqr_count": 8,
            "if_count": 5,
            "both_count": 3,
            "suspect_count": 10,
            "has_labels": False,
        }
        response = self.client.post(
            "/api/report.pdf", json=summary
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertTrue(response.data.startswith(b"%PDF-"))
        self.assertIn(b"Data Probe", response.data)
        self.assertEqual(len(re.findall(rb"/Type\s*/Page\b", response.data)), 1)
        self.assertIn(b"/MediaBox [ 0 0 612 792 ]", response.data)
        self.assertIn(b"/BaseFont /Helvetica-Bold", response.data)

    def test_pdf_report_rejects_raw_record_data(self):
        response = self.client.post(
            "/api/report.pdf",
            json={"records": [{"student_name": "A"}]},
        )

        self.assertEqual(response.status_code, 400)

    def test_llm_explanation_sends_aggregate_counts_only(self):
        summary = {
            "rows": 100, "columns": 5, "numeric_features": 4,
            "rows_with_missing": 2, "duplicates": 1,
            "range_violations": 0, "iqr_count": 8, "if_count": 5,
            "both_count": 3, "suspect_count": 10, "has_labels": False,
        }
        with patch.object(
            web_app, "_ollama_request", return_value={"response": "A few rows deserve a closer look."}
        ) as ollama_request:
            response = self.client.post("/api/explain", json=summary)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["explanation"],
            "A few rows deserve a closer look.",
        )
        prompt = ollama_request.call_args.args[1]["prompt"]
        self.assertIn('"rows": 100', prompt)
        self.assertIn("not a deep dataset analysis", prompt)
        self.assertIn("may be incomplete", prompt)
        self.assertNotIn("filename", prompt.lower())
        self.assertNotIn("student name", prompt.lower())

    def test_llm_explanation_includes_validated_practice_scores(self):
        response = self.client.post(
            "/api/analyze",
            data={"source": "synthetic"},
        )
        result = response.get_json()
        summary = {
            "rows": result["rows"],
            "columns": result["columns"],
            "numeric_features": len(result["features"]),
            "rows_with_missing": result["rows_with_missing"],
            "duplicates": result["duplicates"],
            "range_violations": result["range_violations"],
            "iqr_count": result["iqr_count"],
            "if_count": result["if_count"],
            "both_count": result["both_count"],
            "suspect_count": result["suspect_count"],
            "has_labels": True,
            "evaluation": [
                {
                    **{
                        key: item[key]
                        for key in ("detector", "precision", "recall", "f1")
                    },
                    **{
                        key: int(item[key])
                        for key in ("TP", "FP", "FN")
                    },
                }
                for item in result["evaluation"]
            ],
        }
        with patch.object(
            web_app, "_ollama_request", return_value={"response": "Scores included."}
        ) as ollama_request:
            explanation = self.client.post("/api/explain", json=summary)

        self.assertEqual(explanation.status_code, 200)
        prompt = ollama_request.call_args.args[1]["prompt"]
        self.assertIn('"precision": 0.659', prompt)
        self.assertIn("IQR: Precision 0.659, Recall 0.708, F1 0.683", prompt)
        self.assertIn("results are in-sample and not a held-out test", prompt)
        self.assertNotIn("student-mat.csv", prompt)

    def test_llm_explanation_rejects_row_data(self):
        response = self.client.post(
            "/api/explain",
            json={"records": [{"student_name": "A"}]},
        )

        self.assertEqual(response.status_code, 400)

    def test_llm_status_explains_when_local_service_is_missing(self):
        with patch.object(web_app, "_ollama_request", side_effect=URLError("offline")):
            response = self.client.get("/api/llm-status")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["ready"])
        self.assertIn("Ollama", response.get_json()["message"])
        self.assertIn("ollama pull llama3.2", response.get_json()["message"])


if __name__ == "__main__":
    unittest.main()
