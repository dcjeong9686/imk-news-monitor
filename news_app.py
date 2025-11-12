import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# =========================
# 1. 기본 설정
# =========================

KEYWORDS = ["아이마켓코리아", "그래디언트", "삼성", "서브원"]

NAVER_CLIENT_ID = "A4iaEzPgpbxGewkEWvyW"
NAVER_CLIENT_SECRET = "DPyZaHzOEZ"

SMTP_SERVER = "smtp.your-company.com"
SMTP_PORT = 587
SMTP_USER = "dc.jeong@imarketkorea.com"
SMTP_PASSWORD = "여기에_메일_비밀번호_또는_앱비밀번호"
FROM_EMAIL = SMTP_USER

st.set_page_config(
    page_title="뉴스 모니터링",
    page_icon="",
    layout="wide",
)

# 사이드바 스타일 (밝은 파란색 배경 + 흰 글씨)
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

    /* 카드 스타일: 둥근 사각형 + 연한 테두리 + 약간의 그림자 */
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
    </style>
    """,
    unsafe_allow_html=True
)

st.title("뉴스 모니터링")
st.write(
    "지정한 키워드를 기준으로 한시간 간격 자동업데이트 됩니다. "
)

# =========================
# 유틸
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

def send_email(to_email: str, keyword_label: str, df: pd.DataFrame):
    if df.empty:
        raise ValueError("메일로 보낼 기사 데이터가 없습니다.")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    subject = f"[키워드 뉴스] {keyword_label} 기사 목록 - {now_str}"
    lines = [f"조건: {keyword_label}", "", "기사 목록:", "-" * 40]
    for _, row in df.iterrows():
        pub_str = (
            row["published"].strftime("%Y-%m-%d %H:%M")
            if pd.notnull(row["published"])
            else ""
        )
        lines += [
            f"- [{row['keyword']}] {row['title']}",
            f"  · 날짜: {pub_str}",
            f"  · 링크: {row['link']}",
            "",
        ]
    body = "\n".join(lines)
    msg = MIMEMultipart()
    msg["From"], msg["To"], msg["Subject"] = FROM_EMAIL, to_email, subject
    msg.attach(MIMEText(body, "plain", _charset="utf-8"))
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)

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

# =========================
# 상단 컨트롤 (업데이트 + 스크랩 버튼)
# =========================

top_col1, top_col2, top_col3 = st.columns([1, 1, 3])

with top_col1:
    manual_refresh = st.button("업데이트")

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
    with st.spinner("뉴스 가져오는 중..."):
        load_data()

# =========================
# 사이드바
# =========================

with st.sidebar:
    st.header("보기")
    mode = st.radio("모드", ["뉴스", "스크랩"], index=0)
    if mode == "뉴스":
        st.markdown("---")
        keyword_choice = st.radio("키워드 선택", ["전체"] + KEYWORDS, index=0)
        st.markdown("---")
        recipient_email = st.text_input(
            "받는 사람 이메일", placeholder="example@imarketkorea.com"
        )
        send_mail_button = st.button("현재 화면 기사 메일 발송")
    else:
        keyword_choice, recipient_email, send_mail_button = None, None, False

# =========================
# 메인: 뉴스 모드
# =========================

if mode == "뉴스":
    df_view = st.session_state["history_df"]
    if keyword_choice != "전체":
        df_view = df_view[df_view["keyword"] == keyword_choice]

    st.subheader(
        "전체 키워드 기사 목록"
        if keyword_choice == "전체"
        else f"'{keyword_choice}' 키워드 기사 목록"
    )

    if df_view.empty:
        st.info("현재 조건에 해당하는 뉴스가 없습니다.")
    else:
        selected_links = []

        # 전체일 때: 키워드별 가로 컬럼 + 카드형
        if keyword_choice == "전체":
            cols = st.columns(len(KEYWORDS))
            for kw, col in zip(KEYWORDS, cols):
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

                            st.markdown('<div class="news-card">', unsafe_allow_html=True)
                            c1, c2 = st.columns([0.18, 0.82])
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
                            st.markdown("</div>", unsafe_allow_html=True)

                            if checked:
                                selected_links.append(link)
        else:
            # 단일 키워드: 카드형 세로 리스트
            for _, row in df_view.iterrows():
                link = row["link"]
                pub = row["published"]
                pub_str = (
                    pub.strftime("%Y-%m-%d %H:%M") if pd.notnull(pub) else ""
                )
                ck = widget_key("select", link)

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
                st.markdown("</div>", unsafe_allow_html=True)

                if checked:
                    selected_links.append(link)

        # 상단 스크랩 버튼 동작
        if scrap_button_top:
            if not selected_links:
                st.warning("스크랩할 기사를 하나 이상 선택해주세요.")
            else:
                new = st.session_state["history_df"][
                    st.session_state["history_df"]["link"].isin(selected_links)
                ]
                st.session_state["scrap_df"] = (
                    pd.concat([st.session_state["scrap_df"], new])
                    .drop_duplicates("link")
                    .sort_values("published", ascending=False, na_position="last")
                )
                st.success(f"{len(new)}개 기사를 스크랩함에 저장했습니다.")

        # 표 보기
        st.markdown("---")
        st.markdown("표 형태로 보기")
        df_table = df_view.copy()
        if df_table["published"].notnull().any():
            df_table["published"] = df_table["published"].dt.strftime("%Y-%m-%d %H:%M")
        else:
            df_table["published"] = ""
        df_table = df_table[["keyword", "published", "title", "link"]]
        st.dataframe(df_table, use_container_width=True, hide_index=True)

        # 메일 발송
        if send_mail_button:
            try:
                label = keyword_choice if keyword_choice != "전체" else "전체 키워드"
                send_email(recipient_email, label, df_view)
                st.success("메일 발송을 완료했습니다.")
            except Exception as e:
                st.error(f"메일 발송 중 오류: {e}")

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
