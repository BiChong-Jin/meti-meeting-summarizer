import json
import logging
import os
import time
import uuid
import fitz  # PyMuPDF
import streamlit as st
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger(__name__)
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

from db import get_connection
from pdf_fetcher import download_pdf, scrape_page
from ocr import extract_text_with_ocr
from notifier import send_slack
from site_monitor import check_for_updates, save_state
from report_store import save_report, list_reports, list_video_reports, load_report, search_reports, search_video_reports, count_reports, REPORTS_PER_PAGE
from video_summarizer import extract_video_id, fetch_transcript, VideoTranscriptError
from auth import register_user, authenticate, list_users, delete_user, update_role, AuthError

# --- Per-session cache helpers ---
SESSION_TTL_DAYS = 7


def _cleanup_old_sessions() -> None:
    cutoff = time.time() - SESSION_TTL_DAYS * 86400
    with get_connection() as conn:
        conn.execute("DELETE FROM session_cache WHERE updated_at < ?", (cutoff,))


def _get_session_id() -> str:
    """Return a stable session ID stored in the URL query params."""
    sid = st.query_params.get("sid")
    if not sid:
        sid = uuid.uuid4().hex
        st.query_params["sid"] = sid
    return sid


def load_cache() -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM session_cache WHERE session_id = ?", (_get_session_id(),)
        ).fetchone()
    if not row:
        return {"pdf_texts": [], "summary_result": None, "video_summary_result": None, "auth_email": "", "auth_role": ""}
    return {
        "pdf_texts": json.loads(row["pdf_texts"]),
        "summary_result": row["summary_result"],
        "video_summary_result": row["video_summary_result"],
        "auth_email": row["auth_email"] or "",
        "auth_role": row["auth_role"] or "",
    }


def save_cache() -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO session_cache (session_id, pdf_texts, summary_result, video_summary_result, auth_email, auth_role, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                _get_session_id(),
                json.dumps(st.session_state.pdf_texts, ensure_ascii=False),
                st.session_state.summary_result,
                st.session_state.get("video_summary_result"),
                st.session_state.get("user_email", ""),
                st.session_state.get("user_role", ""),
                time.time(),
            ),
        )


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

