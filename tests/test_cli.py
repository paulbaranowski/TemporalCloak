import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from temporal_cloak.cli import (
    _normalize_url, _extract_link_id, _build_api_url, _resolve_server, DecodeSession, cli
)


class TestNormalizeUrl(unittest.TestCase):
    """Test URL normalization from various user-facing formats to API URLs."""

    # TODO: Implement these tests. _normalize_url should handle:
    #   1. A view.html URL with ?id= param → /api/image/<id>
    #   2. An /api/image/<id> URL → passed through unchanged
    #   3. A bare /api/image URL (random mode) → passed through unchanged
    #   4. A view.html URL missing the ?id= param → sys.exit(1)


class TestDecodeSessionInit(unittest.TestCase):

    def test_defaults(self):
        session = DecodeSession("https://example.com/api/image")
        self.assertEqual(session._url, "https://example.com/api/image")
        self.assertFalse(session._debug)
        self.assertIsNone(session._server_config)
        self.assertIsNone(session._cloak)
        self.assertEqual(session._total_bytes, 0)
        self.assertEqual(session._gap_count, 0)

    def test_debug_flag(self):
        session = DecodeSession("https://example.com/api/image", debug=True)
        self.assertTrue(session._debug)

    def test_repr(self):
        session = DecodeSession("https://example.com/api/image", debug=True)
        r = repr(session)
        self.assertIn("DecodeSession", r)
        self.assertIn("example.com", r)
        self.assertIn("debug=True", r)

    def test_view_url_normalized_on_init(self):
        session = DecodeSession("https://temporalcloak.cloud/view.html?id=abc123")
        self.assertEqual(session._url, "https://temporalcloak.cloud/api/image/abc123")


