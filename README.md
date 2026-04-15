# 会議資料・要約作成ツール

経済産業省（METI）の審議会資料（PDF・YouTube動画）を自動で要約するWebアプリケーション。

**対象**: 次世代電力・ガス事業基盤構築小委員会

## 主な機能

- 会議ページのURLからPDF・動画リンク・タイトル・日付を自動取得
- PDFテキスト抽出（画像PDFはOpenAI Vision APIでOCR対応）
- YouTube動画の字幕を取得して要約
- 並列Map-Reduce処理による高速要約（GPT-4o-mini + GPT-4o）
- 生成レポートの共有ライブラリ（検索・ページネーション付き）
- レポート重複防止
- ユーザー認証（ドメイン制限付き登録、管理者パネル）
- METI更新監視 + Slack通知

## 技術スタック

| カテゴリ | 技術 |
|---------|------|
| Web UI | Streamlit |
| LLM | OpenAI GPT-4o / GPT-4o-mini |
| PDF処理 | PyMuPDF |
| OCR | OpenAI Vision API |
| 動画字幕 | youtube-transcript-api |
| Webスクレイピング | BeautifulSoup + requests |
| データベース | SQLite (WALモード) |
| 認証 | bcrypt |
| 通知 | Slack Incoming Webhook |
| CI | GitHub Actions |
| デプロイ | Streamlit Cloud / Docker |

## セットアップ

### 必要条件
- Python 3.13+
- OpenAI APIキー

### インストール

```bash
git clone https://github.com/BiChong-Jin/meti-meeting-summarizer.git
cd meti-meeting-summarizer
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 環境変数

`.env` ファイルをプロジェクトルートに作成:

```
OPENAI_API_KEY=sk-...
ALLOWED_DOMAIN=gmail.com
SLACK_WEBHOOK=https://hooks.slack.com/services/XXX/YYY/ZZZ
MONITOR_URL=https://www.meti.go.jp/shingikai/enecho/denryoku_gas/jisedai_kiban/index.html
```

Streamlit Cloudの場合は、Settings > Secrets に同じ内容をTOML形式で設定:

```toml
OPENAI_API_KEY = "sk-..."
ALLOWED_DOMAIN = "gmail.com"
SLACK_WEBHOOK = ""
MONITOR_URL = "https://www.meti.go.jp/shingikai/enecho/denryoku_gas/jisedai_kiban/index.html"
```

### 起動

```bash
streamlit run app.py
```

## 使い方

1. ログインまたは新規登録（設定されたドメインのメールアドレスが必要）
2. 会議ページのURLを入力 → PDFリストと動画URLを自動取得
3. PDFをキューに追加 → 「要約レポートを作成する」をクリック
4. 動画URLが自動入力される → 「動画を要約する」をクリック
5. 生成されたレポートは共有リンクで同僚に共有可能

## テスト

```bash
python -m pytest tests/ -v
```

テストスイート: 79テスト（認証、レポート管理、スクレイピング、通知、負荷テスト）

## 更新監視（cronジョブ）

```bash
# 毎日9時に実行
0 9 * * * /path/to/.venv/bin/python /path/to/checker.py
```

新着があればSlackに通知。ページ構成が変更された場合もエラー通知。

## 注意事項

- METIサイトのスクレイピングは日本国内のIPからのみ動作します。海外サーバー（Streamlit Cloud含む）からはタイムアウトします。その場合は手動でPDFをアップロードしてください。
- 最初に登録したユーザーが自動的に管理者になります。

## プロジェクト構成

```
app.py              - メインアプリケーション
auth.py             - 認証（登録・ログイン・管理者）
db.py               - SQLiteデータベース管理
pdf_fetcher.py      - Webスクレイピング（PDF・動画・メタデータ）
video_summarizer.py - YouTube字幕取得
ocr.py              - 画像PDFのOCR処理
site_monitor.py     - METI更新検出
notifier.py         - Slack通知
checker.py          - 日次監視スクリプト（cron用）
report_store.py     - レポート保存・検索・ページネーション
migrate_json_to_sqlite.py - JSONからSQLiteへの移行スクリプト
tests/              - テストスイート（79テスト）
```
