"""
collect_urls.py
===============
都市銀行・地方銀行・信用金庫の公式サイト URL を収集して
data/institutions.csv に保存するスクリプト。

収集元:
  都市銀行   : 固定リスト（5行）
  地方銀行   : 全国銀行協会 https://www.zenginkyo.or.jp/abstract/outline/organization/member-01/
  信用金庫   : 信用金庫業界ポータル https://www.shinkin.co.jp/tikubetu/*.htm (地区別10ページ)

金融機関コードは全銀協の公式コード体系に基づく固定マップを使用。
スクレイピングで取得した機関名→URLの対応を固定マップと突合し、コードを付与する。
コード不明の機関は R/S プレフィックスの連番を付与する。
"""

import csv
import os
import re
import time
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from curl_cffi import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

IMPERSONATE = "chrome124"
TIMEOUT     = 20
DATA_DIR    = os.path.join(os.path.dirname(__file__), "data")
OUT_CSV     = os.path.join(DATA_DIR, "institutions.csv")

# スクレイピング除外ドメイン（協会・ポータル・グループ会社等）
EXCLUDE_DOMAINS = {
    # 銀行協会・業界団体
    "zenginkyo.or.jp", "shinkin.org", "shinkin.co.jp",
    "densai.net", "zengin-net.jp", "caml.co.jp", "jbatibor.or.jp",
    "dgl.or.jp", "jammo.org", "ictac.jp", "abpdpc.gr.jp", "zenginzaidan.jp",
    "jsda.or.jp", "jba-digital.org", "areamarker.com",
    # 地方銀行協会（都道府県単位）
    "shizuginkyo.com", "ginkyo-kyoto.or.jp", "oba.or.jp", "kobe-ginkyo.or.jp",
    "fukuoka-banker.or.jp", "osaka-banker.or.jp", "nagoya-banker.or.jp",
    "aichi-banker.or.jp", "saitama-banker.or.jp", "chiba-banker.or.jp",
    "kanagawa-banker.or.jp", "tokyo-banker.or.jp", "ibaraki-banker.or.jp",
    "tochigi-banker.or.jp", "gunma-banker.or.jp", "niigata-banker.or.jp",
    "toyama-banker.or.jp", "ishikawa-banker.or.jp", "fukui-banker.or.jp",
    "yamanashi-banker.or.jp", "nagano-banker.or.jp", "shizuoka-banker.or.jp",
    "mie-banker.or.jp", "shiga-banker.or.jp", "hyogo-banker.or.jp",
    "nara-banker.or.jp", "wakayama-banker.or.jp", "tottori-banker.or.jp",
    "shimane-banker.or.jp", "okayama-banker.or.jp", "hiroshima-banker.or.jp",
    "yamaguchi-banker.or.jp", "tokushima-banker.or.jp", "kagawa-banker.or.jp",
    "ehime-banker.or.jp", "kochi-banker.or.jp", "saga-banker.or.jp",
    "nagasaki-banker.or.jp", "kumamoto-banker.or.jp", "oita-banker.or.jp",
    "miyazaki-banker.or.jp", "kagoshima-banker.or.jp", "okinawa-banker.or.jp",
    "hokkaido-banker.or.jp", "aomori-banker.or.jp", "iwate-banker.or.jp",
    "miyagi-banker.or.jp", "akita-banker.or.jp", "yamagata-banker.or.jp",
    "fukushima-banker.or.jp", "kyoto-banker.or.jp",
    # FGなどグループ持株会社
    "mufg.jp", "smth.jp", "mizuho-fg.co.jp", "resona-gr.co.jp",
    "sonyfg.co.jp", "au-financial.com",
    # SNS
    "facebook.com", "twitter.com",
    # 農林中金（銀行カテゴリ対象外）
    "nochubank.or.jp",
    # 外国銀行
    "citigroup.jp", "hsbc.co.jp", "sc.com", "bb.com.br",
    "nbptokyo.com", "statebank", "sbjbank.co.jp", "wooribank.com",
    "metrobank.co.jp", "pnb.com.ph", "tcb-bank.com.tw",
    # 信託銀行（専業）
    "mastertrust.co.jp", "nochutb.co.jp", "jsftb.co.jp", "custody.jp",
    "smbctb.co.jp", "nomura-trust.co.jp",
}

