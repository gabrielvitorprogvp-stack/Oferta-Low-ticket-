"""Parser dos dados da Meta Ads Library.

A página da biblioteca embute o resultado da 1ª página de busca em blocos
<script type="application/json"> (chave `search_results_connection`) e pagina via
GraphQL (`AdLibrarySearchPaginationQuery`). Lemos esses JSONs — mais estável que DOM.
Funções puras: testáveis com fixtures, sem navegador.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator

from radar.research.text_utils import first_sentence, norm_text, sha

RATE_LIMIT_CODES = {1675004}


@dataclass
class ParsedAd:
    ad_archive_id: str
    page_id: str
    page_name: str
    collation_id: str | None
    collation_count: int | None
    is_active: bool
    start_date: datetime | None
    end_date: datetime | None
    display_format: str | None
    body: str | None
    title: str | None
    link_url: str | None
    link_description: str | None
    caption: str | None
    cta_text: str | None
    cta_type: str | None
    page_url: str | None
    page_categories: list[str] = field(default_factory=list)
    page_like_count: int | None = None
    media: list[str] = field(default_factory=list)
    publisher_platforms: list[str] = field(default_factory=list)

    @property
    def hook(self) -> str | None:
        return first_sentence(self.body) or first_sentence(self.title)

    @property
    def fingerprint(self) -> str:
        """Identidade do criativo real: texto + título + formato + mídia principal.
        Duplicações técnicas (mesmo criativo em vários conjuntos) colapsam no mesmo hash."""
        media_key = _media_key(self.media[0]) if self.media else ""
        base = "|".join([norm_text(self.body)[:400], norm_text(self.title)[:120],
                         self.display_format or "", media_key])
        return sha(base)

    @property
    def all_text(self) -> str:
        return "\n".join(x for x in (self.body, self.title, self.link_description, self.caption) if x)


@dataclass
class SearchPage:
    total_count: int | None
    ads: list[ParsedAd]
    has_next_page: bool
    end_cursor: str | None
    captcha_required: bool = False
    rate_limited: bool = False
    errors: list[str] = field(default_factory=list)


def _media_key(url: str) -> str:
    # ".../487297091_3956485941269597_2500..._n.jpg?stp=..." -> "487297091_3956485941269597"
    m = re.search(r"/(\d+_\d+)_[^/?]*", url or "")
    return m.group(1) if m else (url or "").split("?")[0][-60:]


def _ts(v: Any) -> datetime | None:
    if v in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(int(v), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None


def _text(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, dict):
        v = v.get("text")
    if not isinstance(v, str):
        return None
    v = v.strip()
    # templates dinâmicos do catálogo ("{{product.name}}") não são copy real
    return v or None


def walk(obj: Any, key: str) -> Iterator[Any]:
    if isinstance(obj, dict):
        if key in obj:
            yield obj[key]
        for v in obj.values():
            yield from walk(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v, key)


def parse_collated(r: dict) -> ParsedAd | None:
    snap = r.get("snapshot") or {}
    ad_id = r.get("ad_archive_id")
    if not ad_id:
        return None
    cards = snap.get("cards") or []
    body = _text(snap.get("body"))
    title = _text(snap.get("title"))
    link_url = snap.get("link_url")
    link_desc = _text(snap.get("link_description"))
    cta_text, cta_type = snap.get("cta_text"), snap.get("cta_type")
    if cards:  # carrossel / DCO: usa o 1º card quando o corpo principal está vazio
        c0 = cards[0] or {}
        body = body or _text(c0.get("body"))
        title = title or _text(c0.get("title"))
        link_url = link_url or c0.get("link_url")
        link_desc = link_desc or _text(c0.get("link_description"))
        cta_text = cta_text or c0.get("cta_text")
        cta_type = cta_type or c0.get("cta_type")
    if body and "{{" in body and "}}" in body:
        body = None

    media: list[str] = []
    for v in snap.get("videos") or []:
        u = v.get("video_preview_image_url") or v.get("video_sd_url")
        if u:
            media.append(u)
    for im in snap.get("images") or []:
        u = im.get("original_image_url") or im.get("resized_image_url")
        if u:
            media.append(u)
    for c in cards:
        u = (c or {}).get("original_image_url") or (c or {}).get("video_preview_image_url")
        if u:
            media.append(u)

    return ParsedAd(
        ad_archive_id=str(ad_id),
        page_id=str(r.get("page_id") or snap.get("page_id") or ""),
        page_name=r.get("page_name") or snap.get("page_name") or "",
        collation_id=str(r["collation_id"]) if r.get("collation_id") else None,
        collation_count=r.get("collation_count"),
        is_active=bool(r.get("is_active", True)),
        start_date=_ts(r.get("start_date")),
        end_date=_ts(r.get("end_date")),
        display_format=snap.get("display_format"),
        body=body,
        title=title,
        link_url=link_url,
        link_description=link_desc,
        caption=snap.get("caption"),
        cta_text=cta_text,
        cta_type=cta_type,
        page_url=snap.get("page_profile_uri"),
        page_categories=list(snap.get("page_categories") or []),
        page_like_count=snap.get("page_like_count"),
        media=media,
        publisher_platforms=list(r.get("publisher_platform") or []),
    )


def parse_connection(conn: dict) -> tuple[list[ParsedAd], int | None, bool, str | None]:
    ads: list[ParsedAd] = []
    for edge in conn.get("edges") or []:
        node = (edge or {}).get("node") or {}
        for r in node.get("collated_results") or []:
            ad = parse_collated(r)
            if ad:
                ads.append(ad)
    pi = conn.get("page_info") or {}
    return ads, conn.get("count"), bool(pi.get("has_next_page")), pi.get("end_cursor") or None


def _loads_many(text: str) -> list[Any]:
    """Respostas GraphQL podem vir como várias linhas JSON; também tolera prefixo for(;;);"""
    text = text.strip()
    if text.startswith("for (;;);"):
        text = text[len("for (;;);"):]
    out = []
    try:
        out.append(json.loads(text))
        return out
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def parse_search_blobs(blobs: list[str]) -> SearchPage:
    """Recebe textos JSON (scripts embutidos e/ou respostas GraphQL) e devolve a página."""
    ads: dict[str, ParsedAd] = {}
    total = None
    has_next, cursor = False, None
    captcha = False
    rate_limited = False
    errors: list[str] = []
    for blob in blobs:
        if not blob:
            continue
        if "search_results_connection" not in blob and "errors" not in blob \
                and "captcha" not in blob:
            continue
        for obj in _loads_many(blob):
            for flag in walk(obj, "xfb_ad_library_is_captcha_required"):
                captcha = captcha or bool(flag)
            if isinstance(obj, dict) and obj.get("errors"):
                for e in obj["errors"]:
                    errors.append(str(e.get("message")))
                    if e.get("code") in RATE_LIMIT_CODES or "rate limit" in str(e.get("message")).lower():
                        rate_limited = True
            for conn in walk(obj, "search_results_connection"):
                if not isinstance(conn, dict):
                    continue
                page_ads, count, nxt, cur = parse_connection(conn)
                for a in page_ads:
                    ads[a.ad_archive_id] = a
                if count is not None:
                    total = count if total is None else max(total, count)
                if cur:
                    has_next, cursor = nxt, cur
                elif not cursor:
                    has_next = nxt
    return SearchPage(total, list(ads.values()), has_next, cursor, captcha, rate_limited, errors)


def parse_result_count_text(text: str) -> int | None:
    """Fallback DOM: '~15.000 resultados' / '20 resultados'."""
    m = re.search(r"~?\s?([\d.]+)\s+resultados?", text or "")
    if not m:
        m = re.search(r"~?\s?([\d,]+)\s+results?", text or "")
    if not m:
        return None
    try:
        return int(re.sub(r"[.,]", "", m.group(1)))
    except ValueError:
        return None
