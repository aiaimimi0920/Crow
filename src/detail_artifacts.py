from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote, urljoin

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

from src import llm_helper


def get_detail_archive_path(data_root: str | Path, date_str_or_obj, item_id, extension: str = ".html") -> Path:
    if isinstance(date_str_or_obj, str):
        try:
            dt = datetime.datetime.strptime(date_str_or_obj[:10], "%Y-%m-%d")
        except Exception:
            dt = datetime.datetime.now()
    elif isinstance(date_str_or_obj, (datetime.date, datetime.datetime)):
        dt = date_str_or_obj
    else:
        dt = datetime.datetime.now()

    root = Path(data_root)
    year = dt.strftime("%Y")
    day = dt.strftime("%Y-%m-%d")
    archive_dir = root / "html_archive" / year / day
    archive_dir.mkdir(parents=True, exist_ok=True)
    normalized_ext = extension if str(extension).startswith(".") else f".{extension}"
    return archive_dir / f"item-{item_id}{normalized_ext}"


def _extract_text_block(soup: BeautifulSoup, block_id: str) -> str:
    node = soup.find(id=block_id)
    if not node:
        return ""
    return "\n".join(part.strip() for part in node.stripped_strings).strip()


def _normalize_url(base_url: str, href: str | None) -> str:
    if not href:
        return ""
    href = href.strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if base_url:
        return urljoin(base_url, href)
    return href


def extract_detail_artifacts(
    data_root: str | Path,
    html_content: str,
    item_id,
    auction_date=None,
    source_url: str | None = None,
) -> dict[str, object]:
    from bs4 import BeautifulSoup

    artifact_fields: dict[str, object] = {}
    soup = BeautifulSoup(html_content, "html.parser")
    base_url = source_url or ""
    root = Path(data_root)

    detail_text = llm_helper.filter_content(html_content)
    if detail_text.strip():
        detail_text_path = get_detail_archive_path(root, auction_date or datetime.datetime.now(), item_id, extension=".txt")
        detail_text_path.write_text(detail_text, encoding="utf-8")
        artifact_fields["detail_text_path"] = os.path.relpath(detail_text_path, root).replace("\\", "/")

    notice_text = _extract_text_block(soup, "J_NoticeDetail")
    if notice_text:
        notice_path = get_detail_archive_path(root, auction_date or datetime.datetime.now(), f"{item_id}.notice", extension=".txt")
        notice_path.write_text(notice_text, encoding="utf-8")
        artifact_fields["notice_text_path"] = os.path.relpath(notice_path, root).replace("\\", "/")

    desc_text = _extract_text_block(soup, "J_desc")
    if desc_text:
        desc_path = get_detail_archive_path(root, auction_date or datetime.datetime.now(), f"{item_id}.desc", extension=".txt")
        desc_path.write_text(desc_text, encoding="utf-8")
        artifact_fields["desc_text_path"] = os.path.relpath(desc_path, root).replace("\\", "/")

    component_payloads = []
    for script in soup.select("script.J_COMPONENT"):
        raw = script.get_text(strip=True)
        if not raw:
            continue
        decoded = unquote(raw)
        try:
            component_payloads.append(json.loads(decoded))
        except Exception:
            component_payloads.append({"raw": decoded[:20000]})
    if component_payloads:
        component_path = get_detail_archive_path(root, auction_date or datetime.datetime.now(), f"{item_id}.components", extension=".json")
        component_path.write_text(json.dumps(component_payloads, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact_fields["component_payload_path"] = os.path.relpath(component_path, root).replace("\\", "/")

    attachments = []
    appraisal_urls = []
    for anchor in soup.find_all("a", href=True):
        href = _normalize_url(base_url, anchor.get("href"))
        text = " ".join(anchor.stripped_strings)
        if not href:
            continue
        if any(keyword in text for keyword in ("评估", "报告", "公告", "须知", "附件")) or re.search(r"\.(pdf|docx?|xlsx?|zip)(?:$|\?)", href, re.I):
            attachments.append({"url": href, "text": text})
            if "评估" in text or "报告" in text:
                appraisal_urls.append(href)
    if attachments:
        attachment_path = get_detail_archive_path(root, auction_date or datetime.datetime.now(), f"{item_id}.attachments", extension=".json")
        attachment_path.write_text(json.dumps(attachments, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact_fields["attachment_manifest_path"] = os.path.relpath(attachment_path, root).replace("\\", "/")
        artifact_fields["announcement_attachment_urls"] = [item["url"] for item in attachments]
        artifact_fields["appraisal_report_urls"] = sorted(set(appraisal_urls))

    image_urls = []
    for image in soup.find_all("img"):
        candidate = image.get("src") or image.get("data-src") or image.get("data-lazy-src")
        normalized = _normalize_url(base_url, candidate)
        if normalized:
            image_urls.append(normalized)
    if image_urls:
        image_path = get_detail_archive_path(root, auction_date or datetime.datetime.now(), f"{item_id}.images", extension=".json")
        image_path.write_text(json.dumps(sorted(set(image_urls)), ensure_ascii=False, indent=2), encoding="utf-8")
        artifact_fields["image_manifest_path"] = os.path.relpath(image_path, root).replace("\\", "/")

    text_source = "\n".join(part for part in (notice_text, desc_text, detail_text) if part)
    court_match = re.search(r"([\u4e00-\u9fa5]{2,30}人民法院)", text_source)
    if court_match:
        artifact_fields["court_name"] = court_match.group(1)
    case_match = re.search(r"[（(]\d{4}[)）][^\s，。,；;:：]{2,40}号", text_source)
    if case_match:
        artifact_fields["case_number"] = case_match.group(0)
    benchmark_match = re.search(r"评估基准日[：:\s]*([0-9]{4}[年/\-.][0-9]{1,2}[月/\-.][0-9]{1,2}日?)", text_source)
    if benchmark_match:
        artifact_fields["appraisal_benchmark_date"] = benchmark_match.group(1)
    agency_match = re.search(r"(?:评估机构|评估公司|评估单位)[：:\s]*([^\n，。,；;]{4,80})", text_source)
    if agency_match:
        artifact_fields["appraisal_agency_name"] = agency_match.group(1).strip()

    return artifact_fields