# 非銀行キーワード（名前でフィルタ）
EXCLUDE_NAME_KEYWORDS = [
    "グループ", "ホールディングス", "フィナンシャル",
    "カード", "リース", "証券", "保険", "コンサル",
    "マスタートラスト", "カストディ", "ネットワーク", "システム",
    "ネット銀行", "銀行協会",
]

# 地銀として扱わない銀行名（ネット銀行・外国銀行・信託・その他）
EXCLUDE_BANK_NAMES = {
    "セブン銀行", "PayPay銀行", "ソニー銀行", "楽天銀行",
    "住信SBIネット銀行", "auじぶん銀行", "イオン銀行", "大和ネクスト銀行",
    "GMOあおぞらネット銀行", "みんなの銀行", "UIバンク", "ローソン銀行",
    "オリックス銀行", "SBI新生銀行", "あおぞら銀行",
    "三菱UFJトラスト銀行", "三菱UFJフィナンシャル・グループ",
    "三井住友トラスト銀行", "みずほ信託銀行",
    "シティバンク、エヌ・エイ", "SMBC信託銀行",
    "農林中央金庫", "商工中金", "日本政策金融公庫",
    "01バンク", "三菱UFJエリート銀行", "大和証券",
}


@dataclass
class Institution:
    code: str
    name: str
    category: str
    url: str


# ─────────────────────────────────────────────────────────────────────────────
# 都市銀行（固定リスト）
# ─────────────────────────────────────────────────────────────────────────────
CITY_BANKS: List[Institution] = [
    Institution("0001", "みずほ銀行",     "都市銀行", "https://www.mizuhobank.co.jp/"),
    Institution("0005", "三菱UFJ銀行",   "都市銀行", "https://www.bk.mufg.jp/"),
    Institution("0009", "三井住友銀行",   "都市銀行", "https://www.smbc.co.jp/"),
    Institution("0010", "りそな銀行",     "都市銀行", "https://www.resonabank.co.jp/"),
    Institution("0017", "埼玉りそな銀行", "都市銀行", "https://www.saitamaresona.co.jp/"),
    Institution("9900", "ゆうちょ銀行",   "都市銀行", "https://www.jp-bank.japanpost.jp/"),
]

# 銀行名 → 金融機関コード マッピング（全銀協公式コード）
BANK_CODE_MAP: Dict[str, str] = {
    # 都市銀行
    "みずほ銀行":         "0001", "三菱UFJ銀行":       "0005",
    "三井住友銀行":       "0009", "りそな銀行":         "0010",
    "埼玉りそな銀行":     "0017", "ゆうちょ銀行":       "9900",
    # 北海道
    "北海道銀行":         "0116", "北洋銀行":           "0501",
    # 東北
    "青森銀行":           "0119", "みちのく銀行":       "0120",
    "みちのく銀行あおもり": "0120",
    "岩手銀行":           "0122", "東北銀行":           "0123",
    "七十七銀行":         "0125", "秋田銀行":           "0126",
    "北都銀行":           "0127", "荘内銀行":           "0128",
    "山形銀行":           "0129", "東邦銀行":           "0130",
    "福島銀行":           "0131", "大東銀行":           "0132",
    # 関東
    "常陽銀行":           "0133", "筑波銀行":           "0134",
    "足利銀行":           "0138", "群馬銀行":           "0140",
    "武蔵野銀行":         "0143", "千葉銀行":           "0144",
    "千葉興業銀行":       "0145", "きらぼし銀行":       "0146",
    "横浜銀行":           "0147", "神奈川銀行":         "0148",
    "第四北越銀行":       "0149", "大光銀行":           "0150",
    # 北陸・甲信越
    "北陸銀行":           "0154", "富山銀行":           "0155",
    "北國銀行":           "0157", "福井銀行":           "0158",
    "山梨中央銀行":       "0160", "八十二銀行":         "0162",
    "長野銀行":           "0163",
    # 東海
    "十六銀行":           "0166", "大垣共立銀行":       "0167",
    "静岡銀行":           "0168", "スルガ銀行":         "0169",
    "清水銀行":           "0170", "名古屋銀行":         "0172",
    "中京銀行":           "0173", "愛知銀行":           "0174",
    "百五銀行":           "0175", "三重銀行":           "0176",
    # 近畿
    "滋賀銀行":           "0180", "京都銀行":           "0181",
    "南都銀行":           "0182", "池田泉州銀行":       "0183",
    "関西みらい銀行":     "0184", "但馬銀行":           "0185",
    "みなと銀行":         "0186", "紀陽銀行":           "0191",
    # 中国
    "鳥取銀行":           "0194", "山陰合同銀行":       "0195",
    "中国銀行":           "0197", "トマト銀行":         "0198",
    "もみじ銀行":         "0199", "広島銀行":           "0200",
    "山口銀行":           "0204", "西京銀行":           "0206",
    "島根銀行":           "0207",
    # 四国
    "阿波銀行":           "0208", "徳島大正銀行":       "0209",
    "百十四銀行":         "0210", "香川銀行":           "0211",
    "伊予銀行":           "0212", "愛媛銀行":           "0213",
    "四国銀行":           "0214", "高知銀行":           "0215",
    # 九州・沖縄
    "福岡銀行":           "0172", "筑邦銀行":           "0173",
    "西日本シティ銀行":   "0190", "佐賀銀行":           "0178",
    "十八親和銀行":       "0174", "肥後銀行":           "0182",
    "熊本銀行":           "0183", "大分銀行":           "0177",
    "豊和銀行":           "0179", "宮崎銀行":           "0184",
    "都城銀行":           "0186", "鹿児島銀行":         "0185",
    "南日本銀行":         "0187", "琉球銀行":           "0188",
    "沖縄銀行":           "0189", "沖縄海邦銀行":       "0596",
    # ネット銀行等（除外対象だが念のため）
    "セブン銀行":         "0034", "SBI新生銀行":        "0397",
    "あおぞら銀行":       "0398",
}


