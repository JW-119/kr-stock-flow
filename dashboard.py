"""Streamlit 대시보드 — 국내 주식 투자자별 수급."""

import os
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import config
import collector

st.set_page_config(page_title="국내 주식 수급", page_icon="📊", layout="wide")
st.title("📊 국내 주식 투자자별 수급 현황")


# ── 데이터 로딩 ─────────────────────────────────────────────

def _load_from_excel(date_str: str) -> pd.DataFrame:
    """로컬 엑셀 파일에서 데이터 로드."""
    path = os.path.join(config.DATA_DIR, f"수급_{date_str}.xlsx")
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        df = pd.read_excel(path, sheet_name="전체", header=1)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def _collect_live(date_str: str) -> pd.DataFrame:
    """pykrx 실시간 수집 (Streamlit Cloud용)."""
    return collector.collect(date_str)


def load_data(date_str: str) -> pd.DataFrame:
    """데이터 로드 (엑셀 우선, 없으면 실시간 수집)."""
    df = _load_from_excel(date_str)
    if not df.empty:
        return df
    return _collect_live(date_str)


# ── 사이드바 ────────────────────────────────────────────────

with st.sidebar:
    st.header("설정")

    # 날짜 선택
    today = datetime.now()
    selected_date = st.date_input(
        "날짜 선택",
        value=today,
        max_value=today,
        min_value=today - timedelta(days=365),
    )
    date_str = selected_date.strftime("%Y%m%d")

    # 시장 필터
    market_filter = st.selectbox("시장", ["전체", "KOSPI", "KOSDAQ"])

    # 투자자 선택 (히트맵/바차트용)
    selected_investors = st.multiselect(
        "투자자 선택",
        options=config.INVESTORS,
        default=config.MAJOR_INVESTORS,
    )

    # 종목 검색
    search_query = st.text_input("종목 검색 (이름 또는 티커)")


# ── 데이터 로드 & 필터 ──────────────────────────────────────

with st.spinner("데이터 수집 중..."):
    df = load_data(date_str)

if df.empty:
    st.warning("해당 날짜의 데이터가 없습니다. 휴장일이거나 날짜를 확인해 주세요.")
    st.stop()

# 시장 필터
if market_filter != "전체" and "시장" in df.columns:
    df = df[df["시장"] == market_filter]

# 종목 검색
if search_query:
    mask = pd.Series(False, index=df.index)
    if "종목명" in df.columns:
        mask |= df["종목명"].str.contains(search_query, case=False, na=False)
    if "티커" in df.columns:
        mask |= df["티커"].str.contains(search_query, case=False, na=False)
    df = df[mask]

if df.empty:
    st.info("검색 결과가 없습니다.")
    st.stop()


# ── 유틸 함수 ───────────────────────────────────────────────

def format_억(value):
    """숫자를 억 단위로 표시."""
    if pd.isna(value) or value == 0:
        return "0"
    if abs(value) >= 1e12:
        return f"{value / 1e12:.2f}조"
    if abs(value) >= 1e8:
        return f"{value / 1e8:.1f}억"
    return f"{value:,.0f}"


def to_numeric_investor(df, col):
    """투자자 컬럼을 숫자로 변환 (문자열 포맷 → 원래 값)."""
    if col not in df.columns:
        return pd.Series(0, index=df.index)
    s = df[col]
    if s.dtype in ("float64", "int64"):
        return s
    # 문자열이면 단위 변환 시도
    return pd.to_numeric(s.astype(str).str.replace(r"[조억만,]", "", regex=True),
                         errors="coerce").fillna(0)


# ── 1. 시장 요약 metrics ────────────────────────────────────

st.subheader("시장 요약")
metric_cols = st.columns(len(config.MAJOR_INVESTORS))
for i, inv in enumerate(config.MAJOR_INVESTORS):
    if inv in df.columns:
        vals = to_numeric_investor(df, inv)
        total = vals.sum()
        metric_cols[i].metric(
            label=f"{inv} 총 순매수",
            value=format_억(total),
        )

st.markdown("---")


# ── 2. 투자자별 순매수 총액 바차트 ─────────────────────────

st.subheader("투자자별 순매수 총액")

