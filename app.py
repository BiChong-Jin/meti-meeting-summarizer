import json
import os
import time
import uuid
import fitz  # PyMuPDF
import streamlit as st
from dotenv import load_dotenv
from langchain_classic.chains.summarize import load_summarize_chain
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pathlib import Path

load_dotenv()

from pdf_fetcher import download_pdf, fetch_pdf_links, fetch_video_links, scrape_page
from notifier import send_slack
from site_monitor import check_for_updates, save_state
from report_store import save_report, list_reports, list_video_reports, load_report, search_reports, search_video_reports
from video_summarizer import extract_video_id, fetch_transcript, VideoTranscriptError

# --- Per-session cache helpers ---
CACHE_DIR = Path("session_cache")
CACHE_DIR.mkdir(exist_ok=True)
SESSION_TTL_DAYS = 7  # clean up sessions older than this


def _cleanup_old_sessions() -> None:
    cutoff = time.time() - SESSION_TTL_DAYS * 86400
    for f in CACHE_DIR.glob("*.json"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


def _get_session_id() -> str:
    """Return a stable session ID stored in the URL query params."""
    sid = st.query_params.get("sid")
    if not sid:
        sid = uuid.uuid4().hex
        st.query_params["sid"] = sid
    return sid


def _cache_file() -> Path:
    return CACHE_DIR / f"{_get_session_id()}.json"


def load_cache() -> dict:
    f = _cache_file()
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"pdf_texts": [], "summary_result": None}


def save_cache() -> None:
    data = {
        "pdf_texts": st.session_state.pdf_texts,
        "summary_result": st.session_state.summary_result,
        "video_summary_result": st.session_state.get("video_summary_result"),
    }
    _cache_file().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# Run cleanup once per session (not on every rerun)
if "cache_cleaned" not in st.session_state:
    _cleanup_old_sessions()
    st.session_state.cache_cleaned = True

# --- 1. Session State Initialization (load from per-user cache on first run) ---
if "pdf_texts" not in st.session_state:
    cache = load_cache()
    st.session_state.pdf_texts = cache["pdf_texts"]
    st.session_state.summary_result = cache["summary_result"]
    st.session_state.video_summary_result = cache.get("video_summary_result")

st.set_page_config(page_title="議事録要約ツール", layout="wide")

# --- Report viewer: render a single report if ?view=<id> is in the URL ---
_view_id = st.query_params.get("view")
if _view_id:
    report = load_report(_view_id)
    if report:
        st.title(f"📋 {report['title']}")
        if report["date"]:
            st.caption(f"日付: {report['date']}　／　生成日時: {report['created_at']}")
        if report["sources"]:
            st.caption("使用資料: " + "、".join(report["sources"]))
        st.divider()
        st.markdown(report["content"])
    else:
        st.error("レポートが見つかりませんでした。")
    st.stop()  # Don't render the rest of the app

st.title("📋 会議資料・要約作成ツール (OpenAI)")

# --- 2. Sidebar Settings ---
st.sidebar.header("設定")
openai_api_key = os.getenv("OPENAI_API_KEY", "")
model_choice = st.sidebar.selectbox("モデル選択", ["gpt-4o", "gpt-4o-mini"])

if not openai_api_key:
    st.sidebar.warning("OPENAI_API_KEY が .env に設定されていません")

st.sidebar.divider()
st.sidebar.subheader("🔔 更新監視 (Slack通知)")
monitor_url = st.sidebar.text_input(
    "監視するページのURL",
    placeholder="例: https://www.meti.go.jp/.../index.html",
    key="monitor_url",
)
slack_webhook = os.getenv("SLACK_WEBHOOK", "")

