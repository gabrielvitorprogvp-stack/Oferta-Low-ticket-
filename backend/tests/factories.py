"""Fábricas de dados sintéticos com a MESMA estrutura do JSON da Meta Ads Library."""
import json
from datetime import datetime, timedelta, timezone


def collated(ad_id, page_id="111", page_name="Kit Teste", start=None, body="Seu filho não come? Cardápio",
             link="https://pay.kiwify.com.br/AbC123x", fmt="VIDEO", title="Cardápio Infantil", media_id=None,
             collation_id=None, cta="SHOP_NOW"):
    start = start or datetime.now(timezone.utc)
    mid = media_id or ad_id
    return {
        "ad_archive_id": str(ad_id), "collation_count": 1, "collation_id": collation_id or f"c{ad_id}",
        "is_active": True, "page_id": page_id, "page_name": page_name,
        "start_date": int(start.timestamp()), "end_date": int((start + timedelta(days=30)).timestamp()),
        "publisher_platform": ["FACEBOOK", "INSTAGRAM"],
        "snapshot": {
            "page_id": page_id, "page_name": page_name, "page_profile_uri": f"https://facebook.com/{page_id}",
            "page_categories": ["Educação"], "page_like_count": 1000, "caption": "pay.kiwify.com.br",
            "cta_text": "Comprar agora", "cta_type": cta, "cards": [], "body": {"text": body},
            "display_format": fmt, "link_url": link, "link_description": None, "title": title,
            "images": [], "videos": [{"video_preview_image_url":
                                      f"https://scontent.xx.fbcdn.net/v/t39/{mid}_{mid}99_123_n.jpg?x=1"}],
        },
    }


def ssr_blob(results, count=None, has_next=False):
    edges = [{"node": {"collated_results": [r]}} for r in results]
    return json.dumps({"require": [["x", {"__bbox": {"result": {"data": {
        "xfb_ad_library_is_captcha_required": False,
        "ad_library_main": {"search_results_connection": {
            "count": len(results) if count is None else count, "edges": edges,
            "page_info": {"end_cursor": "CUR" if has_next else "", "has_next_page": has_next}}}}}}}]]})
