from __future__ import annotations

from decimal import Decimal

import pytest

from .conftest import LANGUAGES, ok


def voice(i: int) -> dict:
    return {"id": i, "full_name": f"Voice {i}", "gender": {"id": 1, "title": "Woman"},
            "age": 29, "is_public": True, "is_rent": False, "price": None,
            "created_at": "2025-02-11 10:04:21", "image": "https://x/i.png",
            "source": "https://x/s.mp3", "languages": [LANGUAGES[0]], "favorite": False}


def test_languages_are_cached(client, api):
    route = api.get("/languages").mock(return_value=ok({"languages": [*LANGUAGES, "junk"]}))
    first = client.languages.list()
    second = client.languages.list()
    assert [x.code for x in first] == ["az", "en", "ru"]
    assert first == second
    assert route.call_count == 1
    client.languages.list(refresh=True)
    assert route.call_count == 2


def test_voices_list(client, api):
    route = api.get("/get-voices/2").mock(return_value=ok({"voices": [voice(41)]}))
    found = client.voices.list(page=2, language=6, gender="male", title="Ay")
    assert found[0].id == 41 and found[0].gender.id == 1 and found[0].age == 29
    assert found[0].languages[0].code == "az"
    assert found[0].raw["image"] == "https://x/i.png"
    params = route.calls.last.request.url.params
    assert params["language_id"] == "6" and params["gender"] == "2" and params["title"] == "Ay"


@pytest.mark.parametrize("gender,expected", [("female", "1"), ("F", "1"), (2, "2"),
                                             (None, None)])
def test_voice_gender_values(client, api, gender, expected):
    route = api.get("/get-voices/1").mock(return_value=ok({"voices": []}))
    client.voices.list(gender=gender)
    assert route.calls.last.request.url.params.get("gender") == expected


def test_voice_bad_gender_and_page(client):
    with pytest.raises(ValueError):
        client.voices.list(gender="other")
    with pytest.raises(ValueError):
        client.voices.list(gender=3)
    with pytest.raises(ValueError):
        client.voices.list(page=0)


def meta(current, last, total):
    return {"current_page": current, "last_page": last, "per_page": 24, "total": total}


def test_voices_iter_walks_pages_by_meta(client, api):
    api.get("/get-voices/1").mock(return_value=ok({"voices": [voice(i) for i in range(24)],
                                                   "meta": meta(1, 2, 29)}))
    api.get("/get-voices/2").mock(return_value=ok({"voices": [voice(i) for i in range(24, 29)],
                                                   "meta": meta(2, 2, 29)}))
    ids = [v.id for v in client.voices.iter()]
    assert ids == list(range(29))


def test_voices_iter_stops_at_last_page_even_when_it_is_full(client, api):
    first = api.get("/get-voices/1").mock(return_value=ok({
        "voices": [voice(i) for i in range(24)], "meta": meta(1, 1, 24)}))
    second = api.get("/get-voices/2").mock(return_value=ok({"voices": []}))
    assert len(list(client.voices.iter())) == 24
    assert first.call_count == 1 and second.call_count == 0


def test_voices_iter_without_meta_falls_back_to_the_page_size(client, api):
    api.get("/get-voices/1").mock(return_value=ok({"voices": [voice(i) for i in range(24)]}))
    api.get("/get-voices/2").mock(return_value=ok({"voices": [voice(i) for i in range(24, 25)]}))
    assert [v.id for v in client.voices.iter()] == list(range(25))


def test_voices_iter_stops_on_empty_page(client, api):
    api.get("/get-voices/1").mock(return_value=ok({"voices": [voice(i) for i in range(24)]}))
    third = api.get("/get-voices/2").mock(return_value=ok({"voices": []}))
    assert len(list(client.voices.iter(max_pages=5))) == 24
    assert third.call_count == 1


def test_voices_iter_stops_when_a_page_repeats(client, api):
    """Servers before 2026-10-15 answered every page number with the first page."""
    def same(_request):
        return ok({"voices": [voice(i) for i in range(24)]})

    first = api.get("/get-voices/1").mock(side_effect=same)
    second = api.get("/get-voices/2").mock(side_effect=same)
    third = api.get("/get-voices/3").mock(side_effect=same)
    assert len(list(client.voices.iter(max_pages=50))) == 24
    assert (first.call_count, second.call_count, third.call_count) == (1, 1, 0)


def test_voices_page_reports_pagination(client, api):
    api.get("/get-voices/2").mock(return_value=ok({"voices": [voice(30)], "meta": meta(2, 3, 61)}))
    page = client.voices.page(page=2)
    assert [v.id for v in page] == [30]
    assert (page.current_page, page.last_page, page.per_page, page.total) == (2, 3, 24, 61)
    assert page.has_more


def test_services(client, api):
    api.get("/services").mock(return_value=ok({"services": [
        {"id": 1, "slug": "text-to-speech", "title": "Text to speech",
         "price": {"amount": "0.30", "currency": "AZN"}},
        {"id": 5, "slug": "dubbing", "price": {"amount": "0.50", "currency": "AZN"},
         "prices": {"auto_emotion_per_min": {"amount": "0.05", "currency": "AZN"}}},
    ]}))
    services = client.services.list()
    assert services[0].price.amount == Decimal("0.30")
    assert services[1].prices["auto_emotion_per_min"].amount == Decimal("0.05")

    api.get("/service/dubbing").mock(return_value=ok({
        "service": {"id": 5, "slug": "dubbing", "price": {"amount": "0.50", "currency": "AZN"},
                    "prices": {"auto_emotion_per_min": None}, "limits": {"max_mb": 100}},
        "filters": {}, "projects": {}}))
    dubbing = client.services.get("dubbing")
    assert dubbing.slug == "dubbing" and dubbing.limits == {"max_mb": 100}
    assert dubbing.prices["auto_emotion_per_min"] is None


def test_balance_and_transactions(client, api):
    api.get("/customer/balance").mock(return_value=ok({"balance": {"amount": 12.4,
                                                                   "currency": "AZN"}}))
    assert client.account.balance().amount == Decimal("12.4")

    route = api.get("/customer/transactions").mock(return_value=ok({
        "data": [{"id": 9182, "amount": "-0.60", "currency": "AZN", "balance_snapshot": "11.80",
                  "description": "Charge for text to speech", "operation_type": "Withdrawal",
                  "balance_type": "Deposit", "status": "Completed",
                  "created_at": "2026-09-10 18:22:07"}],
        "links": {"next": "…"},
        "meta": {"current_page": 1, "from": 1, "last_page": 4, "per_page": 20, "to": 20,
                 "total": 71}}))
    page = client.account.transactions()
    tx = page.items[0]
    assert tx.amount == Decimal("-0.60") and tx.balance_snapshot == Decimal("11.80")
    assert tx.operation_type == "Withdrawal"
    assert page.has_more and page.total == 71 and page.last_page == 4
    assert route.calls.last.request.url.params["page"] == "1"
    with pytest.raises(ValueError):
        client.account.transactions(page=0)
