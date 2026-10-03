from radar.crawler.landing_page import LandingData, analyze_text
from radar.research.niches import detect_niche
from radar.research.offer_filter import triage
from radar.research.text_utils import (detect_platform, extract_keyphrases, extract_prices_brl,
                                       guess_offer_price, normalize_url)


def test_prices():
    t = "De R$ 97,00 por apenas R$ 27,90 ou 12x de R$ 2,79. Assinatura R$ 9,90/mês"
    assert extract_prices_brl(t) == [97.0, 27.9]
    assert guess_offer_price(extract_prices_brl(t), t) == (27.9, 97.0)
    assert extract_prices_brl("R$ 1.297,00") == [1297.0]


def test_urls_and_platform():
    assert normalize_url("https://www.site.com.br/oferta/?utm_source=fb") == "site.com.br/oferta"
    assert normalize_url("https://l.facebook.com/l.php?u=https%3A%2F%2Fpay.kiwify.com.br%2FAbc") \
        == "pay.kiwify.com.br/Abc"
    assert detect_platform("https://pay.hotmart.com/X123") == "hotmart"
    assert detect_platform(None, "PAY.KIWIFY.COM.BR") == "kiwify"


def test_keyword_expansion():
    texts = ["Cardápio para seletividade alimentar: seu filho não come?",
             "Seletividade alimentar infantil — cardápio de 30 dias",
             "{{product.name}} site não"]
    out = extract_keyphrases(texts)
    assert "seletividade alimentar" in out
    assert not any("product" in o or "site" in o for o in out)


def test_triage_accepts_low_ticket_and_rejects_exclusions():
    ok = triage(["Ebook de receitas infantis por apenas R$ 19,90. Acesso imediato!"], platform="kiwify",
                price=19.9, cta_types=["SHOP_NOW"])
    assert ok.accepted and ok.product_format == "ebook"
    assert not triage(["Apartamento à venda, condomínio com lazer, imóvel novo"]).accepted
    assert not triage(["Vote no deputado"]).accepted
    assert not triage(["Ebook completo"], platform="hotmart", price=497.0).accepted
    # substring não pode disparar exclusão ('lote' dentro de 'alongamento' etc.)
    assert triage(["Curso de alongamento de unhas, monte um lote de clientes"], platform="kiwify").accepted


def test_niche_detection_open():
    niche, phrases = detect_niche(["Seu filho não come? Cardápio para seletividade alimentar infantil",
                                   "Criança com seletividade alimentar: receitas"])
    assert niche == "Infantil / Maternidade" and "seletividade alimentar" in phrases


def test_landing_text_extraction():
    text = ("Cardápio Anti-Seletividade\nO método que faz seu filho comer legumes em até 21 dias\n"
            "De R$ 97 por apenas R$ 27,90\nBônus 1: lista de compras\nBônus 2: grupo VIP\n"
            "Garantia de 7 dias\nOferta por tempo limitado\nDepoimentos de mães\n")
    dom = {"h1": ["Cardápio Anti-Seletividade"], "h2": ["Para mães cansadas"], "buttons": ["QUERO AGORA"],
           "links": [{"href": "https://pay.kiwify.com.br/ABC", "text": "Comprar"}], "videos": [], "scripts": []}
    d = analyze_text(text, dom, LandingData(url="https://x.com"))
    assert d.headline == "Cardápio Anti-Seletividade" and d.price_brl == 27.9 and d.price_old_brl == 97.0
    assert len(d.bonuses) == 2 and "7 dias" in d.guarantee and d.urgency
    assert d.checkout_platform == "kiwify" and "método" in d.mechanism.lower()
