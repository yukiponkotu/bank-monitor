"""
check_status.py
===============
institutions.csv に記載された全機関の URL に対して HTTP GET を行い、
HTTP ステータス・レスポンスタイム・エラーを記録して status_results.csv に保存する。

分類:
  UP          : HTTP 200 系
  DOWN        : HTTP 400 / 500 系（Akamai 等 Bot ブロック含む）
  UNREACHABLE : タイムアウト・接続エラー・SSL エラー等

curl_cffi を使い Chrome の TLS fingerprint を偽装することで
Akamai Bot Manager 等による 403 ブロックを回避する。
"""

import csv
import os
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, List

from curl_cffi import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# curl_cffi は impersonate で TLS fingerprint を指定する（UA ヘッダーは不要）
IMPERSONATE  = "chrome124"
TIMEOUT_SEC  = 15
MAX_WORKERS  = 20

DATA_DIR    = os.path.join(os.path.dirname(__file__), "data")
IN_CSV      = os.path.join(DATA_DIR, "institutions.csv")
OUT_CSV     = os.path.join(DATA_DIR, "status_results.csv")


def _classify(status_code: int) -> str:
    if 200 <= status_code < 400:
        return "UP"
    return "DOWN"


def check_one(row: Dict) -> Dict:
    """1機関の死活確認を行い結果 dict を返す。"""
    url = row.get("url", "").strip()
    start = time.monotonic()
    result = {
        "code":             row.get("code", ""),
        "name":             row.get("name", ""),
        "category":         row.get("category", ""),
        "url":              url,
        "http_status":      None,
        "response_time_ms": None,
        "status":           "UNREACHABLE",
        "error":            "",
        "checked_at":       datetime.now(timezone.utc).isoformat(),
    }

    if not url:
        result["error"] = "URL未設定"
        return result

    try:
        resp = requests.get(
            url,
            impersonate=IMPERSONATE,
            timeout=TIMEOUT_SEC,
            allow_redirects=True,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        result["http_status"]      = resp.status_code
        result["response_time_ms"] = elapsed_ms
        result["status"]           = _classify(resp.status_code)
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        result["response_time_ms"] = elapsed_ms
        err_str = str(e)
        # タイムアウト判定
        if "timed out" in err_str.lower() or "timeout" in err_str.lower():
            result["error"] = "Timeout"
        # DNS 解決失敗
        elif "resolve" in err_str.lower() or "getaddrinfo" in err_str.lower():
            result["error"] = f"DNS解決失敗: {err_str}"
        # 接続リセット
        elif "reset" in err_str.lower() or "connection" in err_str.lower():
            result["error"] = f"接続エラー: {err_str}"
        else:
            result["error"] = err_str

    return result


def load_institutions() -> List[Dict]:
    if not os.path.exists(IN_CSV):
        raise FileNotFoundError(
            f"institutions.csv が見つかりません: {IN_CSV}\n"
            "先に collect_urls.py を実行してください。"
        )
    with open(IN_CSV, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def check_all(institutions: List[Dict]) -> List[Dict]:
    results = []
    total = len(institutions)
    done = 0

    log.info("死活監視開始: %d件 (並列数=%d, タイムアウト=%d秒)", total, MAX_WORKERS, TIMEOUT_SEC)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(check_one, row): row for row in institutions}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            done += 1
            if done % 20 == 0 or done == total:
                up   = sum(1 for r in results if r["status"] == "UP")
                down = sum(1 for r in results if r["status"] == "DOWN")
                unrch = sum(1 for r in results if r["status"] == "UNREACHABLE")
                log.info(
                    "  進捗: %d/%d件  UP:%d / DOWN:%d / UNREACHABLE:%d",
                    done, total, up, down, unrch,
                )

    # URL順でソート（元のCSV順を維持するよう code でソート）
    results.sort(key=lambda r: r["code"])
    return results


def save_results(results: List[Dict]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    fieldnames = [
        "code", "name", "category", "url",
        "http_status", "response_time_ms", "status", "error", "checked_at",
    ]
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    log.info("結果保存完了: %s", OUT_CSV)


def print_summary(results: List[Dict]) -> None:
    up       = [r for r in results if r["status"] == "UP"]
    down     = [r for r in results if r["status"] == "DOWN"]
    unreach  = [r for r in results if r["status"] == "UNREACHABLE"]

    log.info("=" * 60)
    log.info("死活監視 結果サマリー")
    log.info("  合計         : %d件", len(results))
    log.info("  UP           : %d件", len(up))
    log.info("  DOWN         : %d件", len(down))
    log.info("  UNREACHABLE  : %d件", len(unreach))

    if up:
        avg_ms = sum(r["response_time_ms"] or 0 for r in up) / len(up)
        log.info("  平均応答時間 : %.0f ms (UP機関のみ)", avg_ms)

    if down:
        log.info("--- DOWN 機関一覧 ---")
        for r in down:
            log.info("  [%s] %s  HTTP:%s  %s", r["category"], r["name"], r["http_status"], r["url"])

    if unreach:
        log.info("--- UNREACHABLE 機関一覧 ---")
        for r in unreach[:20]:  # 多すぎる場合は先頭20件のみ表示
            log.info("  [%s] %s  %s  %s", r["category"], r["name"], r["error"], r["url"])
        if len(unreach) > 20:
            log.info("  ... 他 %d件", len(unreach) - 20)

    log.info("=" * 60)


if __name__ == "__main__":
    institutions = load_institutions()
    results = check_all(institutions)
    save_results(results)
    print_summary(results)
