"""치지직 Open API 클라이언트 (인증 / 세션 / 채팅).

Client Secret 은 인증 서버(auth-server/)에만 있고, 여기서는 토큰만 다룹니다.
"""
import json
import os
import threading
import time
import urllib.parse

import requests

API_BASE = "https://openapi.chzzk.naver.com"


class ChzzkAuthError(Exception):
    """다시 로그인해야 하는 상황."""


class ChzzkApi:
    def __init__(self, auth_server, token_path="tokens.json"):
        self.auth_server = auth_server.rstrip("/")
        self.token_path = token_path
        self._lock = threading.Lock()
        self.tokens = self._load_tokens()

    # ---------- 토큰 저장 ----------
    def _load_tokens(self):
        if not os.path.exists(self.token_path):
            return None
        with open(self.token_path, encoding="utf-8") as f:
            return json.load(f)

    def set_tokens(self, access_token, refresh_token, expires_in):
        self.tokens = {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": time.time() + int(expires_in or 86400) - 60,
        }
        with open(self.token_path, "w", encoding="utf-8") as f:
            json.dump(self.tokens, f, ensure_ascii=False, indent=2)

    def logout(self):
        self.tokens = None
        if os.path.exists(self.token_path):
            os.remove(self.token_path)

    @property
    def logged_in(self):
        return self.tokens is not None

    # ---------- 인증 (인증 서버 경유) ----------
    def login_url(self, port, nonce):
        query = urllib.parse.urlencode({"port": port, "nonce": nonce})
        return f"{self.auth_server}/login?{query}"

    def refresh(self):
        with self._lock:
            if not self.tokens:
                raise ChzzkAuthError("로그인이 필요합니다.")
            try:
                r = requests.post(
                    f"{self.auth_server}/refresh",
                    json={"refreshToken": self.tokens["refreshToken"]},
                    timeout=15,
                )
            except requests.RequestException as e:
                raise RuntimeError(f"인증 서버에 연결할 수 없습니다: {e}")
            data = r.json() if r.content else {}
            if r.status_code == 401:
                # Refresh Token 만료(30일) 또는 권한 해제 → 다시 로그인
                self.logout()
                raise ChzzkAuthError(f"로그인이 만료되었습니다: {data.get('error')}")
            if r.status_code != 200 or not data.get("content"):
                raise RuntimeError(f"토큰 갱신 실패 ({r.status_code}): {data}")
            c = data["content"]
            # Refresh Token은 일회용이므로 매번 새로 저장합니다.
            self.set_tokens(c["accessToken"], c["refreshToken"], c.get("expiresIn"))

    def ensure_fresh(self):
        if self.tokens and time.time() >= self.tokens["expiresAt"]:
            self.refresh()

    # ---------- API 호출 ----------
    def _request(self, method, path, retry=True, **kwargs):
        if not self.tokens:
            raise ChzzkAuthError("로그인이 필요합니다.")
        self.ensure_fresh()
        headers = {"Authorization": f"Bearer {self.tokens['accessToken']}"}
        r = requests.request(method, API_BASE + path, headers=headers, timeout=10, **kwargs)
        if r.status_code == 401 and retry:
            self.refresh()
            return self._request(method, path, retry=False, **kwargs)
        data = r.json() if r.content else {}
        if r.status_code != 200:
            raise RuntimeError(f"{method} {path} 실패 ({r.status_code}): {data}")
        return data.get("content")

    def session_url(self):
        return self._request("GET", "/open/v1/sessions/auth")["url"]

    def subscribe_chat(self, session_key):
        self._request(
            "POST",
            "/open/v1/sessions/events/subscribe/chat",
            params={"sessionKey": session_key},
        )

    def send_chat(self, message):
        # 채팅은 최대 100자
        if len(message) > 100:
            message = message[:99] + "…"
        self._request("POST", "/open/v1/chats/send", json={"message": message})