class TestClickCli(unittest.TestCase):

    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("TemporalCloak", result.output)

    def test_decode_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["decode", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--debug", result.output)

    @patch("temporal_cloak.cli.DecodeSession")
    def test_decode_default_url(self, mock_session_cls):
        """decode with no args should use DEFAULT_URL."""
        mock_instance = MagicMock()
        mock_session_cls.return_value = mock_instance

        runner = CliRunner()
        result = runner.invoke(cli, ["decode"])

        mock_session_cls.assert_called_once_with("https://temporalcloak.cloud/api/image", False)
        mock_instance.run.assert_called_once()

    @patch("temporal_cloak.cli.DecodeSession")
    def test_decode_custom_url(self, mock_session_cls):
        mock_instance = MagicMock()
        mock_session_cls.return_value = mock_instance

        runner = CliRunner()
        result = runner.invoke(cli, ["decode", "https://example.com/api/image/xyz"])

        mock_session_cls.assert_called_once_with("https://example.com/api/image/xyz", False)

    @patch("temporal_cloak.cli.DecodeSession")
    def test_decode_debug_flag(self, mock_session_cls):
        mock_instance = MagicMock()
        mock_session_cls.return_value = mock_instance

        runner = CliRunner()
        result = runner.invoke(cli, ["decode", "--debug"])

        mock_session_cls.assert_called_once_with("https://temporalcloak.cloud/api/image", True)


class TestExtractLinkId(unittest.TestCase):
    """Test _extract_link_id with various URL formats."""

    def test_bare_id(self):
        self.assertEqual(_extract_link_id("abc123"), "abc123")

    def test_view_url(self):
        self.assertEqual(
            _extract_link_id("https://temporalcloak.cloud/view.html?id=abc123"),
            "abc123",
        )

    def test_api_image_url(self):
        self.assertEqual(
            _extract_link_id("https://temporalcloak.cloud/api/image/abc123"),
            "abc123",
        )

    def test_api_image_debug_url(self):
        self.assertEqual(
            _extract_link_id("https://temporalcloak.cloud/api/image/abc123/debug"),
            "abc123",
        )

    def test_api_image_normal_url(self):
        self.assertEqual(
            _extract_link_id("https://temporalcloak.cloud/api/image/abc123/normal"),
            "abc123",
        )

    def test_view_url_missing_id_exits(self):
        with self.assertRaises(SystemExit):
            _extract_link_id("https://temporalcloak.cloud/view.html")

    def test_unrecognized_url_returns_none(self):
        self.assertIsNone(
            _extract_link_id("https://temporalcloak.cloud/something/else")
        )

    def test_random_image_url_returns_none(self):
        self.assertIsNone(
            _extract_link_id("https://temporalcloak.cloud/api/image")
        )


class TestResolveServer(unittest.TestCase):
    """Test _resolve_server alias resolution."""

    def test_local_alias(self):
        self.assertEqual(_resolve_server("local"), "http://localhost:8888")

    def test_prod_alias(self):
        self.assertEqual(_resolve_server("prod"), "https://temporalcloak.cloud")

    def test_case_insensitive(self):
        self.assertEqual(_resolve_server("LOCAL"), "http://localhost:8888")
        self.assertEqual(_resolve_server("Prod"), "https://temporalcloak.cloud")

    def test_full_url_passthrough(self):
        self.assertEqual(_resolve_server("https://example.com"), "https://example.com")

    def test_full_url_trailing_slash_stripped(self):
        self.assertEqual(_resolve_server("http://localhost:9999/"), "http://localhost:9999")


class TestBuildApiUrl(unittest.TestCase):

    def test_debug_from_full_url(self):
        self.assertEqual(
            _build_api_url("https://temporalcloak.cloud/api/image/abc", "abc", suffix="debug"),
            "https://temporalcloak.cloud/api/image/abc/debug",
        )

    def test_debug_from_bare_id(self):
        self.assertEqual(
            _build_api_url("abc123", "abc123", suffix="debug"),
            "https://temporalcloak.cloud/api/image/abc123/debug",
        )

    def test_preserves_scheme_and_host(self):
        self.assertEqual(
            _build_api_url("http://localhost:8888/view.html?id=x", "x", suffix="debug"),
            "http://localhost:8888/api/image/x/debug",
        )

    def test_no_suffix(self):
        self.assertEqual(
            _build_api_url("https://example.com/api/image/abc", "abc"),
            "https://example.com/api/image/abc",
        )

    def test_normal_suffix(self):
        self.assertEqual(
            _build_api_url("https://example.com/api/image/abc", "abc", suffix="normal"),
            "https://example.com/api/image/abc/normal",
        )


class TestDebugCommand(unittest.TestCase):

    def test_debug_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["debug", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("debug info", result.output)

    @patch("temporal_cloak.cli.requests.get")
    def test_debug_displays_message(self, mock_get):
        """debug command should display the message from the API response."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "id": "abc123",
            "message": "hello",
            "mode": "frontloaded",
            "image_filename": "test.jpg",
            "image_size": 10000,
            "total_chunks": 40,
            "total_gaps": 39,
            "signal_bits": "1111111100000000",
            "signal_bits_hex": "ff00",
            "signal_bit_count": 16,
            "sections": [
                {"label": "start_boundary", "bits": "1111111100000000",
                 "hex": "ff00", "offset": 0, "length": 16},
            ],
        }
        mock_get.return_value = mock_resp

        runner = CliRunner()
        result = runner.invoke(cli, ["debug", "abc123"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("hello", result.output)
        self.assertIn("abc123", result.output)
        self.assertIn("frontloaded", result.output)

    @patch("temporal_cloak.cli.requests.get")
    def test_debug_http_error(self, mock_get):
        """debug command should handle HTTP errors gracefully."""
        mock_get.side_effect = Exception("Connection refused")

        runner = CliRunner()
        result = runner.invoke(cli, ["debug", "abc123"])

        self.assertNotEqual(result.exit_code, 0)

    @patch("temporal_cloak.cli.requests.get")
    def test_debug_with_view_url(self, mock_get):
        """debug command should accept view URLs."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "id": "xyz789",
            "message": "test",
            "mode": "distributed",
            "image_filename": "img.jpg",
            "image_size": 5000,
            "total_chunks": 20,
            "total_gaps": 19,
            "signal_bits": "11111111",
            "signal_bits_hex": "ff",
            "signal_bit_count": 8,
            "sections": [],
        }
        mock_get.return_value = mock_resp

        runner = CliRunner()
        result = runner.invoke(
            cli, ["debug", "https://temporalcloak.cloud/view.html?id=xyz789"]
        )

        self.assertEqual(result.exit_code, 0)
        # Should have called the debug API URL
        mock_get.assert_called_once_with(
            "https://temporalcloak.cloud/api/image/xyz789/debug", timeout=10
        )


class TestCollectTimingData(unittest.TestCase):
    """Test _collect_timing_data builds the correct JSON structure."""

    def _make_session_with_mock_cloak(self):
        session = DecodeSession("https://example.com/api/image/abc123")
        session._start_time = 1000.0

        cloak = MagicMock()
        cloak.message = "hello"
        cloak.message_complete = True
        cloak.checksum_valid = True
        cloak.mode = "frontloaded"
        cloak.bit_count = 48
        cloak.bits.hex = "ff00abcdef01"
        cloak.threshold = 0.1500
        cloak.time_delays = [0.001, 0.302, 0.002, 0.301]
        cloak.confidence_scores = [0.95, 0.87, 0.92, 0.85]

        session._cloak = cloak
        session._raw_message = "hello"
        session._total_bytes = 12345
        session._gap_count = 48
        session._server_config = {"bit_1_delay": 0.0, "bit_0_delay": 0.30}

        return session

    @patch("time.monotonic", return_value=1014.2)
    def test_structure_has_all_keys(self, _mock_time):
        session = self._make_session_with_mock_cloak()
        data = session._collect_timing_data()

        self.assertEqual(data["version"], 1)
        self.assertIn("timestamp", data)
        self.assertEqual(data["link_id"], "abc123")
        self.assertIn("result", data)
        self.assertIn("timing", data)
        self.assertIn("server_config", data)
        self.assertIn("server_debug", data)

    @patch("time.monotonic", return_value=1014.2)
    def test_result_fields(self, _mock_time):
        session = self._make_session_with_mock_cloak()
        data = session._collect_timing_data()

        result = data["result"]
        self.assertEqual(result["message"], "hello")
        self.assertTrue(result["message_complete"])
        self.assertTrue(result["checksum_valid"])
        self.assertEqual(result["mode"], "frontloaded")
        self.assertEqual(result["bit_count"], 48)
        self.assertEqual(result["bits_hex"], "ff00abcdef01")
        self.assertAlmostEqual(result["threshold"], 0.15)

    @patch("time.monotonic", return_value=1014.2)
    def test_timing_fields(self, _mock_time):
        session = self._make_session_with_mock_cloak()
        data = session._collect_timing_data()

        timing = data["timing"]
        self.assertEqual(timing["total_bytes"], 12345)
        self.assertEqual(timing["gap_count"], 48)
        self.assertAlmostEqual(timing["elapsed_seconds"], 14.2, places=1)
        self.assertEqual(len(timing["delays"]), 4)
        self.assertEqual(len(timing["confidence_scores"]), 4)

    @patch("time.monotonic", return_value=1014.2)
    def test_server_config_included(self, _mock_time):
        session = self._make_session_with_mock_cloak()
        data = session._collect_timing_data()

        self.assertEqual(data["server_config"]["bit_1_delay"], 0.0)
        self.assertEqual(data["server_config"]["bit_0_delay"], 0.30)


class TestSaveTimingData(unittest.TestCase):
    """Test _save_timing_data writes valid JSON."""

    @patch("temporal_cloak.cli.requests.get")
    @patch("time.monotonic", return_value=1010.0)
    def test_saves_json_file(self, _mock_time, mock_get):
        """Verify timing data is written as valid JSON."""
        # Mock server debug response
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"signal_bits": "1100"}
        mock_get.return_value = mock_resp

        session = DecodeSession("https://example.com/api/image/testid")
        session._start_time = 1000.0
        session._console = MagicMock()

        cloak = MagicMock()
        cloak.message = "test"
        cloak.message_complete = True
        cloak.checksum_valid = True
        cloak.mode = "frontloaded"
        cloak.bit_count = 16
        cloak.bits.hex = "ff00"
        cloak.threshold = 0.15
        cloak.time_delays = [0.01, 0.30]
        cloak.confidence_scores = [0.9, 0.8]
        cloak.hamming = False
        cloak.hamming_corrections = 0
        session._cloak = cloak
        session._raw_message = "test"
        session._total_bytes = 5000
        session._gap_count = 16

        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join

            def patched_join(*args):
                if len(args) >= 2 and args[0] == "data" and args[1] == "timing":
                    return original_join(tmpdir, "timing")
                return original_join(*args)

            with patch("temporal_cloak.cli.os.path.join", side_effect=patched_join):
                session._save_timing_data()

            timing_dir = original_join(tmpdir, "timing")
            files = os.listdir(timing_dir)
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].startswith("testid_"))
            self.assertTrue(files[0].endswith(".json"))

            with open(original_join(timing_dir, files[0])) as f:
                saved = json.load(f)

            self.assertEqual(saved["version"], 1)
            self.assertEqual(saved["link_id"], "testid")
            self.assertEqual(saved["result"]["message"], "test")

            # Verify server debug was fetched
            mock_get.assert_called_once()
            self.assertIn("/debug", mock_get.call_args[0][0])
            self.assertEqual(saved["server_debug"]["signal_bits"], "1100")

    @patch("time.monotonic", return_value=1010.0)
    def test_no_save_without_cloak(self, _mock_time):
        """Should not save if no cloak exists (decode never started)."""
        session = DecodeSession("https://example.com/api/image")
        session._console = MagicMock()

        with patch("builtins.open") as mock_open:
            session._save_timing_data()
            mock_open.assert_not_called()