st.markdown(
    """
    <style>
    [data-testid="stSidebar"][aria-expanded="false"] + div [data-testid="stExpandSidebarButton"] {
        background-color: #e8e8e8;
        border-radius: 8px;
        padding: 8px;
    }
    [data-testid="stSidebar"][aria-expanded="false"] + div [data-testid="stExpandSidebarButton"] span {
        color: #333333 !important;
    }
    [data-testid="stSidebar"][aria-expanded="false"] + div [data-testid="stExpandSidebarButton"]::after {
        content: "メニュー";
        color: #333333;
        font-size: 12px;
        display: block;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Auth Gate ---
if "authenticated" not in st.session_state:
    cache = load_cache()
    if cache["auth_email"]:
        st.session_state.authenticated = True
        st.session_state.user_email = cache["auth_email"]
        st.session_state.user_role = cache["auth_role"]
    else:
        st.session_state.authenticated = False
        st.session_state.user_email = ""
        st.session_state.user_role = ""

if not st.session_state.authenticated:
    st.title("📋 会議資料・要約作成ツール")
    login_tab, register_tab = st.tabs(["ログイン", "新規登録"])

    with login_tab:
        with st.form("login_form"):
            email = st.text_input("メールアドレス", placeholder="会社のメールアドレスをご入力ください")
            password = st.text_input("パスワード", type="password")
            if st.form_submit_button("ログイン", type="primary"):
                try:
                    user = authenticate(email, password)
                    st.session_state.authenticated = True
                    st.session_state.user_email = user["email"]
                    st.session_state.user_role = user["role"]
                    save_cache()
                    log.info("User logged in: %s", user["email"])
                    st.rerun()
                except AuthError as e:
                    log.warning("Login failed for: %s", email)
                    st.error(str(e))

    with register_tab:
        with st.form("register_form"):
            reg_email = st.text_input("メールアドレス", placeholder="会社のメールアドレスをご入力ください", key="reg_email")
            reg_password = st.text_input("パスワード（8文字以上）", type="password", key="reg_pw")
            reg_confirm = st.text_input("パスワード確認", type="password", key="reg_confirm")
            if st.form_submit_button("登録"):
                if reg_password != reg_confirm:
                    st.error("パスワードが一致しません。")
                else:
                    try:
                        register_user(reg_email, reg_password)
                        st.success("登録完了！ログインタブからログインしてください。")
                    except AuthError as e:
                        st.error(str(e))

    st.stop()

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
st.sidebar.caption(f"ログイン中: {st.session_state.user_email}")
if st.sidebar.button("ログアウト"):
    st.session_state.authenticated = False
    st.session_state.user_email = ""
    st.session_state.user_role = ""
    save_cache()
    st.rerun()

st.sidebar.divider()
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
if "_meeting_title" in st.session_state and st.session_state["_meeting_title"]:
    st.session_state["meeting_title_input"] = st.session_state.pop("_meeting_title")
if "_meeting_date" in st.session_state and st.session_state["_meeting_date"]:
    st.session_state["meeting_date_input"] = st.session_state.pop("_meeting_date")
meeting_title = st.sidebar.text_input(
    "会議のタイトル",
    placeholder="例：第1回 企画戦略会議",
    key="meeting_title_input",
)
meeting_date = st.sidebar.text_input(
    "日付",
    placeholder="例：2026/03/30",
    key="meeting_date_input",
)

# --- Admin panel (sidebar) ---
if st.session_state.user_role == "admin":
    st.sidebar.divider()
    st.sidebar.subheader("管理者メニュー")
    with st.sidebar.expander("ユーザー管理"):
        users = list_users()
        for u in users:
            is_self = u["email"] == st.session_state.user_email
            col_email, col_role, col_action, col_del = st.columns([0.4, 0.15, 0.25, 0.2])
            col_email.write(u["email"])
            col_role.write(u["role"])
            if not is_self:
                if u["role"] == "user":
                    if col_action.button("管理者に昇格", key=f"promote_{u['email']}"):
                        update_role(u["email"], "admin")
                        st.rerun()
                else:
                    if col_action.button("管理者を解除", key=f"demote_{u['email']}"):
                        update_role(u["email"], "user")
                        st.rerun()
                if col_del.button("削除", key=f"delusr_{u['email']}"):
                    delete_user(u["email"])
                    st.rerun()
        st.caption(f"登録ユーザー数: {len(users)}")

CHUNK_SIZE = 3000
CHUNK_OVERLAP = 300
MAP_MODEL = "gpt-4o-mini"
MAX_PARALLEL_CHUNKS = 10

from concurrent.futures import ThreadPoolExecutor, as_completed


def _map_single_chunk(chunk_text: str, map_prompt, api_key: str) -> str:
    """Summarize a single chunk using the fast model."""
    llm = ChatOpenAI(model=MAP_MODEL, api_key=api_key, temperature=0)
    prompt_text = map_prompt.format(text=chunk_text)
    return llm.invoke(prompt_text).content


def run_summarization(text_chunks: list[str], map_prompt, reduce_prompt, stream_container=None) -> str:
    """Run parallel map + streaming reduce summarization."""
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    all_chunks = []
    for text in text_chunks:
        all_chunks.extend(text_splitter.split_text(text))

    log.info("Summarizing %d chunks (parallel map with %s)", len(all_chunks), MAP_MODEL)

    # --- Parallel map phase ---
    summaries = [None] * len(all_chunks)
    if stream_container is not None:
        stream_container.info(f"📊 {len(all_chunks)} チャンクを {MAP_MODEL} で並列処理中...")

    completed = 0
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CHUNKS) as pool:
        future_to_idx = {
            pool.submit(_map_single_chunk, chunk, map_prompt, openai_api_key): i
            for i, chunk in enumerate(all_chunks)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            summaries[idx] = future.result()
            completed += 1
            if stream_container is not None:
                stream_container.info(f"📊 並列処理中... {completed}/{len(all_chunks)} 完了")

    # --- Reduce phase (full model, streaming) ---
    combined_summaries = "\n\n".join(summaries)
    reduce_text = reduce_prompt.format(text=combined_summaries)

    llm = ChatOpenAI(model=model_choice, api_key=openai_api_key, temperature=0, streaming=True)
    log.info("Reduce phase started with %s (streaming)", model_choice)

    if stream_container is not None:
        result_chunks = []
        with stream_container:
            for chunk in llm.stream(reduce_text):
                result_chunks.append(chunk.content)
                stream_container.markdown("".join(result_chunks))
        return "".join(result_chunks)
    else:
        return llm.invoke(reduce_text).content


def extract_pdf_text(pdf_bytes: bytes, filename: str) -> str | None:
    """Extract text from PDF bytes. Falls back to OCR if no text is found.
    Returns the extracted text, or None if extraction failed."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = "".join([page.get_text("text") for page in doc])

    if text.strip():
        return text

    # Fallback: OCR via OpenAI Vision API
    if not openai_api_key:
        st.warning(f"{filename}: 画像PDFですがAPIキーが未設定のためOCR処理できません")
        return None

    log.info("No text found in %s, falling back to OCR", filename)
    st.info(f"{filename}: 画像PDFを検出しました。OCR処理中...")
    try:
        text = extract_text_with_ocr(pdf_bytes, openai_api_key)
        if text.strip():
            return text
        st.warning(f"{filename}: OCRでもテキストを抽出できませんでした")
        return None
    except Exception as e:
        log.error("OCR failed for %s: %s", filename, e)
        st.warning(f"{filename}: OCR処理に失敗しました: {e}")
        return None


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
                        text = extract_pdf_text(pdf_bytes, link["filename"])
                        if not text:
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
        st.session_state["video_url_input"] = choice

st.divider()

# -- 4b. Manual upload --
uploaded_file = st.file_uploader(
    "PDFファイルをアップロードしてキューに追加", type="pdf"
)

if uploaded_file:
    if not any(f[0] == uploaded_file.name for f in st.session_state.pdf_texts):
        with st.spinner(f"{uploaded_file.name} を解析中..."):
            pdf_bytes = uploaded_file.read()
            text = extract_pdf_text(pdf_bytes, uploaded_file.name)
            if text:
                st.session_state.pdf_texts.append((uploaded_file.name, text))
                save_cache()
                st.success(f"追加完了: {uploaded_file.name}")

if st.session_state.pdf_texts:
    col_header, col_clear = st.columns([0.8, 0.2])
    col_header.subheader("アップロード済みファイル")
    if col_clear.button("全てクリア", key="clear_pdf_queue"):
        st.session_state.pdf_texts = []
        st.session_state.summary_result = None
        st.session_state.pop("last_report_id", None)
        save_cache()
        st.rerun()

    for i, (name, _) in enumerate(st.session_state.pdf_texts):
        col1, col2 = st.columns([0.8, 0.2])
        col1.write(f"📄 {name}")
        if col2.button("削除", key=f"del_{i}"):
            st.session_state.pdf_texts.pop(i)
            save_cache()
            st.rerun()

    if st.button("🚀 要約レポートを作成する", type="primary"):
        if not openai_api_key:
            st.error("OPENAI_API_KEY が .env に設定されていません。管理者に連絡してください。")
        else:
            try:
                log.info("PDF summarization started by %s (%d files)", st.session_state.user_email, len(st.session_state.pdf_texts))
                texts = [content for _, content in st.session_state.pdf_texts]
                stream_box = st.empty()
                st.session_state.summary_result = run_summarization(
                    texts, MAP_PROMPT, REDUCE_PROMPT, stream_container=stream_box
                )
                stream_box.empty()
                log.info("PDF summarization completed")
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
    col_header, col_clear = st.columns([0.8, 0.2])
    col_header.subheader("生成されたレポート")
    if col_clear.button("クリア", key="clear_pdf_result"):
        st.session_state.summary_result = None
        st.session_state.pop("last_report_id", None)
        save_cache()
        st.rerun()

    st.markdown(st.session_state.summary_result)

    col_dl, col_link = st.columns([1, 1])
    col_dl.download_button(
        label="レポートをテキストとして保存",
        data=st.session_state.summary_result,
        file_name="summary_report.txt",
        mime="text/plain",
    )
    if st.session_state.get("last_report_id"):
        report_url = f"?sid={_get_session_id()}&view={st.session_state.last_report_id}"
        col_link.markdown(f"🔗 [このレポートの共有リンク]({report_url})")

# --- 6. Video Summary ---
st.divider()
st.subheader("🎥 動画要約")
if "_selected_video_url" in st.session_state and st.session_state["_selected_video_url"]:
    st.session_state["video_url_input"] = st.session_state.pop("_selected_video_url")
video_url = st.text_input(
    "YouTube URL",
    placeholder="例: https://www.youtube.com/watch?v=...",
    key="video_url_input",
)

if st.button("🎬 動画を要約する", type="secondary"):
    if not video_url:
        st.warning("YouTubeのURLを入力してください")
    elif not openai_api_key:
        st.error("OPENAI_API_KEY が .env に設定されていません。管理者に連絡してください。")
    else:
        try:
            log.info("Video summarization started by %s: %s", st.session_state.user_email, video_url)
            with st.spinner("字幕を取得中..."):
                video_id = extract_video_id(video_url)
                transcript = fetch_transcript(video_id)
            stream_box = st.empty()
            st.session_state.video_summary_result = run_summarization(
                [transcript], MAP_PROMPT, REDUCE_PROMPT, stream_container=stream_box
            )
            stream_box.empty()
            log.info("Video summarization completed")
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
    col_header, col_clear = st.columns([0.8, 0.2])
    col_header.markdown("### 📝 動画要約レポート")
    if col_clear.button("クリア", key="clear_video_result"):
        st.session_state.video_summary_result = None
        st.session_state.pop("last_video_report_id", None)
        save_cache()
        st.rerun()

    st.markdown(st.session_state.video_summary_result)

    col_dl, col_link = st.columns([1, 1])
    col_dl.download_button(
        label="動画要約をテキストとして保存",
        data=st.session_state.video_summary_result,
        file_name="video_summary_report.txt",
        mime="text/plain",
    )
    if st.session_state.get("last_video_report_id"):
        col_link.markdown(f"🔗 [この動画要約の共有リンク](?sid={_get_session_id()}&view={st.session_state.last_video_report_id})")

# --- 7. Shared Reports Library ---
def _render_report_list(reports: list[dict], search_query: str, source_type: str, page_key: str) -> None:
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
            col_link.markdown(f"[開く](?sid={_get_session_id()}&view={r['id']})")

    # Pagination controls
    total = count_reports(source_type)
    total_pages = max(1, (total + REPORTS_PER_PAGE - 1) // REPORTS_PER_PAGE)
    current_page = st.session_state.get(page_key, 1)
    if total_pages > 1:
        col_prev, col_info, col_next = st.columns([1, 2, 1])
        col_info.caption(f"ページ {current_page} / {total_pages}（全{total}件）")
        if col_prev.button("前のページ", key=f"{page_key}_prev", disabled=current_page <= 1):
            st.session_state[page_key] = current_page - 1
            st.rerun()
        if col_next.button("次のページ", key=f"{page_key}_next", disabled=current_page >= total_pages):
            st.session_state[page_key] = current_page + 1
            st.rerun()


st.divider()
with st.expander("📚 過去のPDFレポート一覧", expanded=False):
    pdf_search = st.text_input("🔍 レポート検索", placeholder="キーワードを入力...", key="pdf_search")
    pdf_page = st.session_state.get("pdf_report_page", 1)
    reports = search_reports(pdf_search, page=pdf_page) if pdf_search else list_reports(page=pdf_page)
    _render_report_list(reports, pdf_search, "pdf", "pdf_report_page")

st.divider()
with st.expander("🎥 過去の動画要約一覧", expanded=False):
    video_search = st.text_input("🔍 動画要約検索", placeholder="キーワードを入力...", key="video_search")
    video_page = st.session_state.get("video_report_page", 1)
    video_reports = search_video_reports(video_search, page=video_page) if video_search else list_video_reports(page=video_page)
    _render_report_list(video_reports, video_search, "video", "video_report_page")
