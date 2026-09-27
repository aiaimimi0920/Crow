from __future__ import annotations

import json
import logging
import re


from src.llm_openai_compatible import chat_with_glm
from src.llm_text_extraction import (
    _backfill_area_and_unit_price,
    _is_valid_china_coordinate,
    extract_area_from_text,
    extract_property_coordinates,
    fetch_description_data_text,
    filter_content,
)

logger = logging.getLogger(__name__)


AVM_RISK_SYSTEM_PROMPT = (
    "你是一个专业的真实房地产估价师与法拍房风控专家。你的任务是从法院复杂的拍卖公告、须知"
    "以及页面详情中，像侦探一样精准提取出房屋的核心属性与潜在风险（雷区）。你必须保持绝对"
    "的客观，如果文中没有提及某项信息，请将其对应的值设置为 null。"
)


AVM_RISK_PROMPT_RULES = [
    (
        "community_name",
        "请从地址/公告中提取后续可复用、可归并的稳定位置索引名，优先是小区、楼盘或院落名称；"
        "不要求官方名称，但同一小区或同一片房源应尽量输出同一个名字。"
        "不要包含城市、区县、道路门牌号、楼号、单元号、房号；"
        "如果只能定位到商圈、镇街或片区且没有稳定小区名，可输出该片区名；无法稳定判断则返回 null。",
    ),
    ("build_year", "房屋建成年份，提取纯数字（如 2010）。如果没写，请尝试根据周边楼盘或证号年份推测，无法确定则返回 null。"),
    ("total_floors", "这栋楼一共有多少层。"),
    ("floor_level", "该房产所在的楼层，请归一化为 [\"低区\", \"中区\", \"高区\", \"顶层\", \"底层\", \"独栋\"]。"),
    ("has_elevator", "是否带电梯。true/false。"),
    ("orientation", "房屋的主要朝向。归一化为 [\"南\", \"南北\", \"东\", \"西\", \"北\", \"未知\"]。"),
    ("land_right_type", "土地权利性质。如果写了“出让”返回\"出让\"，如果写了“划拨”返回\"划拨\"，否则返回\"未知\"。注意，划拨极其危险需要补交土地出让金。"),
    ("is_occupied", "房屋目前是否有人居住、占用、或者未腾空状态？如果是，返回 true，否则 false。"),
    ("has_long_lease", "公告中是否提到“带租约”、“设立了租赁权”等？如果是，返回 true。"),
    ("clear_delivery", "法院是否明确表示“负责清场”、“按现状交付且已腾空”？如果是返回 true。如果写着“买受人自行腾退”、“自行解决”、“法院不负责交付”，则务必返回 false！"),
    ("tax_burden", "历史欠费和交易税费是由谁承担？归一化为 [\"买受人承担全部\", \"各自承担\", \"未知\"]。当写明“标的物转让登记手续所涉及的一切税费及明确或不明确的欠费均由买受人承担”时为买受人承担全部。"),
    ("is_haunted", "公告是否提到“发生过非正常死亡”、“涉嫌刑事案”等凶宅特征？如果是，返回 true。"),
    ("housing_type", "这套房子的用途是什么？归一化为 [\"住宅\", \"别墅\", \"商业\", \"办公\", \"工业\", \"车位\", \"其他\"]。"),
    ("has_keys", "法院是否持有钥匙？是否能正常安排看样？如果是返回 true，如果写明“无钥匙”返回 false。"),
    ("property_fee_owed", "公告中是否提及存在（或可能存在）物业费、水费、电费欠缴？提到了就返回 true。"),
    ("special_school_tag", "公告中是否把“带学位”、“学区房”、“对口XX小学”作为卖点提及？如果是返回 true。"),
    ("evaluation_price", "法院给出的“评估价”或“市场价”是多少元？请输出元为单位的纯数字（例如原文是230万元，则输出 2300000）。如无则返回 null。"),
    ("layout", "房屋的户型结构。提取如“3室2厅1厨2卫”这样的格式。找不到则返回 null。"),
    ("is_restricted_purchase", "公告中是否明确标明该房产“受当地限购政策限制”或“需具备购房资格”？如果是真正的限购，返回 true；如果不限购或没提，返回 false。"),
    ("includes_parking", "此次拍卖的标的物，是否附带了真实的地下车位/车库一起拍卖？（注意：不是指小区内有公共停车位，而是这个拍品本身包含了车位产权或使用权）。如果是，返回 true，寻找不到直接证据返回 false。"),
    ("is_fractional_share", "拍卖的标的物是否为“部分产权”（例如：某某房屋 50% 的份额、二分之一产权）？如果是部分产权，请务必返回 true，否则返回 false。"),
    ("tax_is_company_owned", "标的物的原所有人（即被执行人）是否为一家“公司”、“企业法人”或者挂在企业名下？如果是，返回 true（意味着买受人需承担极高的土地增值税），如果是个人则返回 false。"),
    ("has_lease_before_mortgage", "公告中是否有明确表述如：“该租赁关系设立于抵押权之后”、“不能对抗抵押权”、“法院负责带租清场”？如果是这种其实可以强制赶走租客的“假长租”，必须精准识别并返回 true；如果是普通无法清场的租约，或没有租约，均返回 false。"),
]


