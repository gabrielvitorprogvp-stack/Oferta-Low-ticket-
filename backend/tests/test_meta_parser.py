import json
from datetime import datetime, timedelta, timezone

from radar.crawler.meta_ads import parse_dom_cards
from radar.crawler.meta_parser import parse_result_count_text, parse_search_blobs
from tests.factories import collated, ssr_blob


def test_parse_ssr_blob_extracts_fields():
    start = datetime(2026, 9, 20, tzinfo=timezone.utc)
    sp = parse_search_blobs([ssr_blob([collated(1, start=start), collated(2)], count=40, has_next=True)])
    assert sp.total_count == 40 and len(sp.ads) == 2 and sp.has_next_page
    a = sp.ads[0]
    assert a.ad_archive_id == "1" and a.page_id == "111" and a.page_name == "Kit Teste"
    assert a.start_date == datetime(2026, 9, 20) and a.display_format == "VIDEO"
    assert a.cta_type == "SHOP_NOW" and a.link_url.startswith("https://pay.kiwify")
    assert a.hook.startswith("Seu filho não come?")


def test_technical_duplicates_share_fingerprint():
    a, b, c = (collated(1, media_id="777"), collated(2, media_id="777"),
               collated(3, media_id="888", body="Outro hook totalmente diferente"))
    ads = parse_search_blobs([ssr_blob([a, b, c])]).ads
    fps = {x.ad_archive_id: x.fingerprint for x in ads}
    assert fps["1"] == fps["2"] != fps["3"]


def test_rate_limit_and_captcha_flags():
    rl = json.dumps({"errors": [{"message": "Rate limit exceeded", "severity": "CRITICAL", "code": 1675004}]})
    assert parse_search_blobs([rl]).rate_limited
    cap = json.dumps({"data": {"xfb_ad_library_is_captcha_required": True}})
    assert parse_search_blobs([cap]).captcha_required


def test_graphql_multiline_and_prefix():
    blob = "for (;;);" + ssr_blob([collated(9)]) + "\n" + json.dumps({"extensions": {"is_final": True}})
    assert len(parse_search_blobs([blob]).ads) == 1


def test_template_body_is_ignored():
    r = collated(5, body="{{product.brand}} {{product.name}}")
    assert parse_search_blobs([ssr_blob([r])]).ads[0].body is None


def test_count_text_and_dom_fallback():
    assert parse_result_count_text("~15.000 resultados") == 15000
    assert parse_result_count_text("20 resultados") == 20
    text = ("Ativo\nIdentificação da biblioteca: 456003130916186\nVeiculação iniciada em 30 de mar de 2025\n"
            "Ver detalhes do anúncio\nLuciana RH\nPatrocinado\nCansado de não ser promovido?\nCompre já\n"
            "PAY.KIWIFY.COM.BR\nLuciana RH\nComprar agora\n")
    ads = parse_dom_cards(text)
    assert ads[0].ad_archive_id == "456003130916186" and ads[0].start_date == datetime(2025, 3, 30)
    assert ads[0].page_name == "Luciana RH" and ads[0].link_url == "https://pay.kiwify.com.br"
