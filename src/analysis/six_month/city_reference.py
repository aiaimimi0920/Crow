"""Read-only NBS city-index snapshots, isolated from community-price training."""

import argparse
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import urlopen

TRAIN_CITIES = ("北京", "武汉", "温州", "宜昌")


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = ""
        self.tables = []
        self.rows = None
        self.row = None
        self.cell = None
        self.context = ""
        self.published = None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        if tag == "meta" and attrs.get("name") == "PubDate":
            self.published = attrs.get("content")
        if tag == "table":
            if self.rows is not None:
                raise ValueError("nested tables unsupported")
            self.context = self.text[-300:]
            self.rows = []
        if tag == "tr":
            self.row = []
        if tag in ("td", "th"):
            self.cell = ""

    def handle_data(self, data):
        if self.skip:
            return
        value = re.sub(r"\s+", "", data)
        self.text += value
        if self.cell is not None:
            self.cell += value

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        if tag in ("td", "th") and self.cell is not None:
            if self.row is not None:
                self.row.append(self.cell)
            self.cell = None
        if tag == "tr" and self.row is not None:
            if self.rows is not None:
                self.rows.append(self.row)
            self.row = None
        if tag == "table" and self.rows is not None:
            self.tables.append((self.context, self.rows))
            self.rows = None


def validate_header(rows):
    """Accept only documented two-panel layouts; never infer column semantics."""
    headers = []
    for row in rows:
        if any(city in row for city in TRAIN_CITIES):
            break
        headers.append(row)
    labels = any(
        len(row) == 8
        and all(row[i : i + 3] == ["城市", "环比", "同比"] for i in (0, 4))
        for row in headers
    )
    bases = any(
        (
            len(row) == 6
            and all(row[i : i + 2] == ["上月=100", "上年同月=100"] for i in (0, 3))
        )
        or (
            len(row) == 8
            and all(row[i + 1 : i + 3] == ["上月=100", "上年同月=100"] for i in (0, 4))
        )
        for row in headers
    )
    if not labels or not bases:
        raise ValueError("unsupported or ambiguous index column order")


def parse_snapshot(raw, source_url, retrieved_at):
    """No vintage claim: downloaded snapshot cannot enter past-origin inputs."""
    url = urlparse(source_url)
    if url.scheme != "https" or url.hostname != "www.stats.gov.cn":
        raise ValueError("official NBS HTTPS source required")
    retrieved = datetime.fromisoformat(retrieved_at)
    if retrieved.tzinfo is None:
        raise ValueError("retrieved_at requires timezone")
    page = Tables()
    page.feed(raw.decode("utf-8-sig"))
    pub = page.published
    if pub is None:
        found = re.search(r"(20\d{2}/\d{2}/\d{2}\d{2}:\d{2})", page.text)
        if not found:
            raise ValueError("publication time missing")
        pub = found.group(1)
    pub = re.sub(r"\s+", "", pub)
    published = datetime.strptime(pub, "%Y/%m/%d%H:%M").replace(
        tzinfo=timezone(timedelta(hours=8))
    )
    if published > retrieved:
        raise ValueError("publication later than retrieval")
    candidates = []
    for context, rows in page.tables:
        content = "".join("".join(row) for row in rows)
        heading = re.search(
            r"表2[：:](20\d{2})年(\d{1,2})月70个大中城市二手住宅销售价格指数",
            context + content[:250],
        )
        if not heading or "上月=100" not in content:
            continue
        month = date(int(heading[1]), int(heading[2]), 1).strftime("%Y-%m")
        validate_header(rows)
        values = {}
        for row in rows:
            if len(row) != 8:
                continue
            for offset in (0, 4):
                city = row[offset]
                if city not in TRAIN_CITIES:
                    continue
                number = float(row[offset + 1])
                if not math.isfinite(number) or number <= 0 or city in values:
                    raise ValueError("invalid or duplicate city index")
                values[city] = number
        if set(values) != set(TRAIN_CITIES):
            raise ValueError("training-city coverage incomplete")
        if month >= published.strftime("%Y-%m"):
            raise ValueError("observation month must precede publication")
        candidates.append((month, values))
    if not candidates or any(item != candidates[0] for item in candidates):
        raise ValueError("missing or conflicting table 2")
    month, values = candidates[0]
    return {
        "kind": "city_trend_reference_only",
        "observation_month": month,
        "published_at": published.isoformat(),
        "retrieved_at": retrieved.isoformat(),
        "input_available_at": retrieved.isoformat(),
        "historical_vintage_verified": False,
        "source_url": source_url,
        "snapshot_sha256": sha256(raw).hexdigest(),
        "unit": "previous_month_equals_100",
        "geography": "city_urban_districts_not_counties",
        "training_cities_only": True,
        "city_indices": values,
        "community_price_labels": [],
        "market_predictions": [],
        "limitations": [
            "Not yuan/m2 or community truth",
            "No held-out city values exported",
            "Current snapshot may differ from original publication vintage",
            "Do not substitute missing months or chain nonconsecutive months",
            "NBS no-trade convention and base-year changes differ from Crow",
        ],
    }


def visible_asof(snapshot, origin):
    cutoff = datetime.fromisoformat(origin)
    if cutoff.tzinfo is None:
        raise ValueError("origin requires timezone")
    return datetime.fromisoformat(snapshot["input_available_at"]) <= cutoff


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    args = parser.parse_args()
    url = urlparse(args.url)
    if url.scheme != "https" or url.hostname != "www.stats.gov.cn":
        parser.error("official NBS HTTPS source required")
    with urlopen(args.url, timeout=30) as response:
        if (
            urlparse(response.url).hostname != "www.stats.gov.cn"
            or urlparse(response.url).scheme != "https"
        ):
            raise ValueError("unexpected redirect")
        raw = response.read(5_000_001)
    if len(raw) > 5_000_000:
        raise ValueError("page too large")
    report = parse_snapshot(raw, args.url, datetime.now(timezone.utc).isoformat())
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