if selected_investors:
    bar_data = {}
    for inv in selected_investors:
        if inv in df.columns:
            bar_data[inv] = to_numeric_investor(df, inv).sum()

    if bar_data:
        bar_df = pd.DataFrame({
            "투자자": list(bar_data.keys()),
            "순매수(원)": list(bar_data.values()),
        })
        bar_df["색상"] = bar_df["순매수(원)"].apply(lambda x: "매수" if x >= 0 else "매도")

        fig_bar = px.bar(
            bar_df, x="투자자", y="순매수(원)",
            color="색상",
            color_discrete_map={"매수": "#2ca02c", "매도": "#d62728"},
            text=bar_df["순매수(원)"].apply(format_억),
        )
        fig_bar.update_layout(
            showlegend=False,
            yaxis_title="순매수 금액",
            height=400,
        )
        fig_bar.update_traces(textposition="outside")
        st.plotly_chart(fig_bar, use_container_width=True)


st.markdown("---")


# ── 3. 종목 수급 테이블 ────────────────────────────────────

st.subheader("종목별 수급 현황")

display_cols = [c for c in config.COLUMN_ORDER if c in df.columns]
display_df = df[display_cols].copy()

# 등락률 포맷
if "등락률" in display_df.columns:
    display_df["등락률"] = display_df["등락률"].apply(
        lambda x: f"{x:+.2f}%" if isinstance(x, (int, float)) else x
    )

# 회전율 포맷
if "회전율" in display_df.columns:
    display_df["회전율"] = display_df["회전율"].apply(
        lambda x: f"{x:.4f}%" if isinstance(x, (int, float)) else x
    )

st.dataframe(display_df, use_container_width=True, height=500)


st.markdown("---")


# ── 4. 수급 히트맵 ─────────────────────────────────────────

st.subheader("수급 히트맵 (상위 30종목)")

if selected_investors:
    # 주요 투자자 순매수 합계 기준 상위 30
    inv_cols = [c for c in selected_investors if c in df.columns]
    if inv_cols:
        heatmap_df = df.copy()
        for col in inv_cols:
            heatmap_df[col] = to_numeric_investor(heatmap_df, col)

        heatmap_df["_total"] = heatmap_df[inv_cols].sum(axis=1)
        top30 = heatmap_df.nlargest(30, "_total")

        if "종목명" in top30.columns:
            labels = top30["종목명"].tolist()
        else:
            labels = top30["티커"].tolist()

        heat_values = top30[inv_cols].values

        fig_heat = go.Figure(data=go.Heatmap(
            z=heat_values,
            x=inv_cols,
            y=labels,
            colorscale="RdBu",
            zmid=0,
            text=[[format_억(v) for v in row] for row in heat_values],
            texttemplate="%{text}",
            hovertemplate="종목: %{y}<br>투자자: %{x}<br>순매수: %{text}<extra></extra>",
        ))
        fig_heat.update_layout(
            height=max(400, len(labels) * 25),
            yaxis=dict(autorange="reversed"),
            margin=dict(l=120),
        )
        st.plotly_chart(fig_heat, use_container_width=True)


st.markdown("---")


# ── 5. 랭킹 탭 ────────────────────────────────────────────

st.subheader("순매수 랭킹")

ranking_investors = ["외국인", "기관합계", "개인", "연기금"]
tabs = st.tabs(ranking_investors)

for tab, inv in zip(tabs, ranking_investors):
    with tab:
        if inv not in df.columns:
            st.info(f"{inv} 데이터 없음")
            continue

        rank_df = df.copy()
        rank_df[f"{inv}_num"] = to_numeric_investor(rank_df, inv)

        # TOP 매수
        st.markdown(f"**{inv} 순매수 TOP 20**")
        top_buy = rank_df.nlargest(20, f"{inv}_num")
        show_cols = ["티커", "종목명", "시장", "종가", "등락률", inv]
        show_cols = [c for c in show_cols if c in top_buy.columns]
        st.dataframe(top_buy[show_cols].reset_index(drop=True),
                     use_container_width=True)

        # TOP 매도
        st.markdown(f"**{inv} 순매도 TOP 20**")
        top_sell = rank_df.nsmallest(20, f"{inv}_num")
        st.dataframe(top_sell[show_cols].reset_index(drop=True),
                     use_container_width=True)
