from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from enzyme_recommender.api.app import (
    app,
    client_error_payload,
    sanitize_error_message,
    stream_error_payload,
)
from enzyme_recommender.runtime.config import RuntimeConfigError


class ApiErrorHardeningTests(unittest.TestCase):
    def test_missing_generator_api_key_returns_client_safe_error(self) -> None:
        status_code, payload = client_error_payload(
            RuntimeConfigError(
                "missing API key env var for generator provider siliconflow: SILICONFLOW_API_KEY"
            )
        )

        self.assertEqual(status_code, 503)
        self.assertEqual(payload["error"]["code"], "generator_api_key_missing")
        self.assertIn("siliconflow", payload["error"]["message"])
        self.assertNotIn("SILICONFLOW_API_KEY", payload["error"]["message"])

    def test_upstream_error_redacts_secret_like_values(self) -> None:
        message = sanitize_error_message(
            "generation failed: SILICONFLOW_API_KEY=test-token-value "
            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz"
        )

        self.assertIn("SILICONFLOW_API_KEY=[redacted]", message)
        self.assertIn("Bearer [redacted]", message)
        self.assertNotIn("test-token-value", message)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", message.replace("Bearer [redacted]", ""))

    def test_stream_error_payload_uses_same_safe_contract(self) -> None:
        payload = stream_error_payload(
            RuntimeError("stream generation failed for provider siliconflow: cannot connect to provider host")
        )

        self.assertEqual(payload["event"], "error")
        self.assertEqual(payload["code"], "upstream_unavailable")
        self.assertIn("cannot connect", payload["message"])


class LegacyPdfRouteTests(unittest.TestCase):
    def test_legacy_pdf_route_maps_to_pdf_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "B10.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%test\n")

            with patch("enzyme_recommender.api.app.resolve_pdf_file", return_value=pdf_path):
                response = TestClient(app).get("/PDF/B10.pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")


if __name__ == "__main__":
    unittest.main()
