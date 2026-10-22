"""
scrape_notices.py
=================
status_results.csv で UP の機関のトップページを解析し、
サービス停止・障害・メンテナンス関連のお知らせを抽出して service_notices.csv に保存する。
"""

import csv
import os
import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from curl_cffi import requests
import chardet
from bs4 import BeautifulSoup, Tag

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# curl_cffi は impersonate で TLS fingerprint を指定する（UA ヘッダーは不要）
IMPERSONATE  = "chrome124"
TIMEOUT_SEC  = 15
MAX_WORKERS  = 10   # スクレイピングは死活監視より控えめな並列数
MAX_ITEMS   = 30   # 1機関から取得する最大お知らせ件数

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
IN_CSV   = os.path.join(DATA_DIR, "status_results.csv")
OUT_CSV  = os.path.join(DATA_DIR, "service_notices.csv")

# サービス停止関連キーワード
STOP_KEYWORDS = [
    "サービス停止", "サービスを停止", "一時停止", "停止いたします", "停止しております",
    "メンテナンス", "メンテナンス作業", "定期メンテナンス",
    "障害", "システム障害", "障害発生", "障害が発生",
    "振込停止", "振込みが", "ご利用できません", "ご利用いただけません",
    "ATM停止", "ATMが利用", "ATMをご利用",
    "休止", "休止いたします", "休止中", "サービス休止",
    "不具合", "システム不具合",
    "ネットバンキング停止", "インターネットバンキング停止",
    "緊急", "緊急メンテナンス",
]

# ニュースリスト候補セレクター（優先度順）
NEWS_SELECTORS = [
    # 明示的なニュース系クラス
    "li.p-news__item", "li.p-news__item--release",
    "li.news-list__item", "li.o-news-list__item", "li.o-newsList__item",
    "li.c-list-news__list", "li.c_newslist_item", "li.js_newslist_item",
    "li.newsList_item", "li.cmsData", "li.news-item",
    "li.item", "li[class*=news]", "li[class*=News]",
    # div/article 系
    "article.news_article", "article.home-news__article", "article[class*=news]",
    "div.news-content", "div.news_outer", "div.newsArea_list_wrap",
    "div.modNewsListLinkBlock", "div.news__mtabs_item", "div.home-info__item",
    "div.p-announce__item", "div.p-notice__item", "div.p-top_info_box li",
    "div.sec_topics li", "div.news_list li", "div.top_news_box li",
    "div.news-wrap", "div.news_box li", "div.newsLinkBlock",
    # ID 系
    "#panelTopics01 li", "#panelTopics02 li",
    "#idInfoArea li", "#infoArea li",
    "#top_news li", "#newsBlock li", "#homeNews li",
    "#TP_news_alert li", "#notice li", "#topics li",
    "#top_corporate_notice li", "#top_corporate_release li",
    # 汎用フォールバック
    ".news-list li", ".newslist li", ".newsList li", ".topics li",
    "ul[class*=news] li", "ul[class*=News] li",
    ".information li", ".info-list li",
]


def _decode_response(content: bytes, content_type: str = "") -> str:
    """bytes を文字コード自動検出して str に変換する。"""
    # 1. Content-Type から charset を取得
    ct_match = re.search(r"charset=([\w\-]+)", content_type, re.IGNORECASE)
    charset = ct_match.group(1) if ct_match else ""

    # 2. HTML 先頭 4KB から <meta charset> を確認
    if not charset:
        head = content[:4096]
        m = re.search(rb'charset=["\']?([\w\-]+)', head, re.IGNORECASE)
        if m:
            charset = m.group(1).decode("ascii", errors="ignore")

    # 3. chardet でフォールバック
    if not charset:
        detected = chardet.detect(content[:8192])
        charset = detected.get("encoding") or "utf-8"

    # Shift_JIS 正規化
    enc_lower = charset.lower().replace("-", "").replace("_", "")
    if enc_lower in ("shiftjis", "sjis", "cp932", "windows31j", "x-sjis"):
        charset = "cp932"
    elif enc_lower in ("eucjp", "eucjpms", "eucjpwin"):
        charset = "euc-jp"

    try:
        return content.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return content.decode("utf-8", errors="replace")


def _parse_date(text: str) -> Optional[str]:
    """テキストから日付文字列を抽出する。"""
    m = re.search(r"\d{4}[.\-\/年]\d{1,2}[.\-\/月]\d{1,2}", text)
    return m.group(0) if m else None


