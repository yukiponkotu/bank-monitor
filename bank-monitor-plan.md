# 金融機関ホームページ稼働監視・サービス停止情報収集 — 計画書

## 概要

日本の都市銀行（5行）・地方銀行（全国約100行）・信用金庫（全国約250庫）を対象に、
ホームページの死活監視（HTTP ステータス・レスポンスタイム）と、
トップページに掲載されているサービス停止・障害・メンテナンス情報を収集し、
HTMLダッシュボードとして出力する Python スクリプトを作成する。

### スコープ（必須）
- 金融機関 URL リストの自動収集（全国銀行協会・全国信用金庫協会の公開ページをスクレイピング）
- 各機関のホームページへの HTTP GET による死活確認
- ニュース・お知らせ欄からサービス停止関連キーワードを含む情報の抽出
- HTMLダッシュボードへの結果出力（一回実行）

### スコープ外
- 脆弱性スキャン・ペネトレーションテスト（法的リスクのため実施しない）
- 定期自動実行・監視エージェント
- 既存 Node.js 版 `chiginkun` の改修

---

## サブタスク一覧

---

### サブタスク 1 — URLリスト自動収集モジュール

**Intent**
全国銀行協会（`zenginkyo.or.jp`）の会員行一覧ページと全国信用金庫協会（`shinkin.or.jp`）の信用金庫一覧ページをスクレイピングして、金融機関名・種別・公式サイト URL を CSV として保存する。既存 `chiginkun/src/banks.js` のデータは地銀のみかつ手動保守のため、このスクリプトで補完・差分確認も行う。

**Expected Outcomes**
- `bank_monitor/data/institutions.csv` が生成される
- 列: `code, name, category（都市銀行/地方銀行/信用金庫）, url`
- ログに取得件数（都銀 / 地銀 / 信用金庫別）が出力される

**Todo List**
1. `bank_monitor/` ディレクトリを作成し `requirements.txt` を用意（`requests`, `beautifulsoup4`, `pandas`）
2. `bank_monitor/collect_urls.py` を作成
   - 都市銀行 URL は固定リスト（三菱UFJ・三井住友・みずほ・りそな・埼玉りそな）として直接定義
   - 地方銀行: `https://www.zenginkyo.or.jp/abstract/map/` を GET して各行リンクを抽出
   - 信用金庫: `https://www.shinkin.org/shinkin/area/` を GET して各庫リンクを抽出
   - 結果を `bank_monitor/data/institutions.csv` に保存
3. スクレイピング失敗時は既知の手動リストにフォールバックするフラグを設ける

**Relevant Context**
- 既存の地銀リスト: `chiginkun/src/banks.js`（参考用。直接インポートしない）
- 対象: `requests` + `BeautifulSoup4` のみ（ブラウザ不要）

**Status**
[ ] pending

---

### サブタスク 2 — 死活監視モジュール

**Intent**
`institutions.csv` に記載された全機関の URL に対して HTTP GET を送り、
レスポンスコード・レスポンスタイム・タイムアウト有無を記録する。

**Expected Outcomes**
- `bank_monitor/data/status_results.csv` が生成される
- 列: `code, name, category, url, http_status, response_time_ms, error, checked_at`
- 並列実行（ThreadPoolExecutor）でタイムアウトは 15 秒

**Todo List**
1. `bank_monitor/check_status.py` を作成
   - `institutions.csv` を読み込む
   - `ThreadPoolExecutor(max_workers=20)` で並列 HTTP GET
   - タイムアウト 15 秒、最大リダイレクト 5 回
   - User-Agent は `BankMonitor/1.0 (+https://example.com/bot)` を設定
   - HTTP 200 系: UP、400/500 系: DOWN、タイムアウト/接続エラー: UNREACHABLE に分類
   - 結果を `status_results.csv` に保存

**Relevant Context**
- サブタスク 1 の出力 `institutions.csv` に依存
- `chiginkun/src/scraper.js` と同等の役割を Python で実装

**Status**
[ ] pending

---

### サブタスク 3 — サービス停止情報スクレイピングモジュール

**Intent**
HTTP 200 で応答した機関のトップページ HTML を解析し、
「サービス停止」「メンテナンス」「障害」「システム停止」「振込停止」等のキーワードに
マッチするニュース・お知らせ項目を抽出する。

**Expected Outcomes**
- `bank_monitor/data/service_notices.csv` が生成される
- 列: `code, name, url, date, title, link`
- キーワードにマッチした件数がコンソールに出力される