class TestTimingCommand(unittest.TestCase):
    """Test the 'timing' CLI command output."""

    def _make_timing_data(self, server_debug=None):
        return {
            "version": 1,
            "timestamp": "2026-03-09T12:34:56+00:00",
            "url": "https://example.com/api/image/abc123",
            "link_id": "abc123",
            "result": {
                "message": "hello world",
                "message_complete": True,
                "checksum_valid": True,
                "mode": "distributed",
                "bit_count": 120,
                "bits_hex": "ff01" + "ab" * 58,
                "threshold": 0.1523,
            },
            "timing": {
                "delays": [0.001 + i * 0.003 for i in range(120)],
                "confidence_scores": [0.5 + (i % 10) * 0.05 for i in range(120)],
                "total_bytes": 12345,
                "gap_count": 48,
                "elapsed_seconds": 14.2,
            },
            "server_config": {"bit_1_delay": 0.0, "bit_0_delay": 0.30},
            "server_debug": server_debug,
        }

    def test_timing_displays_summary(self):
        runner = CliRunner()
        data = self._make_timing_data()

        with runner.isolated_filesystem():
            with open("test_timing.json", "w") as f:
                json.dump(data, f)

            result = runner.invoke(cli, ["timing", "test_timing.json"])

            self.assertEqual(result.exit_code, 0)
            self.assertIn("distributed", result.output)
            self.assertIn("hello world", result.output)
            self.assertIn("0.1523", result.output)
            self.assertIn("14.2", result.output)

    def test_timing_displays_per_bit(self):
        runner = CliRunner()
        data = self._make_timing_data()

        with runner.isolated_filesystem():
            with open("test_timing.json", "w") as f:
                json.dump(data, f)

            result = runner.invoke(cli, ["timing", "test_timing.json"])

            self.assertEqual(result.exit_code, 0)
            # Should contain per-bit table header and data
            self.assertIn("Per-Bit", result.output)
            self.assertIn("boundary", result.output)
            self.assertIn("payload", result.output)
            # Message is complete, so end boundary phase should appear
            self.assertIn("end boundary", result.output)

    def test_timing_displays_histogram(self):
        runner = CliRunner()
        data = self._make_timing_data()

        with runner.isolated_filesystem():
            with open("test_timing.json", "w") as f:
                json.dump(data, f)

            result = runner.invoke(cli, ["timing", "test_timing.json"])

            self.assertEqual(result.exit_code, 0)
            self.assertIn("Histogram", result.output)
            self.assertIn("threshold", result.output.lower())

    def test_timing_limit_option(self):
        runner = CliRunner()
        data = self._make_timing_data()

        with runner.isolated_filesystem():
            with open("test_timing.json", "w") as f:
                json.dump(data, f)

            result = runner.invoke(cli, ["timing", "--limit", "5", "test_timing.json"])

            self.assertEqual(result.exit_code, 0)
            # Should show truncation note
            self.assertIn("more", result.output)


