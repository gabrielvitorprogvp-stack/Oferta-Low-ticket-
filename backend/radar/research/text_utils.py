"""Utilitários de texto em pt-BR: normalização, preços, URLs, plataformas, palavras-chave."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from urllib.parse import parse_qs, unquote, urlparse

PLATFORM_DOMAINS = {
    "kiwify": ("kiwify.com.br", "kiwify.app", "kiwify.com"),
    "hotmart": ("hotmart.com", "hotm.art", "hotmart.com.br"),
    "cakto": ("cakto.com.br", "cakto.com"),
    "perfectpay": ("perfectpay.com.br",),
    "eduzz": ("eduzz.com", "sun.eduzz.com"),
    "monetizze": ("monetizze.com.br",),
    "ticto": ("ticto.com.br", "ticto.app"),
    "lastlink": ("lastlink.com",),
    "greenn": ("greenn.com.br",),
    "braip": ("braip.com", "ev.braip.com"),
    "kirvano": ("kirvano.com",),
    "pepper": ("pepper.com.br",),
}

STOPWORDS = set("""
a à ao aos as até com como da das de do dos e é em entre era essa esse esta este eu foi
for há isso já la lhe mais mas me mesmo meu minha muito na nas não nem no nos nossa nosso
num o os ou para pela pelas pelo pelos por qual quando que quem se sem ser seu seus si só
sua suas também te tem tu tua um uma umas uns você vocês voce voces vai vamos ter todo toda
todos todas aqui agora ainda depois sobre isso esta está estão sao são pra pro faz fazer
seja tudo nada bem bom boa hoje dia dias vez cada outro outra apenas aquele aquela assim
clique saiba link bio abaixo acesse garanta compre comprar agora aproveite oferta acesso
imediato garantia pagamento único unico valor preço preco reais r$ www com br https http
nao sim site pagina parece conheca conheça entenda descubra veja melhor opcao opção product
name valido válido horas hora minutos ver detalhes mais quer quero pode podem precisa sabe
voce você seu sua nosso nossa dele dela tao tão ainda sempre nunca vai vem ficar fica deixe
deixa comece começa aqui ali isso aquilo esse essa estes estas desse dessa disso nesse nessa
primeiro primeira novo nova completo completa total totalmente realmente simplesmente
""".split())
TEMPLATE_RE = re.compile(r"\{\{[^}]*\}\}")

PRICE_RE = re.compile(r"R\$\s?(\d{1,4}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)", re.I)
FOREIGN_PRICE_RE = re.compile(r"(US\$|\$\s?\d|USD|€|EUR)", re.I)


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_text(s: str | None) -> str:
    if not s:
        return ""
    s = strip_accents(s.lower())
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"[^a-z0-9$ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def sha(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def parse_brl(token: str) -> float | None:
    t = token.strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") == 1 and len(t.split(".")[1]) == 3:  # 1.000
        t = t.replace(".", "")
    try:
        return round(float(t), 2)
    except ValueError:
        return None


INSTALLMENT_RE = re.compile(r"(\d{1,2}\s?x\s?(de\s)?|parcelas?\s(de\s)?|/m[eê]s|por m[eê]s)\s*$", re.I)


def extract_prices_brl(text: str | None) -> list[float]:
    """Valores em R$ citados no texto (na ordem). Ignora parcelas ('12x de R$ 6,93',
    'R$ 9,90/mês') e valores absurdos."""
    if not text:
        return []
    out = []
    for m in PRICE_RE.finditer(text):
        before = text[max(0, m.start() - 14):m.start()]
        after = text[m.end():m.end() + 8].lower()
        if INSTALLMENT_RE.search(before) or after.lstrip().startswith(("/mês", "/mes", "por mês", "mensa")):
            continue
        v = parse_brl(m.group(1))
        if v is not None and 1 <= v <= 20000:
            out.append(v)
    return out


def guess_offer_price(prices: list[float], text: str = "") -> tuple[float | None, float | None]:
    """Heurística: preço de venda = menor valor > R$5 citado; preço 'de' = maior valor
    citado quando há padrão 'de R$X por R$Y'. Retorna (preço, preço_anterior)."""
    cands = [p for p in prices if p >= 5]
    if not cands:
        return None, None
    m = re.search(r"de\s*R\$\s?([\d.,]+)\s*(?:por|para|\|)\s*(?:apenas\s*)?R\$\s?([\d.,]+)", text or "", re.I)
    if m:
        old, new = parse_brl(m.group(1)), parse_brl(m.group(2))
        if old and new and old > new:
            return new, old
    price = min(cands)
    old = max(cands) if max(cands) > price * 1.3 else None
    return price, old


def has_foreign_currency(text: str | None) -> bool:
    return bool(text and FOREIGN_PRICE_RE.search(text))


def unwrap_redirect(url: str | None) -> str | None:
    """Desembrulha l.facebook.com/l.php?u=... e similares."""
    if not url:
        return url
    p = urlparse(url)
    if p.netloc.endswith("facebook.com") and p.path.startswith("/l.php"):
        u = parse_qs(p.query).get("u")
        if u:
            return unquote(u[0])
    return url


def normalize_url(url: str | None) -> str | None:
    """Domínio + caminho, sem query/utm e sem barra final — identidade da oferta."""
    url = unwrap_redirect(url)
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    p = urlparse(url)
    host = p.netloc.lower().removeprefix("www.")
    if not host or "." not in host:
        return None
    path = re.sub(r"/+$", "", p.path or "")
    return f"{host}{path}"


def domain_of(url: str | None) -> str | None:
    n = normalize_url(url)
    return n.split("/")[0] if n else None


def detect_platform(*urls_or_text: str | None) -> str | None:
    blob = " ".join(u.lower() for u in urls_or_text if u)
    for name, doms in PLATFORM_DOMAINS.items():
        if any(d in blob for d in doms):
            return name
    return None


def first_sentence(text: str | None, max_len: int = 160) -> str | None:
    """'Hook' do anúncio: primeira frase/linha significativa."""
    if not text:
        return None
    for line in re.split(r"[\n\r]+", text):
        line = line.strip(" -•*✅👉🔥➡️")
        if len(norm_text(line)) >= 8:
            s = re.split(r"(?<=[.!?])\s", line, maxsplit=1)[0]
            return s[:max_len].strip()
    return None


STOPWORDS |= {strip_accents(w) for w in STOPWORDS}


def tokenize(text: str | None) -> list[str]:
    text = TEMPLATE_RE.sub(" ", text or "")
    return [w for w in norm_text(text).split() if len(w) > 2 and w not in STOPWORDS and not w.isdigit()]


def extract_keyphrases(texts: list[str], top: int = 8, min_count: int = 2) -> list[str]:
    """Extrai bi/tri-gramas recorrentes (palavras sem stopwords) para expandir a busca.
    Ex.: 'cardápio para seletividade alimentar' -> 'seletividade alimentar'."""
    grams: Counter[str] = Counter()
    texts = list(dict.fromkeys(norm_text(t)[:500] for t in texts if t))  # versões idênticas contam 1x
    for t in texts:
        toks = tokenize(t)
        seen = set()
        for n in (2, 3):
            for i in range(len(toks) - n + 1):
                g = " ".join(toks[i:i + n])
                if g not in seen:
                    seen.add(g)
                    grams[g] += 1
    out: list[str] = []
    # mesma frequência: n-grama mais longo primeiro ("metodo controle maximo" > "controle maximo")
    ranked = sorted(grams.items(), key=lambda kv: (-kv[1], -len(kv[0].split())))
    for g, c in ranked[:120]:
        if c < min_count and len(texts) > 1:
            continue
        toks = set(g.split())
        if any(toks <= set(o.split()) or set(o.split()) <= toks for o in out):
            continue
        out.append(g)
        if len(out) >= top:
            break
    return out