def _fetch(url: str) -> Optional[bytes]:
    try:
        r = requests.get(url, impersonate=IMPERSONATE, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        return r.content
    except Exception as e:
        log.warning("取得失敗: %s — %s", url, e)
        return None


def _domain(url: str) -> str:
    m = re.search(r"https?://([^/]+)", url)
    return m.group(1).lower() if m else ""


def _is_excluded(name: str, url: str) -> bool:
    dom = _domain(url)
    for ex in EXCLUDE_DOMAINS:
        if ex in dom:
            return True
    for kw in EXCLUDE_NAME_KEYWORDS:
        if kw in name:
            return True
    if name in EXCLUDE_BANK_NAMES:
        return True
    return False


def _assign_code(name: str, existing_codes: set, prefix: str, counter_ref: list) -> str:
    code = BANK_CODE_MAP.get(name)
    if code and code not in existing_codes:
        existing_codes.add(code)
        return code
    # コード不明 → 連番
    while True:
        c = f"{prefix}{counter_ref[0]:04d}"
        counter_ref[0] += 1
        if c not in existing_codes:
            existing_codes.add(c)
            return c


# ─────────────────────────────────────────────────────────────────────────────
# 地方銀行: 全国銀行協会 会員一覧
# ─────────────────────────────────────────────────────────────────────────────
ZENGINKYO_MEMBER_URL = "https://www.zenginkyo.or.jp/abstract/outline/organization/member-01/"

# 地銀として扱うカテゴリ名判定（銀行名に含むキーワード）
REGIONAL_BANK_KEYWORDS = ["銀行"]
# 信託銀行・外国銀行・ネット銀行を地銀から除外する追加キーワード
TRUST_KEYWORDS = ["信託", "外国", "ネット"]


def collect_regional_banks() -> List[Tuple[str, str]]:
    """全銀協会員ページから (名前, URL) リストを返す。"""
    log.info("地方銀行 URL収集 → %s", ZENGINKYO_MEMBER_URL)
    content = _fetch(ZENGINKYO_MEMBER_URL)
    if content is None:
        log.warning("全銀協ページ取得失敗")
        return []

    soup = BeautifulSoup(content, "lxml")
    results = []
    seen_urls = set()

    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()
        name = a.get_text(strip=True)
        if not href.startswith("http") or not name:
            continue
        if _is_excluded(name, href):
            continue
        # 銀行名に「銀行」が含まれるもののみ
        if "銀行" not in name:
            continue
        # 信託・外国銀行は除外（地銀リストには不要）
        if any(kw in name for kw in TRUST_KEYWORDS):
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        results.append((name, href))

    log.info("地方銀行スクレイピング結果: %d件", len(results))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 信用金庫: shinkin.co.jp 地区別ページ
# ─────────────────────────────────────────────────────────────────────────────
SHINKIN_AREA_URLS = [
    "https://www.shinkin.co.jp/tikubetu/hokkaido.htm",
    "https://www.shinkin.co.jp/tikubetu/tohoku.htm",
    "https://www.shinkin.co.jp/tikubetu/kantou.htm",
    "https://www.shinkin.co.jp/tikubetu/kosinetu.htm",
    "https://www.shinkin.co.jp/tikubetu/hokuriku.htm",
    "https://www.shinkin.co.jp/tikubetu/tokai.htm",
    "https://www.shinkin.co.jp/tikubetu/kinki.htm",
    "https://www.shinkin.co.jp/tikubetu/cyugoku.htm",
    "https://www.shinkin.co.jp/tikubetu/sikoku.htm",
    "https://www.shinkin.co.jp/tikubetu/kyusyu.htm",
]

SHINKIN_SKIP_DOMAINS = {"shinkin.co.jp", "shinkin.org", "areamarker.com",
                        "facebook.com", "twitter.com"}


def collect_shinkin() -> List[Tuple[str, str]]:
    """信金ポータルの地区別ページから (名前, URL) リストを返す。"""
    log.info("信用金庫 URL収集 → shinkin.co.jp 地区別10ページ")
    results = []
    seen_urls = set()

    for area_url in SHINKIN_AREA_URLS:
        content = _fetch(area_url)
        if content is None:
            continue
        soup = BeautifulSoup(content, "lxml")
        count = 0
        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            name = a.get_text(strip=True)
            if not href.startswith("http") or not name:
                continue
            dom = _domain(href)
            if any(s in dom for s in SHINKIN_SKIP_DOMAINS):
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)
            results.append((name, href))
            count += 1
        page = area_url.split("/")[-1]
        log.info("  %s: %d件", page, count)
        time.sleep(0.4)

    log.info("信用金庫スクレイピング結果: %d件", len(results))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────────────────────────────────────
