"""국내 주식 투자자별 수급 데이터 수집 CLI."""

import argparse
from datetime import datetime

import collector
import excel_writer


def main():
    parser = argparse.ArgumentParser(description="국내 주식 투자자별 수급 데이터 수집")
    parser.add_argument(
        "--date",
        type=str,
        default=datetime.now().strftime("%Y%m%d"),
        help="수집 날짜 (YYYYMMDD, 기본: 오늘)",
    )
    args = parser.parse_args()
    date_str = args.date

    print(f"=== 수급 데이터 수집: {date_str} ===")

    df = collector.collect(date_str)

    if df.empty:
        print("수집된 데이터가 없습니다. 휴장일이거나 날짜를 확인해 주세요.")
        return

    excel_writer.save_to_excel(df, date_str)
    print("완료!")


if __name__ == "__main__":
    main()
