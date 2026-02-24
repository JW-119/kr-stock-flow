"""pykrx 기반 투자자별 수급 데이터 수집 모듈."""

import time

import pandas as pd
from pykrx import stock

import config


def _retry(func, *args, max_retries=config.MAX_RETRIES, **kwargs):
    """API 호출 재시도 래퍼."""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"[Collector] 최종 실패: {func.__name__}{args} — {e}")
                return pd.DataFrame()
            wait = config.RETRY_BASE_DELAY * (2 ** attempt)
            print(f"[Collector] 재시도 {attempt + 1}/{max_retries}: {e} ({wait:.1f}s 대기)")
            time.sleep(wait)
    return pd.DataFrame()


def collect(date: str, progress_callback=None) -> pd.DataFrame:
    """지정 날짜의 전 종목 수급 데이터를 수집.

    Args:
        date: 날짜 (YYYYMMDD 형식)
        progress_callback: 진행률 콜백 (ratio: float, message: str)

    Returns:
        전 종목 수급 DataFrame
    """
    total_steps = len(config.MARKETS) * (len(config.INVESTORS) + 2)
    current_step = 0

    def _progress(msg):
        nonlocal current_step
        current_step += 1
        ratio = current_step / total_steps
        if progress_callback:
            progress_callback(ratio, msg)
        else:
            print(f"[Collector] ({current_step}/{total_steps}) {msg}")

    all_data = []

    for market in config.MARKETS:
        # 1) 시가총액 데이터 (종가, 시가총액, 거래량, 거래대금, 상장주식수)
        _progress(f"{market} 시가총액 데이터 수집")
        cap_df = _retry(stock.get_market_cap_by_ticker, date, market=market)
        time.sleep(config.REQUEST_DELAY)

        # 2) OHLCV 데이터 (등락률)
        _progress(f"{market} 등락률 데이터 수집")
        ohlcv_df = _retry(stock.get_market_ohlcv_by_ticker, date, market=market)
        time.sleep(config.REQUEST_DELAY)

        if cap_df.empty or ohlcv_df.empty:
            for inv in config.INVESTORS:
                _progress(f"{market} {inv} — 기초 데이터 없어 스킵")
            continue

        # 기본 종목 정보 조합 (cap_df 기준 인덱스 = 티커)
        base_df = pd.DataFrame(index=cap_df.index)
        base_df["시장"] = market
        base_df["종가"] = cap_df.iloc[:, 0]       # 종가
        base_df["시가총액"] = cap_df.iloc[:, 1]    # 시가총액
        base_df["거래량"] = cap_df.iloc[:, 2]      # 거래량
        base_df["거래대금"] = cap_df.iloc[:, 3]    # 거래대금

        # 상장주식수 (회전율 계산용)
        listed_shares = cap_df.iloc[:, 4]          # 상장주식수

        # 등락률 (ohlcv 7번째 컬럼 = 등락률, 인덱스 6)
        base_df["등락률"] = ohlcv_df.iloc[:, 6].reindex(base_df.index).fillna(0.0)

        # 회전율 = 거래량 / 상장주식수 * 100
        base_df["회전율"] = (base_df["거래량"] / listed_shares * 100).round(4)
        base_df["회전율"] = base_df["회전율"].fillna(0)

        # 종목명 수집용 dict
        name_map = {}

        # 3) 투자자별 순매수 데이터
        for inv in config.INVESTORS:
            _progress(f"{market} {inv} 순매수 수집")
            net_df = _retry(
                stock.get_market_net_purchases_of_equities,
                date, date, market, inv,
            )
            time.sleep(config.REQUEST_DELAY)

            if net_df.empty:
                base_df[inv] = 0
                continue

            # 첫 번째 투자자 결과에서 종목명 수집 (net_df 첫 컬럼 = 종목명)
            if not name_map:
                for ticker in net_df.index:
                    name_map[ticker] = net_df.iloc[:, 0].get(ticker, "")

            # 순매수거래대금 = 마지막 컬럼 (순매수거래대금)
            net_col = net_df.iloc[:, -1]
            base_df[inv] = net_col.reindex(base_df.index).fillna(0).astype("int64", errors="ignore")

        # 종목명 매핑
        base_df["종목명"] = base_df.index.map(lambda t: name_map.get(t, ""))
        # 종목명이 비어있는 경우 pykrx 개별 조회 (소수만)
        missing = base_df[base_df["종목명"] == ""].index
        for ticker in missing:
            try:
                base_df.at[ticker, "종목명"] = stock.get_market_ticker_name(ticker)
            except Exception:
                pass

        # 인덱스(티커)를 컬럼으로
        base_df = base_df.reset_index()
        base_df = base_df.rename(columns={base_df.columns[0]: "티커"})

        all_data.append(base_df)

    if not all_data:
        print("[Collector] 수집된 데이터가 없습니다.")
        return pd.DataFrame()

    result = pd.concat(all_data, ignore_index=True)

    # 거래량 0인 종목 제거 (비활성 종목)
    result = result[result["거래량"] > 0].reset_index(drop=True)

    # 컬럼 순서 정리
    ordered = [c for c in config.COLUMN_ORDER if c in result.columns]
    extra = [c for c in result.columns if c not in ordered]
    result = result[ordered + extra]

    print(f"[Collector] 수집 완료: {len(result)}개 종목")
    return result
