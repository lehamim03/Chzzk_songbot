"""치지직 Open API 클라이언트 (인증 / 세션 / 채팅)."""
import json
import os
import threading
import time
import urllib.parse

import requests

API_BASE = "https://openapi.chzzk.naver.com"
AUTH_PAGE = "https://chzzk.naver.com/account-interlock"


class ChzzkAuthError(Exception):
    pass


class ChzzkApi:
    def __init__(self, client_id, client_secret, token_path="tokens.json"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_path = token_path
        self._lock = threading.Lock()
        self.tokens = self._load_tokens()

    # ---------- 토큰 저장 ----------
    def _load_tokens(self):
        if not os.path.exists(self.token_path):
            return None
        with open(self.token_path, encoding="utf-8") as f:
            return json.load(f)

    def _save_tokens(self, content):
        self.tokens = {
            "accessToken": content["accessToken"],
            "refreshToken": content["refreshToken"],
            "expiresAt": time.time() + int(content.get("expiresIn", 86400)) - 60,
        }
        with open(self.token_path, "w", encoding="utf-8") as f:
            json.dump(self.tokens, f, ensure_ascii=False, indent=2)

    @property
    def logged_in(self):
        return self.tokens is not None

    # ---------- 인증 ----------
    def auth_url(self, redirect_uri, state):
        query = urllib.parse.urlencode(
            {"clientId": self.client_id, "redirectUri": redirect_uri, "state": state}
        )
        return f"{AUTH_PAGE}?{query}"

    def exchange_code(self, code, state):
        content = self._token_request(
            {
                "grantType": "authorization_code",
                "clientId": self.client_id,
                "clientSecret": self.client_secret,
                "code": code,
                "state": state,
            }
        )
        with self._lock:
            self._save_tokens(content)

    def refresh(self):
        with self._lock:
            if not self.tokens:
                raise ChzzkAuthError("로그인이 필요합니다.")
            content = self._token_request(
                {
                    "grantType": "refresh_token",
                    "refreshToken": self.tokens["refreshToken"],
                    "clientId": self.client_id,
                    "clientSecret": self.client_secret,
                }
            )
            # Refresh Token은 일회용이므로 매번 새로 저장합니다.
            self._save_tokens(content)

    def ensure_fresh(self):
        if self.tokens and time.time() >= self.tokens["expiresAt"]:
            self.refresh()

    def _token_request(self, body):
        r = requests.post(f"{API_BASE}/auth/v1/token", json=body, timeout=10)
        data = r.json() if r.content else {}
        if r.status_code != 200 or not data.get("content"):
            raise ChzzkAuthError(f"토큰 발급 실패 ({r.status_code}): {data}")
        return data["content"]

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
