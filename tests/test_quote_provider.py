import unittest
import os
import json
import tempfile
from temporal_cloak.quote_provider import QuoteProvider


class TestQuoteProvider(unittest.TestCase):
    """Tests for QuoteProvider using the real quotes.json file."""

    def setUp(self):
        self.provider = QuoteProvider()

    def test_loads_quotes(self):
        self.assertGreater(self.provider.count, 0)

    def test_get_random_quote_returns_string(self):
        quote = self.provider.get_random_quote()
        self.assertIsInstance(quote, str)
        self.assertGreater(len(quote), 0)

    def test_get_random_quote_includes_author(self):
        # With 5000+ quotes, we'll find one with an author within a few tries
        found_author = False
        for _ in range(50):
            quote = self.provider.get_random_quote()
            if " - " in quote:
                found_author = True
                break
        self.assertTrue(found_author, "No quote with author found in 50 tries")

    def test_get_encodable_quote_is_ascii(self):
        quote = self.provider.get_encodable_quote()
        quote.encode('ascii')  # Should not raise

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            QuoteProvider(quotes_path="nonexistent.json")

    def test_str(self):
        s = str(self.provider)
        self.assertIn("QuoteProvider", s)
        self.assertIn("quotes", s)

    def test_repr(self):
        r = repr(self.provider)
        self.assertIn("QuoteProvider", r)
        self.assertIn("quotes_path=", r)


class TestQuoteProviderMinimal(unittest.TestCase):
    """Tests QuoteProvider with a controlled minimal JSON file."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='ascii'
        )
        json.dump([
            {"quoteText": "Hello world", "quoteAuthor": "Test"},
            {"quoteText": "Pure ascii", "quoteAuthor": ""},
        ], self.tmpfile)
        self.tmpfile.close()
        self.provider = QuoteProvider(quotes_path=self.tmpfile.name)

    def tearDown(self):
        os.unlink(self.tmpfile.name)

    def test_count(self):
        self.assertEqual(self.provider.count, 2)

    def test_quote_without_author_has_no_dash(self):
        # One of the two quotes has empty author
        found_no_dash = False
        for _ in range(20):
            quote = self.provider.get_random_quote()
            if " - " not in quote:
                found_no_dash = True
                break
        self.assertTrue(found_no_dash)


if __name__ == '__main__':
    unittest.main()