class TestTimingCommandWithServerComparison(unittest.TestCase):
    """Test the timing command with server_debug data."""

    def test_comparison_table_shown(self):
        runner = CliRunner()
        # Create matching signal bits for a clean comparison
        bits_hex = "ff00ab"
        bits_bin = bin(int(bits_hex, 16))[2:].zfill(len(bits_hex) * 4)

        data = {
            "version": 1,
            "timestamp": "2026-03-09T12:34:56+00:00",
            "url": "https://example.com/api/image/abc123",
            "link_id": "abc123",
            "result": {
                "message": "test",
                "message_complete": True,
                "checksum_valid": True,
                "mode": "frontloaded",
                "bit_count": 24,
                "bits_hex": bits_hex,
                "threshold": 0.15,
            },
            "timing": {
                "delays": [0.01] * 24,
                "confidence_scores": [0.9] * 24,
                "total_bytes": 5000,
                "gap_count": 24,
                "elapsed_seconds": 5.0,
            },
            "server_config": {"bit_1_delay": 0.0, "bit_0_delay": 0.30},
            "server_debug": {
                "signal_bits": bits_bin,
                "signal_bit_count": 24,
            },
        }

        with runner.isolated_filesystem():
            with open("test_timing.json", "w") as f:
                json.dump(data, f)

            result = runner.invoke(cli, ["timing", "test_timing.json"])

            self.assertEqual(result.exit_code, 0)
            self.assertIn("Comparison", result.output)
            self.assertIn("0 mismatches", result.output)

    def test_comparison_highlights_mismatches(self):
        runner = CliRunner()

        data = {
            "version": 1,
            "timestamp": "2026-03-09T12:34:56+00:00",
            "url": "https://example.com/api/image/abc123",
            "link_id": "abc123",
            "result": {
                "message": "test",
                "message_complete": True,
                "checksum_valid": True,
                "mode": "frontloaded",
                "bit_count": 8,
                "bits_hex": "ff",
                "threshold": 0.15,
            },
            "timing": {
                "delays": [0.01] * 8,
                "confidence_scores": [0.9] * 8,
                "total_bytes": 5000,
                "gap_count": 8,
                "elapsed_seconds": 2.0,
            },
            "server_config": {},
            "server_debug": {
                "signal_bits": "11110000",  # Server expected 11110000
                "signal_bit_count": 8,
            },
        }

        with runner.isolated_filesystem():
            with open("test_timing.json", "w") as f:
                json.dump(data, f)

            result = runner.invoke(cli, ["timing", "test_timing.json"])

            self.assertEqual(result.exit_code, 0)
            self.assertIn("Comparison", result.output)
            # Client has 0xff = 11111111, server expected 11110000 → 4 mismatches
            self.assertIn("4 mismatches", result.output)


