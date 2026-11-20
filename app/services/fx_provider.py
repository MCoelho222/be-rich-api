"""Exchange-rate providers (specs/schemas.md §16.2).

The provider sits behind `RateProvider` so it can be swapped.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.domain.enums import Currency


class RateProviderError(Exception):
    pass


@dataclass(frozen=True)
class Quote:
    rate_date: date
    base: Currency
    quote: Currency
    rate: Decimal


class RateProvider(Protocol):
    source: str

    def latest(self, base: Currency, quotes: list[Currency]) -> list[Quote]: ...

    def on(self, day: date, base: Currency, quotes: list[Currency]) -> list[Quote]: ...


class FrankfurterProvider:
    """European Central Bank reference rates via Frankfurter: free, no API key,
    supports BRL and historical dates. Days without rates (weekends, holidays)
    return the most recent earlier rate, with that rate's date."""

    source = "frankfurter"

    def __init__(self, base_url: str, timeout: float = 5.0, transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)

    def _get(self, path: str, base: Currency, quotes: list[Currency]) -> list[Quote]:
        try:
            response = self.client.get(path, params={"base": base.value, "symbols": ",".join(q.value for q in quotes)})
            response.raise_for_status()
            body = response.json()
            day = date.fromisoformat(body["date"])
            return [
                Quote(day, base, Currency(code), Decimal(str(value)))
                for code, value in body["rates"].items()
                if code in Currency.__members__
            ]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise RateProviderError(f"{self.source} {path}: {exc}") from exc

    def latest(self, base: Currency, quotes: list[Currency]) -> list[Quote]:
        return self._get("/latest", base, quotes)

    def on(self, day: date, base: Currency, quotes: list[Currency]) -> list[Quote]:
        return self._get(f"/{day.isoformat()}", base, quotes)


@lru_cache
def get_rate_provider() -> RateProvider:
    return FrankfurterProvider(get_settings().fx_base_url)
