from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from deploy.remote.vitalab.scripts.quick_tunnel_sentinel import (
    extract_latest_quick_tunnel_url,
    normalize_backend_origin,
    run_once,
)


class QuickTunnelSentinelTests(unittest.TestCase):
    def test_extract_latest_quick_tunnel_url(self) -> None:
        logs = """
        INF | https://old-name.trycloudflare.com
        INF | https://new-name.trycloudflare.com
        """

        self.assertEqual(extract_latest_quick_tunnel_url(logs), "https://new-name.trycloudflare.com")

    def test_normalize_backend_origin_rejects_unsafe_origins(self) -> None:
        self.assertEqual(
            normalize_backend_origin("https://shade-temp-raising-vendor.trycloudflare.com/"),
            "https://shade-temp-raising-vendor.trycloudflare.com",
        )
        self.assertIsNone(normalize_backend_origin("http://shade-temp-raising-vendor.trycloudflare.com"))
        self.assertIsNone(normalize_backend_origin("https://example.com"))
        self.assertIsNone(normalize_backend_origin("https://shade-temp-raising-vendor.trycloudflare.com/api"))

    @patch("deploy.remote.vitalab.scripts.quick_tunnel_sentinel.build_kv_client")
    @patch("deploy.remote.vitalab.scripts.quick_tunnel_sentinel.health_ok", return_value=False)
    @patch("deploy.remote.vitalab.scripts.quick_tunnel_sentinel.restart_quick_tunnel")
    def test_local_api_unhealthy_skips_restart_and_kv_write(
        self, restart: Mock, _health: Mock, build_client: Mock
    ) -> None:
        result = run_once(Path("/tmp/vitalab"), {"ENZYME_API_PORT": "18001"})

        self.assertFalse(result)
        restart.assert_not_called()
        build_client.assert_not_called()

    @patch("deploy.remote.vitalab.scripts.quick_tunnel_sentinel.wait_for_pages_health", return_value=True)
    @patch("deploy.remote.vitalab.scripts.quick_tunnel_sentinel.write_state")
    @patch("deploy.remote.vitalab.scripts.quick_tunnel_sentinel.read_cloudflared_logs")
    @patch("deploy.remote.vitalab.scripts.quick_tunnel_sentinel.restart_quick_tunnel")
    @patch("deploy.remote.vitalab.scripts.quick_tunnel_sentinel.origin_health_ok")
    @patch("deploy.remote.vitalab.scripts.quick_tunnel_sentinel.health_ok", return_value=True)
    @patch("deploy.remote.vitalab.scripts.quick_tunnel_sentinel.build_kv_client")
    def test_new_origin_health_failure_does_not_write_kv(
        self,
        build_client: Mock,
        _health: Mock,
        origin_health: Mock,
        _restart: Mock,
        read_logs: Mock,
        _write_state: Mock,
        _pages: Mock,
    ) -> None:
        client = Mock()
        client.get_value.return_value = "https://old.trycloudflare.com"
        build_client.return_value = client
        origin_health.side_effect = [False, False]
        read_logs.return_value = "https://new.trycloudflare.com"

        result = run_once(Path("/tmp/vitalab"), {"ENZYME_API_PORT": "18001"})

        self.assertFalse(result)
        client.put_value.assert_not_called()
