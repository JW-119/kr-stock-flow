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


@st.cache_data(ttl=3600, show_spinner="데이터 수집 중...")
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
    """원 단위 숫자를 억원 표시로 변환."""
    if pd.isna(value) or value == 0:
        return "0억"
    return f"{round(float(value) / 1e8):,}억"


def format_comma(value):
    """숫자에 3자리 콤마 추가."""
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value == int(value):
        return f"{int(value):,}"
    if isinstance(value, (int, float)):
        return f"{value:,}"
    return str(value)


def to_numeric_investor(df, col):
    """투자자 컬럼을 숫자로 변환 (원 단위 반환)."""
    if col not in df.columns:
        return pd.Series(0, index=df.index)
    s = df[col]
    if s.dtype in ("float64", "int64"):
        return s
    # 엑셀에서 읽은 경우: 억원 단위 콤마 문자열 → 콤마 제거 → 억 → 원으로 복원
    numeric = pd.to_numeric(
        s.astype(str).str.replace(",", ""), errors="coerce"
    ).fillna(0)
    return numeric * 1e8


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

st.caption("💡 금액 단위: 억원")
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
            "순매수(억원)": [v / 1e8 for v in bar_data.values()],
        })
        bar_df["색상"] = bar_df["순매수(억원)"].apply(lambda x: "매수" if x >= 0 else "매도")

        fig_bar = px.bar(
            bar_df, x="투자자", y="순매수(억원)",
            color="색상",
            color_discrete_map={"매수": "#2ca02c", "매도": "#d62728"},
            text=bar_df["순매수(억원)"].apply(lambda v: f"{round(v):,}억"),
        )
        fig_bar.update_layout(
            showlegend=False,
            yaxis_title="순매수 (억원)",
            height=400,
        )
        fig_bar.update_traces(textposition="outside")
        st.plotly_chart(fig_bar, width="stretch")


st.markdown("---")


# ── 3. 종목 수급 테이블 ────────────────────────────────────

st.subheader("종목별 수급 현황")
st.caption("💡 금액 단위: 억원")

display_cols = [c for c in config.COLUMN_ORDER if c in df.columns]
display_df = df[display_cols].copy()

# 금액 컬럼을 억원 숫자로 변환 (문자열 아닌 숫자 유지 → 정렬 가능)
money_cols = [c for c in display_df.columns
              if c in config.INVESTORS or c in ("시가총액", "거래대금")]
for col in money_cols:
    s = display_df[col]
    if s.dtype in ("float64", "int64"):
        display_df[col] = (s / 1e8).round(0).astype("int64", errors="ignore")

# column_config: 숫자 컬럼에 콤마 포맷 적용
col_config = {}
for col in ["종가", "거래량"]:
    if col in display_df.columns:
        col_config[col] = st.column_config.NumberColumn(col, format="%d")
for col in money_cols:
    if col in display_df.columns:
        col_config[col] = st.column_config.NumberColumn(col, format="%d")
if "등락률" in display_df.columns:
    col_config["등락률"] = st.column_config.NumberColumn("등락률", format="%.2f%%")
if "회전율" in display_df.columns:
    col_config["회전율"] = st.column_config.NumberColumn("회전율", format="%.4f%%")

st.dataframe(display_df, width="stretch", height=500,
             column_config=col_config)


st.markdown("---")


# ── 4. 수급 히트맵 ─────────────────────────────────────────

st.subheader("수급 히트맵 (상위 30종목)")

if selected_investors:
    # 주요 투자자 순매수 합계 기준 상위 30
    inv_cols = [c for c in selected_investors if c in df.columns]
    if inv_cols:
        # 주요 투자자(개인/외국인/기관합계)를 앞으로 정렬
        major = [c for c in config.MAJOR_INVESTORS if c in inv_cols]
        others = [c for c in inv_cols if c not in major]
        inv_cols = major + others

        heatmap_df = df.copy()
        for col in inv_cols:
            heatmap_df[col] = to_numeric_investor(heatmap_df, col)

        heatmap_df["_total"] = heatmap_df[inv_cols].sum(axis=1)
        top30 = heatmap_df.nlargest(30, "_total")

        if "종목명" in top30.columns:
            labels = top30["종목명"].tolist()
        else:
            labels = top30["티커"].tolist()

        # 억원 단위로 변환
        heat_values_억 = top30[inv_cols].values / 1e8

        # x축 라벨: 주요 투자자는 볼드
        x_labels = [
            f"<b>{c}</b>" if c in config.MAJOR_INVESTORS else c
            for c in inv_cols
        ]

        fig_heat = go.Figure(data=go.Heatmap(
            z=heat_values_억,
            x=x_labels,
            y=labels,
            colorscale="RdBu",
            zmid=0,
            text=[[f"{round(v):,}" for v in row] for row in heat_values_억],
            texttemplate="%{text}",
            hovertemplate="종목: %{y}<br>투자자: %{x}<br>순매수: %{text}억<extra></extra>",
        ))
        fig_heat.update_layout(
            height=max(400, len(labels) * 25),
            xaxis=dict(side="top"),
            yaxis=dict(autorange="reversed"),
            margin=dict(l=120, t=60),
        )
        st.plotly_chart(fig_heat, width="stretch")


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

        show_cols = ["티커", "종목명", "시장", "종가", "등락률", inv]
        show_cols = [c for c in show_cols if c in rank_df.columns]

        def _fmt_ranking(sub_df):
            out = sub_df[show_cols].reset_index(drop=True).copy()
            if "종가" in out.columns:
                out["종가"] = out["종가"].apply(format_comma)
            if inv in out.columns:
                s = out[inv]
                if s.dtype in ("float64", "int64"):
                    out[inv] = s.apply(lambda v: f"{round(v / 1e8):,}" if pd.notna(v) else "")
            return out

        # TOP 매수
        st.markdown(f"**{inv} 순매수 TOP 20** (억원)")
        top_buy = rank_df.nlargest(20, f"{inv}_num")
        st.dataframe(_fmt_ranking(top_buy), width="stretch")

        # TOP 매도
        st.markdown(f"**{inv} 순매도 TOP 20** (억원)")
        top_sell = rank_df.nsmallest(20, f"{inv}_num")
        st.dataframe(_fmt_ranking(top_sell), width="stretch")