AVM_RISK_PROMPT_OUTPUT_RULE = (
    "请务必仅返回一段合法的 JSON 对象，不要包含任何额外的多余说明文字或 Markdown 标记。"
    "JSON 的 key 必须与上述英文名完全一致。"
    "请额外输出 extraction_confidence(0~1)、evidence_span(字符串或字符串数组)、"
    "evidence_source(公告/须知/评估报告/页面主文)、extraction_version。"
)


def build_avm_risk_prompt(page_text_content):
    """Build AVM risk extraction prompt from independent rule constants."""
    from src.llm_evidence_prompt import EvidencePrompt
    rules_text = "\n".join(
        f"{idx}. `{field}`：{instruction}"
        for idx, (field, instruction) in enumerate(AVM_RISK_PROMPT_RULES, start=1)
    )
    return EvidencePrompt(f"""
# 系统 Prompt
{AVM_RISK_SYSTEM_PROMPT}

# 用户 Prompt
请仔细阅读以下法拍房网页的文本内容，帮我提取以下结构化字段。

提取规则：
{rules_text}

{AVM_RISK_PROMPT_OUTPUT_RULE}

""".strip(), page_text_content)


def _extract_avm_risk_features_raw(text, item_id=None, *, model=None):
    """Extract AVM risk features using the 23-rule structured prompt."""
    from src.llm_request_policy import MAX_INPUT_CHARACTERS

    page_text_content = (text or "").strip()
    if not page_text_content:
        return "{}"

    truncated_text = page_text_content[:MAX_INPUT_CHARACTERS]
    prompt = build_avm_risk_prompt(truncated_text)
    logger.debug(
        "Extracting AVM risk features (item_id=%s, text_len=%s, prompt_len=%s).",
        item_id,
        len(page_text_content),
        len(prompt),
    )
    return chat_with_glm(prompt, model=model) if model else chat_with_glm(prompt)


