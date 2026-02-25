"""설정 모듈."""

import os

# 경로
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# 시장
MARKETS = ["KOSPI", "KOSDAQ"]

# 투자자 카테고리 (pykrx 지원 12종)
INVESTORS = [
    "개인", "외국인", "기관합계",
    "금융투자", "보험", "투신", "사모",
    "은행", "기타금융", "연기금",
    "기타법인", "기타외국인",
]

# 주요 투자자 (대시보드 요약용)
MAJOR_INVESTORS = ["개인", "외국인", "기관합계"]

# API 호출 딜레이 (초)
REQUEST_DELAY = 0.2

# 재시도 설정
MAX_RETRIES = 2
RETRY_BASE_DELAY = 0.5

# 엑셀 컬럼 순서
COLUMN_ORDER = [
    "티커", "종목명", "시장", "종가", "등락률",
    "시가총액", "거래대금", "거래량", "회전율",
] + INVESTORS

# 랭킹 시트에서 사용할 투자자 및 시트명
RANKING_INVESTORS = {
    "외국인": "외국인_TOP50",
    "기관합계": "기관_TOP50",
    "개인": "개인_TOP50",
}

# 랭킹 시트 컬럼 순서
RANKING_COLUMN_ORDER = [
    "티커", "종목명", "시장", "종가", "등락률",
    "시가총액", "거래대금", "거래량", "회전율",
]
