import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup  # 기사 요약용

# =========================
# 1. 기본 설정
# =========================

# 그룹별 키워드
RELATION_KEYWORDS = [
    "아이마켓코리아",
    "그래디언트",
    "테라펙스",
    "GBCC",
    "그래디언트바이오컨버전스",
    "안연케어",
]

CUSTOMER_KEYWORDS = [
    "삼성",
]

COMPETITOR_KEYWORDS = [
    "서브원",
    "코리아이플랫폼",
    "행복나래",
]

KEYWORDS = RELATION_KEYWORDS + CUSTOMER_KEYWORDS + COMPETITOR_KEYWORDS

NAVER_CLIENT_ID = "A4iaEzPgpbxGewkEWvyW"
NAVER_CLIENT_SECRET = "DPyZaHzOEZ"

# 🔹 SMTP 설정 (네이버 메일 기준 예시)
SMTP_SERVER = "smtp.naver.com"
SMTP_PORT = 587
SMTP_USER = "wjdeocjf1708@naver.com"
SMTP_PASSWORD = "여기에_네이버_메일_비밀번호_또는_앱비밀번호"
FROM_EMAIL = "wjdeocjf1708@naver.com"   # 요청하신 발신자 메일

st.set_page_config(
    page_title="뉴스 모니터링",
    page_icon="",
    layout="wide",
)