def _make_absolute(href: str, base_url: str) -> str:
    """相対URLを絶対URLに変換する。"""
    if not href or href.startswith("javascript"):
        return ""
    if href.startswith("http"):
        return href
    try:
        from urllib.parse import urljoin
        return urljoin(base_url, href)
    except Exception:
        return ""


def _contains_stop_keyword(text: str) -> bool:
    """テキストにサービス停止関連キーワードが含まれているか判定する。"""
    return any(kw in text for kw in STOP_KEYWORDS)


def _scrape_notices_from_html(
    html: str, url: str
) -> List[Dict]:
    """HTML から停止関連お知らせを抽出して list of dict を返す。"""
    soup = BeautifulSoup(html, "lxml")
    notices = []
    seen_texts = set()

    for sel in NEWS_SELECTORS:
        try:
            elements = soup.select(sel)
        except Exception:
            continue

        for i, el in enumerate(elements):
            if i >= MAX_ITEMS:
                break

            text = el.get_text(separator=" ", strip=True)
            text = re.sub(r"\s+", " ", text).strip()
            if not text or len(text) < 5:
                continue
            if text in seen_texts:
                continue

            if not _contains_stop_keyword(text):
                continue

            seen_texts.add(text)
            a_tag = el.find("a")
            href = ""
            if isinstance(a_tag, Tag):
                href = _make_absolute(a_tag.get("href", ""), url)

            date_str = _parse_date(text)

            notices.append({
                "date":  date_str or "",
                "title": text[:200],  # 長すぎる場合はカット
                "link":  href,
            })

        if notices:
            break  # 最初にヒットしたセレクターで終了

    return notices


def fetch_and_scrape(row: Dict) -> Tuple[Dict, List[Dict]]:
    """1機関のページを取得してお知らせを抽出する。"""
    url = row.get("url", "").strip()
    if not url:
        return row, []

    try:
        resp = requests.get(
            url,
            impersonate=IMPERSONATE,
            timeout=TIMEOUT_SEC,
            allow_redirects=True,
        )
        ct = resp.headers.get("content-type", "")
        html = _decode_response(resp.content, ct)
        notices = _scrape_notices_from_html(html, url)
        return row, notices
    except Exception as e:
        log.debug("スクレイピング失敗 [%s] %s: %s", row.get("name", ""), url, e)
        return row, []


def load_up_institutions() -> List[Dict]:
    if not os.path.exists(IN_CSV):
        raise FileNotFoundError(
            f"status_results.csv が見つかりません: {IN_CSV}\n"
            "先に check_status.py を実行してください。"
        )
    with open(IN_CSV, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    up_rows = [r for r in rows if r.get("status") == "UP"]
    log.info("UP機関数: %d件 / 合計: %d件", len(up_rows), len(rows))
    return up_rows


def scrape_all(institutions: List[Dict]) -> List[Dict]:
    all_notices = []
    total = len(institutions)
    done = 0

    log.info("サービス停止情報スクレイピング開始: %d件", total)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_and_scrape, row): row for row in institutions}
        for future in as_completed(futures):
            row, notices = future.result()
            done += 1

            for n in notices:
                all_notices.append({
                    "code":     row.get("code", ""),
                    "name":     row.get("name", ""),
                    "category": row.get("category", ""),
                    "url":      row.get("url", ""),
                    "date":     n["date"],
                    "title":    n["title"],
                    "link":     n["link"],
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                })

            if notices:
                log.info(
                    "  ✓ %s: %d件のお知らせ検出",
                    row.get("name", ""), len(notices),
                )

            if done % 20 == 0 or done == total:
                log.info("  進捗: %d/%d件  停止情報検出機関数: %d",
                         done, total,
                         len(set(n["name"] for n in all_notices)))

    return all_notices


def save_notices(notices: List[Dict]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    fieldnames = ["code", "name", "category", "url", "date", "title", "link", "scraped_at"]
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(notices)
    log.info("停止情報保存完了: %s (%d件)", OUT_CSV, len(notices))


if __name__ == "__main__":
    institutions = load_up_institutions()
    notices = scrape_all(institutions)
    save_notices(notices)

    if notices:
        log.info("=== サービス停止情報 検出一覧 ===")
        for n in notices:
            log.info("  [%s] %s — %s", n["category"], n["name"], n["title"][:60])
    else:
        log.info("サービス停止関連のお知らせは検出されませんでした。")