class TestCorrectionCalculation(unittest.TestCase):
    """Test that _count_bits_corrected correctly sums bit errors.

    Regression test: compute_char_bit_errors returns per_char as a list of
    (orig_char, decoded_char, bit_errors) tuples.  A previous bug passed
    this list directly to sum(), which crashed with TypeError because
    sum() cannot add tuples to int(0).
    """

    def _make_session(self, raw, corrected):
        session = DecodeSession("https://example.com/api/image")
        session._raw_message = raw
        session._corrected_message = corrected
        return session

    def test_single_char_difference(self):
        # 'e' (0x65) vs 'f' (0x66) differs by 2 bits
        session = self._make_session("Hfllo", "Hello")
        self.assertEqual(session._count_bits_corrected(), 2)

    def test_multiple_differences(self):
        # 'A' (0x41) vs 'a' (0x61) = 1 bit, 'B' (0x42) vs 'b' (0x62) = 1 bit
        session = self._make_session("AB", "ab")
        self.assertEqual(session._count_bits_corrected(), 2)

    def test_identical_strings(self):
        session = self._make_session("Hello", "Hello")
        self.assertEqual(session._count_bits_corrected(), 0)

    def test_attempt_correction_sets_state(self):
        """_attempt_correction populates raw_message and corrected_message."""
        session = DecodeSession("https://example.com/api/image")

        mock_cloak = MagicMock()
        mock_cloak.message = "Hfllo"
        mock_cloak.message_complete = True
        mock_cloak.checksum_valid = False
        mock_cloak.try_correction.return_value = ("Hello", [10])
        session._cloak = mock_cloak

        session._attempt_correction()

        self.assertEqual(session._raw_message, "Hfllo")
        self.assertEqual(session._corrected_message, "Hello")
        self.assertEqual(session._flipped_indices, [10])
        self.assertEqual(session._count_bits_corrected(), 2)
