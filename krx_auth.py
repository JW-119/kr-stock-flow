"""KRX data.krx.co.kr 세션 인증 모듈.

2026-02-27부터 KRX가 비로그인 API 접근을 차단하여,
pykrx 사용 전 인증된 세션을 주입해야 한다.
"""

from __future__ import annotations

import os
import requests
from pykrx.website.comm.webio import Post

_session: requests.Session | None = None


def _create_authenticated_session(krx_id: str, krx_pw: str) -> requests.Session:
    """KRX 로그인 후 인증된 세션 반환."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9",
    })

    # 1) 메인 페이지 → JSESSIONID 쿠키 획득
    session.get("https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd")

    # 2) 로그인 (MDCCOMS001D1.cmd가 인증 + 세션 설정을 동시에 처리)
    resp = session.post(
        "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd",
        data={"mbrId": krx_id, "pw": krx_pw, "skipDup": "Y"},
        headers={
            "Referer": "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd",
            "X-Requested-With": "XMLHttpRequest",
        },
    )

    data = resp.json()
    error = data.get("_error_code", "")
    # CD001 = 정상 로그인
    if error and error != "CD001":
        msg = data.get("_error_message", error)
        raise RuntimeError(f"KRX 로그인 실패: {msg} ({error})")

    # mdc.client_session 쿠키 설정 (세션 타임아웃 관리용)
    session.cookies.set("mdc.client_session", "true", domain="data.krx.co.kr", path="/")

    return session


def _patched_read(self, **params):
    """pykrx Post.read()를 인증된 세션으로 대체."""
    resp = _session.post(self.url, headers=self.headers, data=params)
    return resp


def init(krx_id: str | None = None, krx_pw: str | None = None):
    """KRX 인증 초기화 및 pykrx 패치.

    환경변수 KRX_ID, KRX_PW 또는 인자로 전달.
    """
    global _session

    krx_id = krx_id or os.environ.get("KRX_ID", "")
    krx_pw = krx_pw or os.environ.get("KRX_PW", "")

    if not krx_id or not krx_pw:
        print("[KRX Auth] KRX_ID / KRX_PW 미설정 — 인증 없이 진행 (실패할 수 있음)")
        return False

    try:
        _session = _create_authenticated_session(krx_id, krx_pw)
        # pykrx Post.read()를 인증된 세션 사용하도록 패치
        Post.read = _patched_read
        print("[KRX Auth] 로그인 성공")
        return True
    except Exception as e:
        print(f"[KRX Auth] 로그인 실패: {e}")
        return False