if st.sidebar.button("今すぐ確認"):
    if not monitor_url:
        st.sidebar.warning("URLを入力してください")
    else:
        with st.sidebar:
            with st.spinner("確認中..."):
                try:
                    result = check_for_updates(monitor_url)
                    save_state(result["last_update_date"], result["all_links"])

                    if result["has_update"]:
                        st.success(f"新着あり！ {len(result['new_items'])} 件")
                        for item in result["new_items"]:
                            st.markdown(f"• [{item['text']}]({item['href']})")
                        if slack_webhook:
                            send_slack(slack_webhook, monitor_url, result)
                            st.info("Slack通知を送信しました")
                        else:
                            st.warning("SLACK_WEBHOOK が .env に設定されていないため通知は送信されていません")
                    else:
                        st.info(f"更新なし\n{result['last_update_date']}")
                except Exception as e:
                    st.error(f"エラー: {e}")

st.sidebar.divider()
st.sidebar.subheader("レポート情報")
meeting_title = st.sidebar.text_input(
    "会議のタイトル",
    placeholder="例：第1回 企画戦略会議",
    value=st.session_state.get("_meeting_title", ""),
)
meeting_date = st.sidebar.text_input(
    "日付",
    placeholder="例：2026/03/30",
    value=st.session_state.get("_meeting_date", ""),
)

# --- 3. Prompt Engineering (Japanese Form) ---

# Map Prompt: Summarize each chunk in Japanese
map_template = """以下の内容を日本語で短く要約してください。
内容: {text}
要約:"""
MAP_PROMPT = PromptTemplate(template=map_template, input_variables=["text"])

# Reduce Prompt: Final Formatting
reduce_template = f"""
あなたはプロの書記です。提供された要約を基に、以下の厳密なフォーマットで日本語のレポートを作成してください。

# {meeting_title if meeting_title else "(会議のタイトル)"}（{meeting_date if meeting_date else "日付"}）

## 議題
(ここでは会議で話された主な議題を1行ずつ簡潔に箇条書きしてください)
1, [議題1]
2, [議題2]
3, [議題3]

## 本レポートのキーポイント（抜粋）
(会議の重要な決定事項や要点を詳細に記述してください)

## 委員コメント（抜粋/氏名省略）
(発言内容の要旨を抜粋して記述してください。氏名は含めないでください)

要約データ:
{{text}}
"""
REDUCE_PROMPT = PromptTemplate(template=reduce_template, input_variables=["text"])

# --- 4. Main UI Logic ---

# -- 4a. Auto-fetch PDFs from a URL --
with st.expander("🌐 WebサイトからPDFを自動取得"):
    page_url = st.text_input(
        "会議ページのURL",
        placeholder="例: https://www.meti.go.jp/shingikai/.../005.html",
    )
    if st.button("PDFリストを取得"):
        if not page_url:
            st.warning("URLを入力してください")
        else:
            with st.spinner("ページを解析中..."):
                try:
                    page_data = scrape_page(page_url)
                    st.session_state["_fetched_links"] = page_data["pdf_links"]
                    st.session_state["_fetched_video_links"] = page_data["video_links"]
                    st.session_state["_meeting_title"] = page_data["title"]
                    st.session_state["_meeting_date"] = page_data["date"]
                    # Auto-select the first video URL if found
                    if page_data["video_links"]:
                        st.session_state["_selected_video_url"] = page_data["video_links"][0]["url"]
                    msg = f"{len(page_data['pdf_links'])} 件のPDF"
                    if page_data["video_links"]:
                        msg += f"、{len(page_data['video_links'])} 件の動画が見つかりました"
                    st.success(msg)
                except Exception as e:
                    st.session_state["_fetched_links"] = []
                    st.session_state["_fetched_video_links"] = []
                    st.error(f"取得エラー: {e}")

    if st.session_state.get("_fetched_links"):
        links = st.session_state["_fetched_links"]
        selected = []
        st.write("ダウンロードするファイルを選択してください:")
        for i, link in enumerate(links):
            checked = st.checkbox(link["filename"], key=f"chk_{i}", value=True)
            if checked:
                selected.append(link)

        if st.button("選択したPDFをキューに追加", type="secondary"):
            added = 0
            with st.spinner("ダウンロード中..."):
                for link in selected:
                    if any(f[0] == link["filename"] for f in st.session_state.pdf_texts):
                        continue
                    try:
                        pdf_bytes = download_pdf(link["url"])
                        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                        text = "".join([page.get_text("text") for page in doc])
                        if not text.strip():
                            st.warning(f"{link['filename']}: テキストを抽出できませんでした（画像PDFの可能性）")
                            continue
                        st.session_state.pdf_texts.append((link["filename"], text))
                        added += 1
                    except Exception as e:
                        st.warning(f"{link['filename']} の取得に失敗: {e}")
            save_cache()
            st.success(f"{added} 件追加しました")
            st.session_state["_fetched_links"] = []
            st.rerun()

    if len(st.session_state.get("_fetched_video_links", [])) > 1:
        video_links = st.session_state["_fetched_video_links"]
        choice = st.selectbox(
            "複数の動画が見つかりました。要約する動画を選択してください:",
            options=[v["url"] for v in video_links],
            format_func=lambda u: next(v["title"] for v in video_links if v["url"] == u),
            key="video_select",
        )
        st.session_state["_selected_video_url"] = choice

