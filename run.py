"""
run.py — BankMonitor エントリーポイント
========================================
以下の4ステップを順番に実行し、最終的に HTMLダッシュボードを生成する。

  Step 1: collect_urls.py   — 金融機関 URL 一覧を収集
  Step 2: check_status.py   — 各機関の死活監視
  Step 3: scrape_notices.py — サービス停止情報の抽出
  Step 4: generate_report.py— HTMLダッシュボード生成

使い方:
  pip install -r requirements.txt
  python run.py

オプション:
  --skip-collect   URLリスト収集をスキップ（既存 institutions.csv を使用）
  --skip-status    死活監視をスキップ（既存 status_results.csv を使用）
  --skip-notices   停止情報取得をスキップ（既存 service_notices.csv を使用）
  --report-only    レポート生成のみ実行
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("run")

JST = timezone(timedelta(hours=9))

REPORT_PATH = os.path.join(os.path.dirname(__file__), "report", "index.html")


def step(name: str, fn, *args, **kwargs):
    """ステップを実行して経過時間を表示する。"""
    log.info("─" * 60)
    log.info("▶ %s", name)
    t0 = time.monotonic()
    fn(*args, **kwargs)
    elapsed = time.monotonic() - t0
    log.info("✓ %s 完了 (%.1f秒)", name, elapsed)
    return elapsed


def main():
    parser = argparse.ArgumentParser(description="BankMonitor — 金融機関稼働状況監視")
    parser.add_argument("--skip-collect",  action="store_true", help="URL収集をスキップ")
    parser.add_argument("--skip-status",   action="store_true", help="死活監視をスキップ")
    parser.add_argument("--skip-notices",  action="store_true", help="停止情報取得をスキップ")
    parser.add_argument("--report-only",   action="store_true", help="レポート生成のみ")
    args = parser.parse_args()

    if args.report_only:
        args.skip_collect = True
        args.skip_status  = True
        args.skip_notices = True

    start_all = time.monotonic()
    start_ts  = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    log.info("=" * 60)
    log.info("BankMonitor 開始: %s", start_ts)
    log.info("=" * 60)

    times = {}

    # ── Step 1: URL 収集 ──────────────────────────────────────────────
    if not args.skip_collect:
        from collect_urls import collect_all, save_csv
        times["URL収集"] = step("Step 1: 金融機関 URL 収集", lambda: save_csv(collect_all()))
    else:
        log.info("Step 1: URL収集 をスキップ")

    # ── Step 2: 死活監視 ─────────────────────────────────────────────
    if not args.skip_status:
        from check_status import load_institutions, check_all, save_results, print_summary
        def _check():
            insts   = load_institutions()
            results = check_all(insts)
            save_results(results)
            print_summary(results)
        times["死活監視"] = step("Step 2: 死活監視", _check)
    else:
        log.info("Step 2: 死活監視 をスキップ")

    # ── Step 3: 停止情報収集 ─────────────────────────────────────────
    if not args.skip_notices:
        from scrape_notices import load_up_institutions, scrape_all, save_notices
        def _notices():
            insts   = load_up_institutions()
            notices = scrape_all(insts)
            save_notices(notices)
        times["停止情報収集"] = step("Step 3: サービス停止情報収集", _notices)
    else:
        log.info("Step 3: 停止情報収集 をスキップ")

    # ── Step 4: レポート生成 ─────────────────────────────────────────
    from generate_report import generate
    times["レポート生成"] = step("Step 4: HTMLダッシュボード生成", generate)

    # ── 完了サマリー ─────────────────────────────────────────────────
    total_elapsed = time.monotonic() - start_all
    end_ts = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")

    log.info("=" * 60)
    log.info("BankMonitor 完了: %s (合計 %.1f秒)", end_ts, total_elapsed)
    for step_name, elapsed in times.items():
        log.info("  %-16s %.1f秒", step_name, elapsed)
    log.info("")
    log.info("📊 レポートを開いてください:")
    log.info("   %s", os.path.abspath(REPORT_PATH))
    log.info("=" * 60)


if __name__ == "__main__":
    # カレントディレクトリを bank_monitor/ に変更してモジュールを正しく import できるようにする
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
