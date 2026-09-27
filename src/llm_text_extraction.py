from __future__ import annotations

from html import unescape
import json
import logging
import re

import requests

logger = logging.getLogger(__name__)


def filter_content(html_content):
    """
    Filter HTML content using BeautifulSoup to preserve structure (divs, tables)
    but remove scripts, styles, and other noise.
    """
    from bs4 import BeautifulSoup

    try:
        # Use lxml if available, else html.parser
        soup = BeautifulSoup(html_content, 'html.parser')

        # Remove unwanted tags completely
        for tag in soup(['script', 'style', 'img', 'svg', 'video', 'iframe', 'noscript', 'meta', 'link']):
            tag.decompose()

        # Remove strict structure tags but keep content (unwrap)
        for tname in ['div', 'a', 'span', 'li', 'p']:
            for tag in soup.find_all(tname):
                tag.unwrap()

        # Remove all attributes from remaining tags to reduce noise/tokens
        for tag in soup.find_all(True):
            tag.attrs = {}

        # Convert to string and normalize whitespace: remove newlines, collapse spaces
        text = str(soup)
        text = re.sub(r'[\r\n]+', ' ', text)
        text = re.sub(r'\s+', ' ', text)

        return text.strip()

    except Exception as e:
        logger.exception("Error in filter_content")
        # Fallback to simple filtering if bs4 fails
        # Using string replacement for basic cleanup
        text = html_content
        for tag in ['<div>', '</div>', '<p>', '</p>', '<span>', '</span>', '<a>', '</a>', '<li>', '</li>']:
             text = text.replace(tag, ' ')

        # Remove newlines and collapse spaces
        text = re.sub(r'[\r\n]+', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()


AREA_EVIDENCE_PATTERNS = [
    re.compile(
        r"(?:房屋建筑面积|不动产建筑面积|产权建筑面积|证载建筑面积|建筑面积)"
        r"\s*(?:为|约|是|：|:|=)?\s*([1-9]\d{0,3}(?:\.\d{1,4})?)\s*(?:㎡|平方米|平米|m²|m2)",
        re.IGNORECASE,
    ),
    re.compile(
        r"([1-9]\d{0,3}(?:\.\d{1,4})?)\s*(?:㎡|平方米|平米|m²|m2)"
        r"\s*(?:的)?(?:房屋建筑面积|不动产建筑面积|产权建筑面积|证载建筑面积|建筑面积)",
        re.IGNORECASE,
    ),
]


GENERIC_AREA_EVIDENCE_PATTERNS = [
    re.compile(
        r"面积\s*(?:为|约|是|：|:|=)?\s*([1-9]\d{0,3}(?:\.\d{1,4})?)\s*(?:㎡|平方米|平米|m²|m2)",
        re.IGNORECASE,
    ),
    re.compile(
        r"([1-9]\d{0,3}(?:\.\d{1,4})?)\s*(?:㎡|平方米|平米|m²|m2)\s*(?:的)?面积",
        re.IGNORECASE,
    ),
]


NON_BUILDING_AREA_PREFIXES = ("宗地", "土地", "占地", "用地")


def _parse_area_number(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = re.search(r"[1-9]\d{0,3}(?:\.\d{1,4})?", str(value).replace(",", ""))
        if not match:
            return None
        number = float(match.group(0))
    if number <= 0 or number > 5000:
        return None
    return round(number, 4)


def extract_area_from_text(text):
    """Extract a plausible building area from Chinese auction detail text."""
    if not text:
        return None
    normalized = re.sub(r"\s+", "", str(text))
    for pattern in AREA_EVIDENCE_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return _parse_area_number(match.group(1))
    for pattern in GENERIC_AREA_EVIDENCE_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        prefix = normalized[max(0, match.start() - 4) : match.start()]
        if any(prefix.endswith(term) for term in NON_BUILDING_AREA_PREFIXES):
            continue
        return _parse_area_number(match.group(1))
    return None


def _parse_description_data_link(soup):
    node = soup.find(id="description-data")
    if not node:
        return None
    raw = node.get_text(strip=True)
    if not raw:
        return None
    try:
        payload = json.loads(unescape(raw))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    link = payload.get("link")
    if not link:
        return None
    link = str(link).strip()
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("http://") or link.startswith("https://"):
        return link
    return None


def fetch_description_data_text(html_content, *, timeout=20):
    """Fetch Taobao/Tmall async description HTML referenced by #description-data."""
    from bs4 import BeautifulSoup

    if not html_content:
        return None
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        link = _parse_description_data_link(soup)
        if not link:
            return None
        session = requests.Session()
        session.trust_env = False
        session.proxies = {"http": None, "https": None}
        response = session.get(
            link,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://sf.taobao.com/",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        raw_bytes = getattr(response, "content", None)
        if isinstance(raw_bytes, (bytes, bytearray)):
            desc_html = _decode_response_bytes(raw_bytes)
        else:
            desc_html = str(getattr(response, "text", ""))
        desc_soup = BeautifulSoup(desc_html, "html.parser")
        return desc_soup.get_text("\n", strip=True) or desc_html
    except Exception as exc:
        logger.warning("[AREA_FALLBACK_WARN] description-data fetch failed: %s", exc)
        return None


def _decode_response_bytes(raw_bytes):
    candidates = []
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            text = raw_bytes.decode(encoding)
            candidates.append(text)
        except UnicodeDecodeError:
            continue
    if not candidates:
        return raw_bytes.decode("utf-8", errors="replace")
    return min(candidates, key=lambda text: text.count("\ufffd"))


def _parse_plain_number(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("¥", "").replace("元", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


def _parse_share_ratio(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        ratio = float(value)
    else:
        text = str(value).strip().replace("％", "%")
        fraction_match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", text)
        if fraction_match:
            numerator = float(fraction_match.group(1))
            denominator = float(fraction_match.group(2))
            if denominator == 0:
                return None
            ratio = numerator / denominator
        elif "二分之一" in text or "1/2" in text:
            ratio = 0.5
        else:
            ratio = _parse_plain_number(text)
            if ratio is not None and "%" in text:
                ratio = ratio / 100.0
    if ratio is None or ratio <= 0 or ratio > 1:
        return None
    return ratio


def _backfill_area_and_unit_price(data, area_fallback):
    if not isinstance(data, dict):
        return data
    area = _parse_area_number(data.get("建筑面积"))
    gross_area = _parse_area_number(data.get("产权建筑面积"))
    share_ratio = _parse_share_ratio(data.get("产权份额比例"))
    if area is None:
        fallback_area = _parse_area_number(area_fallback)
        if fallback_area is not None:
            if gross_area is None:
                gross_area = fallback_area
                data["产权建筑面积"] = gross_area
            area = round(gross_area * share_ratio, 2) if share_ratio and share_ratio < 1 else gross_area
            data["建筑面积"] = area
    if area is None:
        return data

    unit_price = _parse_plain_number(data.get("单价"))
    transaction_price = _parse_plain_number(data.get("成交价格"))
    if transaction_price and transaction_price > 0 and (unit_price is None or unit_price <= 0):
        data["单价"] = round(transaction_price / area, 2)
    return data


COORDINATE_PATTERNS = [
    re.compile(
        r'(?is)(?:longitude|lng)\s*["\']?\s*[:=]\s*["\']?([1-9]\d{1,2}\.\d+)[,"\']?.{0,80}?(?:latitude|lat)\s*["\']?\s*[:=]\s*["\']?(-?\d{1,2}\.\d+)',
    ),
    re.compile(
        r'(?is)(?:latitude|lat)\s*["\']?\s*[:=]\s*["\']?(-?\d{1,2}\.\d+)[,"\']?.{0,80}?(?:longitude|lng)\s*["\']?\s*[:=]\s*["\']?([1-9]\d{1,2}\.\d+)',
    ),
    re.compile(
        r'(?is)(?:center|point|lnglat|lonlat)[^0-9-]{0,20}\[\s*([1-9]\d{1,2}\.\d+)\s*,\s*(-?\d{1,2}\.\d+)\s*\]',
    ),
    re.compile(
        r'(?is)(?:longitude|lng)=([1-9]\d{1,2}\.\d+).*?(?:latitude|lat)=(-?\d{1,2}\.\d+)',
    ),
    re.compile(
        r'(?is)(?:center|point|lnglat|lonlat)\s*[:=]\s*["\']([1-9]\d{1,2}\.\d+)\s*,\s*(-?\d{1,2}\.\d+)["\']',
    ),
    re.compile(
        r'(?is)(?:AMap\.LngLat|LngLat)\s*\(\s*([1-9]\d{1,2}\.\d+)\s*,\s*(-?\d{1,2}\.\d+)\s*\)',
    ),
]


def _is_valid_china_coordinate(latitude, longitude):
    return 3.0 <= latitude <= 54.5 and 73.0 <= longitude <= 136.0


def extract_property_coordinates(html_content):
    """Best-effort coordinate extraction from raw page HTML/scripts."""
    if not html_content:
        return None

    text = str(html_content)

    for pattern in COORDINATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue

        first = float(match.group(1))
        second = float(match.group(2))
        if pattern is COORDINATE_PATTERNS[1]:
            latitude, longitude = first, second
        else:
            longitude, latitude = first, second

        if _is_valid_china_coordinate(latitude, longitude):
            return {
                "latitude": round(latitude, 6),
                "longitude": round(longitude, 6),
                "coordinate_evidence": match.group(0)[:200],
            }

    return None


__all__ = ['filter_content', 'AREA_EVIDENCE_PATTERNS', 'GENERIC_AREA_EVIDENCE_PATTERNS', 'NON_BUILDING_AREA_PREFIXES', '_parse_area_number', 'extract_area_from_text', '_parse_description_data_link', 'fetch_description_data_text', '_decode_response_bytes', '_parse_plain_number', '_parse_share_ratio', '_backfill_area_and_unit_price', 'COORDINATE_PATTERNS', '_is_valid_china_coordinate', 'extract_property_coordinates']