st.divider()

# -- 4b. Manual upload --
uploaded_file = st.file_uploader(
    "PDFファイルをアップロードしてキューに追加", type="pdf"
)

if uploaded_file:
    if not any(f == uploaded_file.name for f in st.session_state.pdf_texts):
        with st.spinner(f"{uploaded_file.name} を解析中..."):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            text = "".join([page.get_text("text") for page in doc])
            if not text.strip():
                st.warning(
                    f"{uploaded_file.name}: テキストを抽出できませんでした。"
                    "画像のみのPDFの可能性があります。OCR対応は現在未実装です。"
                )
            else:
                st.session_state.pdf_texts.append((uploaded_file.name, text))
                save_cache()
                st.success(f"追加完了: {uploaded_file.name}")

if st.session_state.pdf_texts:
    st.subheader("アップロード済みファイル")
    for i, (name, _) in enumerate(st.session_state.pdf_texts):
        # Unpack the list into individual column objects
        col1, col2 = st.columns([0.8, 0.2])

        # Use the specific column objects
        col1.write(f"📄 {name}")
        if col2.button("削除", key=f"del_{i}"):
            st.session_state.pdf_texts.pop(i)
            save_cache()
            st.rerun()
    # cols = st.columns([0.8, 0.2])
    # cols.write(f"📄 {name}")
    # if cols.button("削除", key=f"del_{i}"):
    #     st.session_state.pdf_texts.pop(i)
    #     st.rerun()

    if st.button("🚀 要約レポートを作成する", type="primary"):
        if not openai_api_key:
            st.error("OPENAI_API_KEY が .env に設定されていません。管理者に連絡してください。")
        else:
            with st.spinner("AIがレポートを作成しています..."):
                try:
                    # Text Processing
                    text_splitter = RecursiveCharacterTextSplitter(
                        chunk_size=3000, chunk_overlap=300
                    )
                    all_docs = []
                    for name, content in st.session_state.pdf_texts:
                        chunks = text_splitter.split_text(content)
                        all_docs.extend([Document(page_content=c) for c in chunks])

                    # LLM Setup
                    llm = ChatOpenAI(
                        model=model_choice, api_key=openai_api_key, temperature=0
                    )

                    # Custom Summarization Chain
                    chain = load_summarize_chain(
                        llm=llm,
                        chain_type="map_reduce",
                        map_prompt=MAP_PROMPT,
                        combine_prompt=REDUCE_PROMPT,
                        verbose=False,
                    )

                    st.session_state.summary_result = chain.run(all_docs)
                    sources = [name for name, _ in st.session_state.pdf_texts]
                    st.session_state.last_report_id = save_report(
                        meeting_title, meeting_date,
                        st.session_state.summary_result, sources,
                        source_type="pdf",
                    )
                    save_cache()
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")