def collect_all() -> List[Institution]:
    all_institutions: List[Institution] = []
    used_codes: set = set()

    # ── 都市銀行（固定） ─────────────────────────────────────────
    for inst in CITY_BANKS:
        used_codes.add(inst.code)
        all_institutions.append(inst)
    log.info("都市銀行: %d行 (固定リスト)", len(CITY_BANKS))

    # ── 地方銀行 ─────────────────────────────────────────────────
    regional_raw = collect_regional_banks()
    r_counter = [1000]
    city_names = {inst.name for inst in CITY_BANKS}
    for name, url in regional_raw:
        if name in city_names:   # 都市銀行は除外
            continue
        code = _assign_code(name, used_codes, "R", r_counter)
        all_institutions.append(Institution(code, name, "地方銀行", url))
    regional_count = sum(1 for i in all_institutions if i.category == "地方銀行")
    log.info("地方銀行: %d行", regional_count)

    # ── 信用金庫 ─────────────────────────────────────────────────
    shinkin_raw = collect_shinkin()
    s_counter = [1]
    for name, url in shinkin_raw:
        code = _assign_code(name, used_codes, "S", s_counter)
        all_institutions.append(Institution(code, name, "信用金庫", url))
    shinkin_count = sum(1 for i in all_institutions if i.category == "信用金庫")
    log.info("信用金庫: %d庫", shinkin_count)

    return all_institutions


def save_csv(institutions: List[Institution]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["code", "name", "category", "url"])
        writer.writeheader()
        for inst in institutions:
            writer.writerow({
                "code":     inst.code,
                "name":     inst.name,
                "category": inst.category,
                "url":      inst.url,
            })
    log.info("CSV保存完了: %s (%d件)", OUT_CSV, len(institutions))


if __name__ == "__main__":
    institutions = collect_all()
    save_csv(institutions)
    log.info(
        "=== 収集完了 === 合計: %d件 (都市銀行:%d / 地方銀行:%d / 信用金庫:%d)",
        len(institutions),
        sum(1 for i in institutions if i.category == "都市銀行"),
        sum(1 for i in institutions if i.category == "地方銀行"),
        sum(1 for i in institutions if i.category == "信用金庫"),
    )