**Todo List**
1. `bank_monitor/scrape_notices.py` を作成
   - `status_results.csv` で `UP` の機関のみを対象とする
   - `chiginkun/src/scraper.js` と同様のアプローチで HTML を取得・パース（BeautifulSoup4）
   - Shift-JIS / EUC-JP / UTF-8 の文字コード自動検出
   - ニュースリスト候補セレクター: `.news-list li`, `.newslist li`, `li[class*=news]`, `article[class*=news]` 等を順に試みる
   - キーワードフィルター: `["サービス停止", "メンテナンス", "障害", "システム停止", "振込停止", "ATM停止", "一時停止", "休止"]`
   - `service_notices.csv` に保存

**Relevant Context**
- サブタスク 2 の出力 `status_results.csv` に依存
- `chiginkun/src/banks.js` の `newsSelector` を参考にセレクターを設定

**Status**
[ ] pending

---

### サブタスク 4 — HTMLダッシュボード生成モジュール

**Intent**
死活監視結果とサービス停止情報を統合したHTMLダッシュボードを生成する。
ブラウザで開くだけで全機関の状況が一覧できる。

**Expected Outcomes**
- `bank_monitor/report/dashboard.html` が生成される
- サマリーカード: UP数 / DOWN数 / UNREACHABLE数 / サービス停止通知数
- テーブル: 機関名・種別・URL・ステータス・レスポンスタイム・サービス停止情報（クリック展開）
- ステータス別カラーコード（緑/赤/グレー）
- 種別・ステータスでフィルタリング可能（JavaScript）
- 外部CDN不使用（オフライン表示可能）

**Todo List**
1. `bank_monitor/generate_report.py` を作成
   - `status_results.csv` と `service_notices.csv` をマージ
   - Jinja2 テンプレートを使って HTML を生成（テンプレートは `bank_monitor/templates/dashboard.html.j2`）
   - インラインCSS・JavaScriptでフィルタ・ソート機能を実装
   - 生成ファイルを `bank_monitor/report/dashboard.html` に出力
2. Jinja2 を `requirements.txt` に追加

**Relevant Context**
- サブタスク 2, 3 の CSV 出力に依存
- 外部フォント・CDN不使用でポータブルな単一HTMLファイルとして出力する

**Status**
[ ] pending

---

### サブタスク 5 — エントリーポイント（一括実行スクリプト）

**Intent**
上記4モジュールを順番に呼び出す単一エントリーポイントを作成し、
`python bank_monitor/run.py` の一コマンドで全処理が完結するようにする。

**Expected Outcomes**
- `bank_monitor/run.py` を実行すると `collect_urls → check_status → scrape_notices → generate_report` が順に実行される
- 実行ログ（進捗・エラー数・最終レポートパス）がコンソールに出力される
- `requirements.txt` が揃っていれば追加設定なしで動作する

**Todo List**
1. `bank_monitor/run.py` を作成
   - 各モジュールを `subprocess` または `import` で順次呼び出す
   - 開始時刻・終了時刻・処理件数をサマリーとして出力
2. `bank_monitor/README.md` に実行方法・依存ライブラリを記述

**Relevant Context**
- サブタスク 1〜4 すべてに依存

**Status**
[ ] pending

---

## 技術スタック

| 用途 | ライブラリ |
|---|---|
| HTTP リクエスト | `requests` |
| HTML パース | `beautifulsoup4` |
| 文字コード検出 | `chardet` |
| データ処理 | `pandas` |
| HTML テンプレート | `jinja2` |
| 並列処理 | `concurrent.futures.ThreadPoolExecutor` |

## ディレクトリ構成（完成後）

```
bank_monitor/
├── run.py                  # エントリーポイント
├── collect_urls.py         # サブタスク 1
├── check_status.py         # サブタスク 2
├── scrape_notices.py       # サブタスク 3
├── generate_report.py      # サブタスク 4
├── requirements.txt
├── README.md
├── data/
│   ├── institutions.csv
│   ├── status_results.csv
│   └── service_notices.csv
├── report/
│   └── dashboard.html
└── templates/
    └── dashboard.html.j2
```

## 制約・注意事項

- 第三者サーバーへのアクセスは **死活確認（GET）とニューステキスト取得のみ** に限定する
- レート制限: 1機関あたり1リクエスト（リトライ最大2回）
- 脆弱性スキャン・ヘッダ操作・ペイロード送信は **一切行わない**
- robots.txt は参照するが、金融機関公式サイトのトップページへのGETは一般的に許容範囲とみなす
