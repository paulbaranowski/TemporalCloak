import json
import random
from temporal_cloak.encoding import TemporalCloakEncoding


class QuoteProvider:
    def __init__(self, quotes_path: str = "content/quotes/quotes.json"):
        self._quotes_path = quotes_path
        with open(quotes_path, "r", encoding="utf-8") as f:
            self._quotes = json.load(f)

    @property
    def quotes_path(self) -> str:
        return self._quotes_path

    @property
    def count(self) -> int:
        return len(self._quotes)

    def get_random_quote(self) -> str:
        """Returns a random quote string formatted as 'text - author'."""
        random_quote = random.choice(self._quotes)
        quote_text = random_quote["quoteText"]
        quote_author = random_quote["quoteAuthor"]
        if quote_author.strip() != "":
            quote_author = " - " + quote_author
        return f"{quote_text}{quote_author}"

    def get_encodable_quote(self) -> str:
        """Returns a random quote that is guaranteed to be ASCII-encodable.

        Some quotes contain non-ASCII characters that can't be transmitted
        via TemporalCloak. This method retries until it finds one that works.
        """
        while True:
            quote = self.get_random_quote()
            encodable, _ = TemporalCloakEncoding.encode_message(quote)
            if encodable:
                return quote

    def __str__(self) -> str:
        return f"QuoteProvider({self.count} quotes from '{self._quotes_path}')"

    def __repr__(self) -> str:
        return f"QuoteProvider(quotes_path='{self._quotes_path}')"
