"""
generate_report.py
==================
status_results.csv と service_notices.csv を統合して
Jinja2 テンプレートから HTMLダッシュボードを生成する。
出力: bank_monitor/report/dashboard.html
"""

import csv
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List

from jinja2 import Environment, FileSystemLoader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

BASE_DIR      = os.path.dirname(__file__)
DATA_DIR      = os.path.join(BASE_DIR, "data")
TEMPLATE_DIR  = os.path.join(BASE_DIR, "templates")
REPORT_DIR    = os.path.join(BASE_DIR, "report")
STATUS_CSV    = os.path.join(DATA_DIR, "status_results.csv")
NOTICES_CSV   = os.path.join(DATA_DIR, "service_notices.csv")
OUT_HTML      = os.path.join(REPORT_DIR, "dashboard.html")

JST = timezone(timedelta(hours=9))


def load_csv(path: str) -> List[Dict]:
    if not os.path.exists(path):
        log.warning("CSV が見つかりません: %s", path)
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _to_jst(iso_str: str) -> str:
    """ISO8601 UTC 文字列を JST の表示用文字列に変換する。"""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        dt_jst = dt.astimezone(JST)
        return dt_jst.strftime("%Y-%m-%d %H:%M JST")
    except Exception:
        return iso_str


def build_rows(status_rows: List[Dict], notices_rows: List[Dict]) -> List[Dict]:
    """ステータスとお知らせを機関コードで結合してテンプレート用 row を構築する。"""

    # code+name をキーにお知らせを集約
    notices_map: Dict[str, List[Dict]] = {}
    for n in notices_rows:
        key = n.get("code", "") + "__" + n.get("name", "")
        notices_map.setdefault(key, []).append({
            "date":  n.get("date", ""),
            "title": n.get("title", ""),
            "link":  n.get("link", ""),
        })

    rows = []
    for s in status_rows:
        key = s.get("code", "") + "__" + s.get("name", "")
        row = {
            "code":             s.get("code", ""),
            "name":             s.get("name", ""),
            "category":         s.get("category", ""),
            "url":              s.get("url", ""),
            "http_status":      s.get("http_status", ""),
            "response_time_ms": s.get("response_time_ms", ""),
            "status":           s.get("status", "UNREACHABLE"),
            "error":            s.get("error", ""),
            "checked_at":       s.get("checked_at", ""),
            "checked_at_jst":   _to_jst(s.get("checked_at", "")),
            "notices":          notices_map.get(key, []),
        }
        rows.append(row)

    # 金融機関コード順でソート
    # 数値コード (0001〜) → R連番 → S連番 の順になるよう自然順ソート
    def _sort_key(r):
        code = r["code"]
        if code.startswith("S"):
            return (2, code)
        if code.startswith("R"):
            return (1, code)
        return (0, code.zfill(6))   # 数値コードはゼロ埋めで辞書順

    rows.sort(key=_sort_key)
    return rows


def build_stats(rows: List[Dict]) -> Dict:
    up         = [r for r in rows if r["status"] == "UP"]
    down       = [r for r in rows if r["status"] == "DOWN"]
    unreachable= [r for r in rows if r["status"] == "UNREACHABLE"]
    with_notices = [r for r in rows if r["notices"]]

    avg_ms = 0
    up_with_rt = [r for r in up if r["response_time_ms"]]
    if up_with_rt:
        avg_ms = int(sum(int(r["response_time_ms"]) for r in up_with_rt) / len(up_with_rt))

    return {
        "total":        len(rows),
        "up":           len(up),
        "down":         len(down),
        "unreachable":  len(unreachable),
        "with_notices": len(with_notices),
        "avg_response_ms": avg_ms,
    }


def generate() -> None:
    log.info("レポート生成開始")

    status_rows  = load_csv(STATUS_CSV)
    notices_rows = load_csv(NOTICES_CSV)

    if not status_rows:
        log.error(
            "status_results.csv が空または存在しません。"
            "check_status.py を先に実行してください。"
        )
        return

    rows  = build_rows(status_rows, notices_rows)
    stats = build_stats(rows)

    now_jst = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=True,
    )
    # truncate フィルターは Jinja2 デフォルトで使えるが、URL 用に killwords=True に設定
    env.filters["truncate"] = lambda s, length, **kw: (
        s[:length] + "…" if len(s) > length else s
    )

    template = env.get_template("dashboard.html.j2")
    html = template.render(
        rows=rows,
        stats=stats,
        generated_at=now_jst,
    )

    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    log.info("ダッシュボード生成完了: %s", OUT_HTML)
    log.info(
        "=== 統計 === 合計:%d  UP:%d  DOWN:%d  接続不可:%d  停止情報あり:%d  平均応答:%dms",
        stats["total"], stats["up"], stats["down"],
        stats["unreachable"], stats["with_notices"], stats["avg_response_ms"],
    )


if __name__ == "__main__":
    generate()
