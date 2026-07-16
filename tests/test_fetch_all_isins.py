import pytest

from founder.fetch_all_isins import fetch_all_isins
from founder.http import EodhdHttpError


class FakeClient:
    def get_json(
        self,
        path: str,
        params: dict[str, str | int | float] | None = None,
    ) -> object:
        if path == "/exchanges-list/":
            return [{"Code": "XETRA"}, {"Code": "US"}]
        if path == "/exchange-symbol-list/XETRA":
            return [
                {
                    "Code": "AAA",
                    "Exchange": "XETRA",
                    "Name": "Example UCITS ETF",
                    "Type": "ETF",
                    "Country": "DE",
                    "Currency": "EUR",
                    "Isin": "IE1",
                }
            ]
        if path == "/exchange-symbol-list/US":
            return [{"Code": "NOISIN", "Exchange": "US", "Name": "No ISIN"}]
        raise AssertionError(path)


def test_fetch_all_isins_enumerates_exchanges_and_keeps_isin_rows() -> None:
    result = fetch_all_isins(FakeClient())

    assert result.requested_exchanges == ("US", "XETRA")
    assert result.skipped_exchanges == ()
    assert list(result.rows) == [
        {
            "isin": "IE1",
            "exchange": "XETRA",
            "code": "AAA",
            "name": "Example UCITS ETF",
            "instrument_type": "ETF",
            "country": "DE",
            "currency": "EUR",
            "source_exchange": "XETRA",
            "fetched_at": result.rows[0]["fetched_at"],
        }
    ]


class ForbiddenExchangeClient(FakeClient):
    def get_json(
        self,
        path: str,
        params: dict[str, str | int | float] | None = None,
    ) -> object:
        if path == "/exchanges-list/":
            return [{"Code": "MONEY"}, {"Code": "XETRA"}]
        if path == "/exchange-symbol-list/MONEY":
            raise EodhdHttpError("forbidden", status_code=403)
        return super().get_json(path, params)


def test_fetch_all_isins_skips_forbidden_auto_enumerated_exchanges() -> None:
    result = fetch_all_isins(ForbiddenExchangeClient())

    assert result.requested_exchanges == ("MONEY", "XETRA")
    assert result.skipped_exchanges == ("MONEY",)
    assert len(result.rows) == 1


def test_fetch_all_isins_fails_for_explicit_forbidden_exchange() -> None:
    with pytest.raises(EodhdHttpError, match="forbidden"):
        fetch_all_isins(ForbiddenExchangeClient(), exchange_codes=("MONEY",))
