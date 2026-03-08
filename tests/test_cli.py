import unittest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from temporal_cloak.cli import _normalize_url, DecodeSession, cli


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
