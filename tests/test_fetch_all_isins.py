from founder.fetch_all_isins import fetch_all_isins


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
    rows = fetch_all_isins(FakeClient())

    assert rows == [
        {
            "isin": "IE1",
            "exchange": "XETRA",
            "code": "AAA",
            "name": "Example UCITS ETF",
            "instrument_type": "ETF",
            "country": "DE",
            "currency": "EUR",
            "source_exchange": "XETRA",
            "fetched_at": rows[0]["fetched_at"],
        }
    ]
