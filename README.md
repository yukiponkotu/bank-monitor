# BankMonitor — 金融機関ホームページ稼働状況監視ツール

日本の都市銀行・地方銀行・信用金庫のホームページを定期的に確認し、
稼働状況とサービス停止情報を HTML ダッシュボードとして出力する Python スクリプトです。

## 機能

| 機能 | 内容 |
|---|---|
| URL 自動収集 | 全国銀行協会・全国信用金庫協会の公開ページから機関一覧を自動収集 |
| 死活監視 | HTTP GET による応答確認（UP / DOWN / UNREACHABLE 分類） |
| 停止情報収集 | トップページのお知らせからサービス停止・障害・メンテナンス情報を抽出 |
| HTML レポート | フィルター・ソート機能付きのダッシュボードを生成 |

## 対象機関

- 都市銀行（5行）: みずほ・三菱UFJ・三井住友・りそな・埼玉りそな
- 地方銀行（全国約100行）
- 信用金庫（全国約250庫）

## インストール

```bash
cd bank_monitor
pip install -r requirements.txt
```

## 実行

### 全ステップを一括実行（推奨）

```bash
python run.py
```

### 個別実行

```bash
# Step 1: 金融機関 URL 一覧を収集
python collect_urls.py

# Step 2: 死活監視
python check_status.py

# Step 3: サービス停止情報を収集
python scrape_notices.py

# Step 4: HTML ダッシュボード生成
python generate_report.py
```

### オプション

```bash
# URL収集をスキップ（既存 institutions.csv を使用）
python run.py --skip-collect

# 死活監視・停止情報収集をスキップしてレポートのみ再生成
python run.py --report-only
```

## 出力ファイル

| ファイル | 内容 |
|---|---|
| `data/institutions.csv` | 収集した金融機関一覧 |
| `data/status_results.csv` | 死活監視結果 |
| `data/service_notices.csv` | サービス停止関連お知らせ |
| `report/dashboard.html` | HTML ダッシュボード（ブラウザで開く） |

## 依存ライブラリ

| ライブラリ | 用途 |
|---|---|
| `requests` | HTTP リクエスト |
| `beautifulsoup4` | HTML パース |
| `chardet` | 文字コード自動検出（Shift-JIS 等対応） |
| `pandas` | データ処理（オプション） |
| `jinja2` | HTML テンプレート生成 |
| `lxml` | HTML パーサー（BeautifulSoup バックエンド） |

## 注意事項

- 本ツールは公開されているトップページへの HTTP GET による死活確認のみを行います
- 脆弱性スキャン・ペネトレーションテストは**一切行いません**
- アクセス間隔は適切に制御されており（タイムアウト 15 秒・最大リダイレクト 5 回）、サーバーへの過度な負荷をかけません
- User-Agent は `BankMonitor/1.0` を設定しています
