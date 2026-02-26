"""pykrx 기반 투자자별 수급 데이터 수집 모듈."""

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime

import pandas as pd
import requests as _requests

pd.set_option("future.no_silent_downcasting", True)

# ── pykrx 내부 requests에 기본 타임아웃 설정 (무한 대기 방지) ──
_original_request = _requests.Session.request


def _patched_request(self, *args, **kwargs):
    kwargs.setdefault("timeout", 15)
    return _original_request(self, *args, **kwargs)


_requests.Session.request = _patched_request

from pykrx import stock  # noqa: E402  — 타임아웃 패치 후 임포트

import config  # noqa: E402


def _is_likely_trading_day(date_str: str) -> bool:
    """간단한 거래일 판별 (주말 제외 + KRX 빠른 체크).

    완벽하지 않지만 주말/공휴일에 28번 API 호출하는 것을 방지.
    """
    try:
        dt = datetime.strptime(date_str, "%Y%m%d")
        if dt.weekday() >= 5:  # 토/일
            return False
        # pykrx로 빠른 체크: OHLCV가 있으면 거래일
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                stock.get_market_ohlcv_by_ticker, date_str, market="KOSPI"
            )
            result = future.result(timeout=10)
            return not result.empty
    except (FuturesTimeout, Exception):
        # 타임아웃이면 일단 거래일로 간주 (본 수집에서 개별 타임아웃 처리)
        return True


def _retry(func, *args, max_retries=config.MAX_RETRIES, timeout=20, **kwargs):
    """API 호출 재시도 래퍼 (타임아웃 포함)."""
    for attempt in range(max_retries):
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(func, *args, **kwargs)
                return future.result(timeout=timeout)
        except FuturesTimeout:
            print(f"[Collector] 타임아웃 ({timeout}s): {func.__name__}")
            if attempt == max_retries - 1:
                return pd.DataFrame()
            time.sleep(config.RETRY_BASE_DELAY)
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
    # 비거래일 사전 체크
    if not _is_likely_trading_day(date):
        print(f"[Collector] {date}는 비거래일(주말/공휴일)입니다.")
        return pd.DataFrame()

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
        # 종목명이 비어있는 경우 pykrx 개별 조회 (최대 50개로 제한)
        missing = base_df[base_df["종목명"] == ""].index[:50]
        for ticker in missing:
            try:
                name = stock.get_market_ticker_name(ticker)
                if name:
                    base_df.at[ticker, "종목명"] = name
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