# 사이드바 / 카드 스타일
st.markdown(
    """
    <style>
    [data-testid="stSidebar"] > div:first-child {
        background-color: #1e3a8a;
        color: white;
    }
    [data-testid="stSidebar"] * {
        color: white !important;
    }
    [data-testid="stSidebar"] label span {
        color: white !important;
    }

    /* 카드 스타일 */
    .news-card, .scrap-card {
        border-radius: 12px;
        border: 1px solid #e5e7eb;
        padding: 0.7rem 0.9rem;
        margin-bottom: 0.6rem;
        background-color: #f9fafb;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }
    .news-card-title {
        font-weight: 600;
        font-size: 0.95rem;
        margin-bottom: 0.15rem;
    }
    .news-card-meta {
        font-size: 0.8rem;
        color: #6b7280;
    }

    /* 🔹 사이드바 입력창/버튼 글씨는 검정색으로 */
    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] textarea {
        color: black !important;
    }
    [data-testid="stSidebar"] button[kind="secondary"],
    [data-testid="stSidebar"] button[kind="primary"],
    [data-testid="stSidebar"] button {
        color: black !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("뉴스 모니터링")
st.write(
    "한시간 단위 자동 업데이트 "
)

# =========================
# 유틸 함수들
# =========================

def widget_key(prefix: str, link: str) -> str:
    return f"{prefix}_{abs(hash(link))}"

def fetch_news_for_keyword(keyword: str, display: int = 30, sort: str = "date"):
    base_url = "https://openapi.naver.com/v1/search/news.json"
    params = {"query": keyword, "display": display, "sort": sort}
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    res = requests.get(base_url, params=params, headers=headers)
    if res.status_code != 200:
        st.warning(f"[{keyword}] 뉴스 요청 실패 (status: {res.status_code})")
        return []

    items = res.json().get("items", [])
    results = []
    for item in items:
        title = re.sub("<.*?>", "", item.get("title", ""))
        if keyword.lower() not in title.lower():
            continue
        link = item.get("link", "")
        pub_str = item.get("pubDate", "")
        pub_dt = None
        if pub_str:
            try:
                pub_dt = datetime.strptime(
                    pub_str, "%a, %d %b %Y %H:%M:%S %z"
                ).astimezone()
            except Exception:
                pass
        results.append(
            {"keyword": keyword, "title": title, "link": link, "published": pub_dt}
        )
    return results

def fetch_all_news():
    all_items = []
    for kw in KEYWORDS:
        all_items.extend(fetch_news_for_keyword(kw))
    if not all_items:
        return pd.DataFrame(columns=["keyword", "title", "link", "published"])
    df = pd.DataFrame(all_items).drop_duplicates("link")
    return df.sort_values("published", ascending=False, na_position="last")

# 🔹 체크된 기사만 메일 발송하는 함수
def send_email(to_email: str, keyword_label: str, df: pd.DataFrame):
    if df.empty:
        raise ValueError("메일로 보낼 기사 데이터가 없습니다.")

    # 제목 고정: "Daily 뉴스"
    subject = "Daily 뉴스"

    lines = []
    lines.append(f"조건: {keyword_label}")
    lines.append("")
    lines.append("기사 목록:")
    lines.append("-" * 40)

    for _, row in df.iterrows():
        title = row["title"]
        link = row["link"]
        kw = row.get("keyword", "")
        pub_str = ""
        if pd.notnull(row["published"]):
            pub_str = row["published"].strftime("%Y-%m-%d %H:%M")
        lines.append(f"- [{kw}] {title}")
        lines.append(f"  · 날짜: {pub_str}")
        lines.append(f"  · 링크: {link}")
        lines.append("")

    body = "\n".join(lines)

    msg = MIMEMultipart()
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", _charset="utf-8"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)

# 🔹 기사 요약 추출 함수
def get_article_summary(url: str) -> str:
    try:
        res = requests.get(url, timeout=5)
        if res.status_code != 200:
            return "요약을 불러오지 못했습니다. (사이트 응답 오류)"

        soup = BeautifulSoup(res.text, "html.parser")

        og_desc = soup.find("meta", attrs={"property": "og:description"})
        if og_desc and og_desc.get("content"):
            text = og_desc["content"].strip()
        else:
            body = soup.find(id="dic_area") or soup.find("div", {"class": "newsct_article"})
            if body:
                text = body.get_text(" ", strip=True)
            else:
                text = soup.get_text(" ", strip=True)

        text = re.sub(r"\s+", " ", text)
        if len(text) > 400:
            text = text[:400] + " ..."
        if not text:
            return "요약할 수 있는 본문을 찾지 못했습니다."
        return text
    except Exception:
        return "요약을 불러오는 중 오류가 발생했습니다."

# =========================
# 세션 상태 초기화
# =========================

if "last_update" not in st.session_state:
    st.session_state["last_update"] = None
if "history_df" not in st.session_state:
    st.session_state["history_df"] = pd.DataFrame(
        columns=["keyword", "title", "link", "published"]
    )
if "scrap_df" not in st.session_state:
    st.session_state["scrap_df"] = pd.DataFrame(
        columns=["keyword", "title", "link", "published"]
    )
# 요약 패널용 상태
if "summary_info" not in st.session_state:
    st.session_state["summary_info"] = None
if "summary_text" not in st.session_state:
    st.session_state["summary_text"] = None

# =========================
# 상단 컨트롤 (업데이트 + 스크랩 버튼)
# =========================

top_col1, top_col2, top_col3 = st.columns([1, 1, 3])

with top_col1:
    manual_refresh = st.button("수동 업데이트")

with top_col2:
    scrap_button_top = st.button("기사 스크랩")

with top_col3:
    if st.session_state["last_update"]:
        st.caption(
            "마지막 업데이트: "
            + st.session_state["last_update"].strftime("%Y-%m-%d %H:%M:%S")
        )
    else:
        st.caption("아직 업데이트된 적이 없습니다.")

def load_data():
    df_new = fetch_all_news()
    if not df_new.empty:
        st.session_state["history_df"] = (
            pd.concat([st.session_state["history_df"], df_new])
            .drop_duplicates("link")
            .sort_values("published", ascending=False, na_position="last")
        )
    st.session_state["last_update"] = datetime.now().astimezone()

last = st.session_state["last_update"]
need_refresh = not last or (datetime.now().astimezone() - last > timedelta(hours=1))
if manual_refresh or need_refresh:
    with st.spinner("네이버 뉴스 가져오는 중..."):
        load_data()

history_df = st.session_state["history_df"]

# =========================
# 사이드바: 모드 + 메일
# =========================

with st.sidebar:
    st.header("보기 모드")
    mode = st.radio(
        "카테고리 선택",
        ["전체", "관계사 동향", "고객사 동향", "경쟁사 동향", "스크랩"],
        index=0,
    )

    if mode != "스크랩":
        st.markdown("---")
        recipient_email = st.text_input(
            "받는 사람 이메일", placeholder="example@imarketkorea.com"
        )
        send_mail_button = st.button("현재 화면 기사 메일 발송")
    else:
        recipient_email = None
        send_mail_button = False

# =========================
# 요약 패널 렌더링 함수
# =========================

def render_summary_panel():
    st.markdown("#### 기사 요약")
    info = st.session_state.get("summary_info")
    text = st.session_state.get("summary_text")

    if not info:
        st.info("요약을 보고 싶은 기사의 '요약 보기' 버튼을 눌러주세요.")
        return

    title = info.get("title", "")
    link = info.get("link", "")
    keyword = info.get("keyword", "")
    published = info.get("published", None)

    if isinstance(published, datetime):
        pub_str = published.strftime("%Y-%m-%d %H:%M")
    else:
        pub_str = ""

    st.markdown(f"**{title}**")
    if link:
        st.markdown(f"[기사 링크 바로가기]({link})")
    meta_line = " · ".join(x for x in [keyword, pub_str] if x)
    if meta_line:
        st.caption(meta_line)

    st.write(text or "요약 내용을 가져오지 못했습니다.")

# =========================
# 메인: 뉴스 모드 (전체 + 3그룹)
# =========================

if mode != "스크랩":

    if mode == "전체":
        df_view = history_df.copy()
        group_label = "전체 동향"
    elif mode == "관계사 동향":
        df_view = history_df[history_df["keyword"].isin(RELATION_KEYWORDS)]
        group_label = "관계사 동향"
    elif mode == "고객사 동향":
        df_view = history_df[history_df["keyword"].isin(CUSTOMER_KEYWORDS)]
        group_label = "고객사 동향"
    else:  # 경쟁사 동향
        df_view = history_df[history_df["keyword"].isin(COMPETITOR_KEYWORDS)]
        group_label = "경쟁사 동향"

    st.subheader(f"{group_label} 기사 목록")

    main_col, summary_col = st.columns([3, 1])

    with summary_col:
        render_summary_panel()

    selected_links = []

    with main_col:
        if df_view.empty:
            st.info("현재 조건에 해당하는 뉴스가 없습니다.")
        else:
            if mode == "전체":
                # 관계사 블록
                relation_df = df_view[df_view["keyword"].isin(RELATION_KEYWORDS)]
                st.markdown("#### 관계사 동향")
                if relation_df.empty:
                    st.caption("관계사 관련 기사가 없습니다.")
                else:
                    cols_rel = st.columns(len(RELATION_KEYWORDS))
                    for kw, col in zip(RELATION_KEYWORDS, cols_rel):
                        with col:
                            st.markdown(f"**{kw}**")
                            df_kw = relation_df[relation_df["keyword"] == kw]
                            if df_kw.empty:
                                st.caption("기사 없음")
                            else:
                                for _, row in df_kw.iterrows():
                                    link = row["link"]
                                    pub = row["published"]
                                    pub_str = (
                                        pub.strftime("%Y-%m-%d %H:%M")
                                        if pd.notnull(pub)
                                        else ""
                                    )
                                    ck = widget_key("select", link)
                                    summary_key = widget_key("summary", link)

                                    st.markdown('<div class="news-card">', unsafe_allow_html=True)
                                    c1, c2 = st.columns([0.2, 0.8])
                                    with c1:
                                        checked = st.checkbox("", key=ck)
                                    with c2:
                                        st.markdown(
                                            f'<div class="news-card-title"><a href="{link}" target="_blank">{row["title"]}</a></div>',
                                            unsafe_allow_html=True,
                                        )
                                        st.markdown(
                                            f'<div class="news-card-meta">{pub_str}</div>',
                                            unsafe_allow_html=True,
                                        )
                                    if st.button("요약 보기", key=summary_key):
                                        st.session_state["summary_info"] = {
                                            "title": row["title"],
                                            "link": link,
                                            "keyword": row["keyword"],
                                            "published": pub,
                                        }
                                        st.session_state["summary_text"] = get_article_summary(link)
                                    st.markdown("</div>", unsafe_allow_html=True)

                                    if checked:
                                        selected_links.append(link)

                st.markdown("---")

                # 고객사 블록
                customer_df = df_view[df_view["keyword"].isin(CUSTOMER_KEYWORDS)]
                st.markdown("#### 고객사 동향")
                if customer_df.empty:
                    st.caption("고객사 관련 기사가 없습니다.")
                else:
                    for _, row in customer_df.iterrows():
                        link = row["link"]
                        pub = row["published"]
                        pub_str = (
                            pub.strftime("%Y-%m-%d %H:%M") if pd.notnull(pub) else ""
                        )
                        ck = widget_key("select", link)
                        summary_key = widget_key("summary", link)

                        st.markdown('<div class="news-card">', unsafe_allow_html=True)
                        c1, c2 = st.columns([0.08, 0.92])
                        with c1:
                            checked = st.checkbox("", key=ck)
                        with c2:
                            st.markdown(
                                f'<div class="news-card-title"><a href="{link}" target="_blank">{row["title"]}</a></div>',
                                unsafe_allow_html=True,
                            )
                            st.markdown(
                                f'<div class="news-card-meta">{pub_str} · {row["keyword"]}</div>',
                                unsafe_allow_html=True,
                            )
                        if st.button("요약 보기", key=summary_key):
                            st.session_state["summary_info"] = {
                                "title": row["title"],
                                "link": link,
                                "keyword": row["keyword"],
                                "published": pub,
                            }
                            st.session_state["summary_text"] = get_article_summary(link)
                        st.markdown("</div>", unsafe_allow_html=True)

                        if checked:
                            selected_links.append(link)

                st.markdown("---")

                # 경쟁사 블록
                competitor_df = df_view[df_view["keyword"].isin(COMPETITOR_KEYWORDS)]
                st.markdown("#### 경쟁사 동향")
                if competitor_df.empty:
                    st.caption("경쟁사 관련 기사가 없습니다.")
                else:
                    cols_comp = st.columns(len(COMPETITOR_KEYWORDS))
                    for kw, col in zip(COMPETITOR_KEYWORDS, cols_comp):
                        with col:
                            st.markdown(f"**{kw}**")
                            df_kw = competitor_df[competitor_df["keyword"] == kw]
                            if df_kw.empty:
                                st.caption("기사 없음")
                            else:
                                for _, row in df_kw.iterrows():
                                    link = row["link"]
                                    pub = row["published"]
                                    pub_str = (
                                        pub.strftime("%Y-%m-%d %H:%M")
                                        if pd.notnull(pub)
                                        else ""
                                    )
                                    ck = widget_key("select", link)
                                    summary_key = widget_key("summary", link)

                                    st.markdown('<div class="news-card">', unsafe_allow_html=True)
                                    c1, c2 = st.columns([0.2, 0.8])
                                    with c1:
                                        checked = st.checkbox("", key=ck)
                                    with c2:
                                        st.markdown(
                                            f'<div class="news-card-title"><a href="{link}" target="_blank">{row["title"]}</a></div>',
                                            unsafe_allow_html=True,
                                        )
                                        st.markdown(
                                            f'<div class="news-card-meta">{pub_str}</div>',
                                            unsafe_allow_html=True,
                                        )
                                    if st.button("요약 보기", key=summary_key):
                                        st.session_state["summary_info"] = {
                                            "title": row["title"],
                                            "link": link,
                                            "keyword": row["keyword"],
                                            "published": pub,
                                        }
                                        st.session_state["summary_text"] = get_article_summary(link)
                                    st.markdown("</div>", unsafe_allow_html=True)

                                    if checked:
                                        selected_links.append(link)

            else:
                # 개별 모드 (관계사/고객사/경쟁사 중 하나)
                if mode == "관계사 동향":
                    group_keywords = RELATION_KEYWORDS
                elif mode == "고객사 동향":
                    group_keywords = CUSTOMER_KEYWORDS
                else:
                    group_keywords = COMPETITOR_KEYWORDS

                if len(group_keywords) > 1:
                    cols = st.columns(len(group_keywords))
                    for kw, col in zip(group_keywords, cols):
                        with col:
                            st.markdown(f"**{kw}**")
                            df_kw = df_view[df_view["keyword"] == kw]
                            if df_kw.empty:
                                st.caption("기사 없음")
                            else:
                                for _, row in df_kw.iterrows():
                                    link = row["link"]
                                    pub = row["published"]
                                    pub_str = (
                                        pub.strftime("%Y-%m-%d %H:%M")
                                        if pd.notnull(pub)
                                        else ""
                                    )
                                    ck = widget_key("select", link)
                                    summary_key = widget_key("summary", link)

                                    st.markdown('<div class="news-card">', unsafe_allow_html=True)
                                    c1, c2 = st.columns([0.2, 0.8])
                                    with c1:
                                        checked = st.checkbox("", key=ck)
                                    with c2:
                                        st.markdown(
                                            f'<div class="news-card-title"><a href="{link}" target="_blank">{row["title"]}</a></div>',
                                            unsafe_allow_html=True,
                                        )
                                        st.markdown(
                                            f'<div class="news-card-meta">{pub_str}</div>',
                                            unsafe_allow_html=True,
                                        )
                                    if st.button("요약 보기", key=summary_key):
                                        st.session_state["summary_info"] = {
                                            "title": row["title"],
                                            "link": link,
                                            "keyword": row["keyword"],
                                            "published": pub,
                                        }
                                        st.session_state["summary_text"] = get_article_summary(link)
                                    st.markdown("</div>", unsafe_allow_html=True)

                                    if checked:
                                        selected_links.append(link)
                else:
                    # 키워드 하나 (예: 삼성)
                    for _, row in df_view.iterrows():
                        link = row["link"]
                        pub = row["published"]
                        pub_str = (
                            pub.strftime("%Y-%m-%d %H:%M") if pd.notnull(pub) else ""
                        )
                        ck = widget_key("select", link)
                        summary_key = widget_key("summary", link)

                        st.markdown('<div class="news-card">', unsafe_allow_html=True)
                        c1, c2 = st.columns([0.08, 0.92])
                        with c1:
                            checked = st.checkbox("", key=ck)
                        with c2:
                            st.markdown(
                                f'<div class="news-card-title"><a href="{link}" target="_blank">{row["title"]}</a></div>',
                                unsafe_allow_html=True,
                            )
                            st.markdown(
                                f'<div class="news-card-meta">{pub_str} · {row["keyword"]}</div>',
                                unsafe_allow_html=True,
                            )
                        if st.button("요약 보기", key=summary_key):
                            st.session_state["summary_info"] = {
                                "title": row["title"],
                                "link": link,
                                "keyword": row["keyword"],
                                "published": pub,
                            }
                            st.session_state["summary_text"] = get_article_summary(link)
                        st.markdown("</div>", unsafe_allow_html=True)

                        if checked:
                            selected_links.append(link)

    # 🔹 선택 기사 스크랩 저장
    if scrap_button_top:
        if not selected_links:
            st.warning("스크랩할 기사를 하나 이상 선택하세요.")
        else:
            new = history_df[history_df["link"].isin(selected_links)]
            st.session_state["scrap_df"] = (
                pd.concat([st.session_state["scrap_df"], new])
                .drop_duplicates("link")
                .sort_values("published", ascending=False, na_position="last")
            )
            st.success(f"{len(new)}개 기사를 스크랩함에 저장했습니다.")

    # 🔹 메일 발송: 선택된 기사만
    if send_mail_button:
        if not recipient_email:
            st.warning("받는 사람 이메일을 입력하세요.")
        elif not selected_links:
            st.warning("메일로 보낼 기사를 하나 이상 선택하세요.")
        else:
            df_send = df_view[df_view["link"].isin(selected_links)]
            if df_send.empty:
                st.warning("선택한 기사 데이터가 없습니다.")
            else:
                try:
                    send_email(recipient_email, group_label, df_send)
                    st.success(f"{recipient_email} 주소로 Daily 뉴스 메일을 발송했습니다.")
                except Exception as e:
                    st.error(f"메일 발송 중 오류가 발생했습니다: {e}")

    # 표 보기
    st.markdown("---")
    st.markdown("표 형태로 보기")
    table_df = df_view.copy()
    if table_df["published"].notnull().any():
        table_df["published"] = table_df["published"].dt.strftime(
            "%Y-%m-%d %H:%M"
        )
    else:
        table_df["published"] = ""
    table_df = table_df[["keyword", "published", "title", "link"]]
    st.dataframe(table_df, use_container_width=True, hide_index=True)

# =========================
# 스크랩 모드
# =========================

else:
    st.subheader("스크랩한 기사 목록")
    scrap_df = st.session_state["scrap_df"]
    if scrap_df.empty:
        st.info("스크랩한 기사가 없습니다.")
    else:
        del_links = []
        for _, row in scrap_df.iterrows():
            link = row["link"]
            pub = row["published"]
            pub_str = (
                pub.strftime("%Y-%m-%d %H:%M") if pd.notnull(pub) else ""
            )
            ck = widget_key("scrapdel", link)

            st.markdown('<div class="scrap-card">', unsafe_allow_html=True)
            c1, c2 = st.columns([0.08, 0.92])
            with c1:
                checked = st.checkbox("", key=ck)
            with c2:
                st.markdown(
                    f'<div class="news-card-title"><a href="{link}" target="_blank">{row["title"]}</a></div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div class="news-card-meta">{pub_str} · {row["keyword"]}</div>',
                    unsafe_allow_html=True,
                )
            st.markdown("</div>", unsafe_allow_html=True)

            if checked:
                del_links.append(link)

        if st.button("선택한 스크랩 삭제"):
            st.session_state["scrap_df"] = scrap_df[
                ~scrap_df["link"].isin(del_links)
            ]
            st.success(f"{len(del_links)}개 스크랩을 삭제했습니다.")