def extract_auction_data(html_content, item_id=None, *, model=None):
    """
    Extract structured auction data from HTML/Text content using AI.
    Applies filtering first.
    """
    # 0. Pre-Extraction of Critical Data (Area, Address)
    logger.debug("Pre-extracting critical data...")
    critical_text = ""
    trusted_url = None
    trusted_title = None
    coordinate_payload = extract_property_coordinates(html_content)
    area_fallback = None

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, 'html.parser')

        # 0.4 Extract Metadata (fapaifang-meta) - Trusted Source
        meta_div = soup.find(id="fapaifang-meta")
        if meta_div:
            url_meta = meta_div.find("meta", attrs={"name": "original_url"})
            if url_meta and url_meta.get("content"):
                trusted_url = url_meta["content"]
                critical_text += f"【已知元数据】\n原始链接: {trusted_url}\n\n"
            lat_meta = meta_div.find("meta", attrs={"name": "latitude"})
            lon_meta = meta_div.find("meta", attrs={"name": "longitude"})
            if lat_meta and lon_meta:
                try:
                    lat = float(lat_meta.get("content"))
                    lon = float(lon_meta.get("content"))
                    if _is_valid_china_coordinate(lat, lon):
                        coordinate_payload = {
                            "latitude": round(lat, 6),
                            "longitude": round(lon, 6),
                            "coordinate_evidence": "meta:fapaifang-meta",
                        }
                except (TypeError, ValueError):
                    pass

        if soup.title and soup.title.string:
            trusted_title = soup.title.string.strip()
            if trusted_title:
                critical_text += f"【已知标题】\n{trusted_title}\n\n"

        # 0.1 Extract Address (item-address class)
        # Note: Address is often split into multiple divs inside .item-address
        addr_div = soup.find(class_="item-address")
        if addr_div:
            # Join text with space to ensure "上海 上海市 黄浦区" + " 巨鹿路..."
            addr_text = addr_div.get_text(" ", strip=True)
            critical_text += f"【重要地点信息】\n{addr_text}\n\n"

        # 0.2 Extract Subject Description (J_desc id) - Provides Area
        # This contains the table with "建筑面积：105.08平方米"
        desc_div = soup.find(id="J_desc")
        if desc_div:
            # Get text but try to preserve some structure with newlines
            desc_text = desc_div.get_text("\n", strip=True)
            # Limit length of description just in case it's massive
            critical_text += f"【重要标的物描述】\n{desc_text[:20000]}\n\n"

        # 0.3 Extract Notice Detail (J_NoticeDetail id) - Provides Critical Area Info
        # As per user request, this div contains the "建筑面积" text reliably.
        notice_div = soup.find(id="J_NoticeDetail")
        if notice_div:
            # Extract text as single line, truncate at "竞买人条件"
            text_val = notice_div.get_text(separator="", strip=True)
            if "竞买人条件" in text_val:
                text_val = text_val.split("竞买人条件")[0]
            clean_notice = re.sub(r'\s+', '', text_val)
            critical_text += f"【重要竞买公告（含建筑面积）】\n{clean_notice}\n\n"
        else:
            logger.debug("J_NoticeDetail not found, skipping this part.")

        desc_async_text = fetch_description_data_text(html_content)
        if desc_async_text:
            area_fallback = extract_area_from_text(desc_async_text)
            critical_text += f"【异步标的物描述（含可能面积）】\n{desc_async_text[:20000]}\n\n"

    except Exception as e:
        logger.warning("Pre-extraction failed: %s", e)

    if coordinate_payload:
        critical_text += (
            "【已知坐标信息】\n"
            f"纬度: {coordinate_payload['latitude']}\n"
            f"经度: {coordinate_payload['longitude']}\n\n"
        )

    # 1. Filter Content
    logger.debug("Filtering content (len=%s)...", len(html_content))
    filtered_text = filter_content(html_content)
    logger.debug("Filtered content (len=%s). Preparing prompt...", len(filtered_text))

    # Limit length to avoid context overflow, though filtered text should be smaller
    from src.llm_request_policy import MAX_INPUT_CHARACTERS

    truncated_text = filtered_text[:MAX_INPUT_CHARACTERS]

    # 2. Construct Prompt (Strict User Rules)
    prompt = f"""
# Role
你是一个专业的房产拍卖数据清洗专家。

# Task
我将提供一条原始的房产数据。你需要根据以下规则，对其进行清洗、提取、计算和标准化，最终输出一个符合指定结构的 JSON 对象。

# Rules

## 1. 数据清洗与类型转换
- **数值清洗**：所有价格、面积、ID、人数等字段，必须去除人民币符号（¥）、逗号（,）和引号。输出应为纯数字（Number 类型）。
- **布尔值转换**：`是否成交` 字段，如果原始数据 `status` 为 "done" 或类似成交状态，输出布尔值 `true`，否则输出 `false`。
- **面积清洗**：`建筑面积` 字段需去除“平方米”、“㎡”等单位，仅保留数字（保留两位小数）。注意：此处的建筑面积为房产证上的建筑面积，非套内建筑面积。

## 2. 字段映射与提取
请从原始数据中提取并映射到以下字段（注意：不要输出原始字段名，只输出新字段名）：
- `id` -> `唯一id`
- `market_price` -> `市场评估价`
- `initialPrice` -> `起拍价格`
- `deposit` 或文本中的 **保证金** -> `保证金`
- `deal_price`、`currentPrice` 或文本中的 **`拍下价`** -> `成交价格` (注意：不要输出 `成交价` 字段，仅保留 `成交价格`)
- `startTime` 或文本中的 **开拍时间** -> `开拍时间`
- `auction_date` -> `交易时间`
- `url` -> `原始网站`
- `title` -> `标题`
- `status` -> `是否成交`
- `applyCount` -> `竞拍人数`
- `bidCount` -> `出价次数`
- `bidUserNumber` 或明确描述“共有X人出价” -> `出价人数`
- `watchCount` / `pv` / 文本中的围观数 -> `围观人数`
- `remindCount` / 文本中的提醒数 -> `提醒人数`
- `viewCount` / 文本中的浏览数 -> `浏览次数`
- `item_address` -> `地点`

## 3. 智能信息补充
- **地点/完整地址**：必须优先输出真实地址文本。如果页面没有明确地址，不要为了凑字段把 `title` 原样抄进 `地点`；此时 `地点` 和 `完整地址` 可以为 null。
- **所属小区/稳定位置索引名**：必须基于 `item_address`、`地点`、`完整地址` 或 `title` 中的地址信息，输出用于后续归并、索引同片房源的稳定位置索引名。不要求它是官方名称，但同一小区或同一片房源应尽量输出同一个名字；优先输出小区、楼盘或院落名称，也可以在无法稳定识别小区时输出商圈、镇街或片区名。不要输出城市、区县、道路门牌号、楼号、单元号、房号。如果确实无法形成稳定索引名，填入 null。
- **地理位置解析**：根据 `地点`、`完整地址` 或 `title`，解析并填充 `省份`、`城市`、`区`。
- **最靠近商圈**：根据地址信息，推断该房产最靠近的知名商圈或板块名称。

## 4. 数据计算
- **单价计算**：公式为 `单价 = 成交价格 / 建筑面积`。结果保留两位小数。（注意：成交价格即为上面提取的拍下价）
- **缺失面积处理**：如果 `building_area` 为空，请优先从【重要标的物描述】或【重要竞买公告（含建筑面积）】中寻找数字线索。如果确实无法获取，请将 `建筑面积` 设为 null，`单价` 设为 0。
- **产权份额处理**：如果拍卖标的涉及部分产权（如"1/2产权"、"二分之一所有权"、"50%份额"、"1/12产权份额"等），请同时输出：
  - `产权建筑面积` = 原始产权建筑面积
  - `产权份额比例` = 0~1 浮点值
  - `建筑面积` = 最终有效可交易面积（例如 120 平米的 1/2 产权，则输出 60）
- **法务上下文**：如果页面中出现执行法院、案号，请尽量提取到 `法院名称` 和 `案号`。

## 5. 输出格式要求
- 仅输出最终的 JSON 对象，不要包含任何解释性文字、Markdown 代码块标记（如 ```json）或其他多余内容。
- 字段顺序必须严格遵循下方的“输出模板”顺序。

# Output Template
请严格按照以下 JSON 结构和顺序输出数据：

{{
    "id": [Number],
    "市场评估价": [Number],
    "起拍价格": [Number],
    "成交价格": [Number],
    "保证金": [Number],
    "开拍时间": [String],
    "交易时间": [String],
    "原始网站": [String],
    "标题": [String],
    "是否成交": [Boolean],
    "竞拍人数": [Number],
    "出价次数": [Number],
    "出价人数": [Number],
    "围观人数": [Number],
    "提醒人数": [Number],
    "浏览次数": [Number],
    "地点": [String],
    "完整地址": [String],
    "所属小区": [String],
    "省份": [String],
    "城市": [String],
    "区": [String],
    "最靠近商圈": [String],
    "建筑面积": [Number],
    "产权建筑面积": [Number],
    "产权份额比例": [Number],
    "法院名称": [String],
    "案号": [String],
    "单价": [Number],
    "is_processed": true
}}

    """
    from src.llm_evidence_prompt import EvidencePrompt

    prompt = EvidencePrompt(prompt, critical_text + "\n---\n" + truncated_text)

    # Debug: Save prompt for inspection
    # Debug: Save prompt for inspection (DISABLED by user request)
    # try:
    #     filename = f"item_{item_id}_ai_prompt.txt" if item_id else "test_output.txt"
    #     with open(filename, "w", encoding="utf-8") as f:
    #         f.write(prompt)
    # except: pass

    ai_response = chat_with_glm(prompt, model=model) if model else chat_with_glm(prompt)

    try:
        data = json.loads(ai_response)
        if trusted_url:
            logger.debug("Overwriting AI URL with trusted metadata: %s", trusted_url)
            data["原始网站"] = trusted_url
        if trusted_title and not data.get("标题"):
            data["标题"] = trusted_title
        if trusted_title and not data.get("title"):
            data["title"] = trusted_title
            data.setdefault("source_title", trusted_title)
        elif data.get("标题") and not data.get("title"):
            data["title"] = data.get("标题")
            data.setdefault("source_title", data.get("标题"))
        if data.get("完整地址") and not data.get("地点"):
            data["地点"] = data.get("完整地址")
        if data.get("地点") and not data.get("完整地址"):
            data["完整地址"] = data.get("地点")
        _backfill_area_and_unit_price(data, area_fallback)
        if coordinate_payload:
            data.setdefault("纬度", coordinate_payload["latitude"])
            data.setdefault("经度", coordinate_payload["longitude"])
            data.setdefault("latitude", coordinate_payload["latitude"])
            data.setdefault("longitude", coordinate_payload["longitude"])
            data.setdefault("coordinate_source", coordinate_payload.get("coordinate_evidence", "html"))
        return json.dumps(data, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.warning("Failed to normalize extracted JSON: %s. Returning original response.", e)
        return ai_response


__all__ = ['AVM_RISK_SYSTEM_PROMPT', 'AVM_RISK_PROMPT_RULES', 'AVM_RISK_PROMPT_OUTPUT_RULE', 'build_avm_risk_prompt', '_extract_avm_risk_features_raw', 'extract_auction_data']