# --- 5. Display Results ---
if st.session_state.summary_result:
    st.divider()
    st.subheader("生成されたレポート")
    st.markdown(st.session_state.summary_result)

    col_dl, col_link = st.columns([1, 1])
    col_dl.download_button(
        label="レポートをテキストとして保存",
        data=st.session_state.summary_result,
        file_name="summary_report.txt",
        mime="text/plain",
    )
    if st.session_state.get("last_report_id"):
        report_url = f"?view={st.session_state.last_report_id}"
        col_link.markdown(f"🔗 [このレポートの共有リンク]({report_url})")

# --- 6. Video Summary ---
st.divider()
st.subheader("🎥 動画要約")
video_url = st.text_input(
    "YouTube URL",
    placeholder="例: https://www.youtube.com/watch?v=...",
    value=st.session_state.get("_selected_video_url", ""),
)

if st.button("🎬 動画を要約する", type="secondary"):
    if not video_url:
        st.warning("YouTubeのURLを入力してください")
    elif not openai_api_key:
        st.error("OPENAI_API_KEY が .env に設定されていません。管理者に連絡してください。")
    else:
        with st.spinner("字幕を取得してAIが要約しています..."):
            try:
                video_id = extract_video_id(video_url)
                transcript = fetch_transcript(video_id)

                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=3000, chunk_overlap=300
                )
                chunks = text_splitter.split_text(transcript)
                docs = [Document(page_content=c) for c in chunks]

                llm = ChatOpenAI(model=model_choice, api_key=openai_api_key, temperature=0)
                chain = load_summarize_chain(
                    llm=llm,
                    chain_type="map_reduce",
                    map_prompt=MAP_PROMPT,
                    combine_prompt=REDUCE_PROMPT,
                )
                st.session_state.video_summary_result = chain.run(docs)
                st.session_state.last_video_report_id = save_report(
                    meeting_title, meeting_date,
                    st.session_state.video_summary_result,
                    [video_url],
                    source_type="video",
                )
                save_cache()
            except VideoTranscriptError as e:
                st.error(f"字幕エラー: {e}")
            except ValueError as e:
                st.error(f"URL エラー: {e}")
            except Exception as e:
                st.error(f"エラーが発生しました: {e}")

if st.session_state.get("video_summary_result"):
    st.markdown("### 📝 動画要約レポート")
    st.markdown(st.session_state.video_summary_result)

    col_dl, col_link = st.columns([1, 1])
    col_dl.download_button(
        label="動画要約をテキストとして保存",
        data=st.session_state.video_summary_result,
        file_name="video_summary_report.txt",
        mime="text/plain",
    )
    if st.session_state.get("last_video_report_id"):
        col_link.markdown(f"🔗 [この動画要約の共有リンク](?view={st.session_state.last_video_report_id})")

# --- 7. Shared Reports Library ---
def _render_report_list(reports: list[dict], search_query: str) -> None:
    if not reports:
        if search_query:
            st.info("キーワードとマッチした検索結果が見つかりませんでした")
        else:
            st.info("まだレポートはありません")
    else:
        for r in reports:
            col_date, col_title, col_link = st.columns([0.2, 0.55, 0.25])
            col_date.write(r.get("date", "―"))
            col_title.write(f"**{r['title']}**")
            col_link.markdown(f"[開く](?view={r['id']})")


st.divider()
with st.expander("📚 過去のPDFレポート一覧", expanded=False):
    pdf_search = st.text_input("🔍 レポート検索", placeholder="キーワードを入力...", key="pdf_search")
    reports = search_reports(pdf_search) if pdf_search else list_reports()
    _render_report_list(reports, pdf_search)

st.divider()
with st.expander("🎥 過去の動画要約一覧", expanded=False):
    video_search = st.text_input("🔍 動画要約検索", placeholder="キーワードを入力...", key="video_search")
    video_reports = search_video_reports(video_search) if video_search else list_video_reports()
    _render_report_list(video_reports, video_search)
