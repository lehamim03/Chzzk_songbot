"""치지직 신청곡 봇 실행 파일.

python main.py 로 실행한 뒤 OBS 브라우저 소스에 http://localhost:8080/player 를 추가하세요.
"""
import json
import logging
import os
import secrets
import sys
import webbrowser

from flask import Flask, jsonify, redirect, request, send_from_directory

from bot import SongBot
from chzzk import ChzzkApi
from songs import SongQueue

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

# 한국어 Windows 콘솔(cp949)에서 이모지 출력 시 오류가 나지 않도록
for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
for _name in ("werkzeug", "engineio", "socketio"):  # 연결 상세 로그(접속 토큰 포함) 숨김
    logging.getLogger(_name).setLevel(logging.WARNING)
log = logging.getLogger("main")

if not os.path.exists("config.json"):
    sys.exit("config.json 이 없습니다. config.example.json 을 복사해서 config.json 을 만들어 주세요.")
with open("config.json", encoding="utf-8") as f:
    config = json.load(f)
if not str(config.get("auth_server", "")).startswith("https://"):
    sys.exit("config.json 의 auth_server 에 인증 서버 주소(https://...)를 넣어 주세요.")

PORT = int(config.get("port", 8080))

api = ChzzkApi(config["auth_server"], token_path="tokens.json")
queue = SongQueue(
    max_queue=int(config.get("max_queue", 30)),
    per_user_limit=int(config.get("per_user_limit", 2)),
    volume=max(0, min(100, int(config.get("volume", 70)))),
)
bot = SongBot(api, queue, config)

app = Flask(__name__, static_folder=None)
_pending_nonces = set()

AUTH_PAGE = """<!doctype html><meta charset="utf-8"><title>치지직 로그인</title>
<body style="font-family:'Malgun Gothic',sans-serif;padding:40px">
<h2 id="msg">로그인 처리 중…</h2>
<script>
  const p = new URLSearchParams(location.hash.slice(1));
  history.replaceState(null, "", "/auth");  // 주소창에서 토큰 지우기
  const msg = document.getElementById("msg");
  if (p.get("error")) {
    msg.textContent = "로그인 실패: " + p.get("error");
  } else {
    fetch("/api/auth-complete", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(Object.fromEntries(p))})
      .then(r => r.json()).then(d => {
        if (d.ok) location.replace("/"); else msg.textContent = "로그인 실패: " + d.error;
      });
  }
</script>"""


# ---------- 로그인 ----------
@app.route("/")
def index():
    if not api.logged_in:
        return redirect("/login")
    return (
        "<meta charset='utf-8'><h2>치지직 신청곡 봇 실행 중</h2>"
        f"<p>OBS 브라우저 소스 주소: <code>http://localhost:{PORT}/player</code></p>"
        "<p><a href='/player'>플레이어 열기</a> · <a href='/api/state'>대기열 보기(JSON)</a></p>"
    )


@app.route("/login")
def login():
    nonce = secrets.token_urlsafe(16)
    _pending_nonces.add(nonce)
    return redirect(api.login_url(PORT, nonce))


@app.route("/auth")
def auth_page():
    # 인증 서버가 토큰을 URL 조각(#)에 담아 이곳으로 돌려보냅니다.
    return AUTH_PAGE


@app.route("/api/auth-complete", methods=["POST"])
def auth_complete():
    body = request.get_json(silent=True) or {}
    # 이 PC에서 시작한 로그인인지 확인 (다른 사람 토큰 주입 방지)
    if body.get("nonce") not in _pending_nonces:
        return jsonify(ok=False, error="잘못된 로그인 요청입니다. 다시 시도해 주세요.")
    _pending_nonces.discard(body["nonce"])
    if not body.get("accessToken") or not body.get("refreshToken"):
        return jsonify(ok=False, error="토큰이 없습니다.")
    api.set_tokens(body["accessToken"], body["refreshToken"], body.get("expiresIn"))
    log.info("치지직 로그인 완료")
    bot.start()
    return jsonify(ok=True)


# ---------- 플레이어 ----------
@app.route("/player")
def player():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "player.html")


@app.route("/api/state")
def state():
    return jsonify(queue.state())


@app.route("/api/finished", methods=["POST"])
def finished():
    body = request.get_json(silent=True) or {}
    seq = int(body.get("seq", -1))
    if body.get("error"):
        bot.on_play_error(seq)
    else:
        _, nxt = queue.finished(seq)
        if nxt:
            log.info("다음 곡: %s", nxt.title)
    return jsonify(queue.state())


@app.route("/api/skip", methods=["POST"])
def skip():
    queue.skip()
    return jsonify(queue.state())


if __name__ == "__main__":
    if api.logged_in:
        bot.start()
    else:
        url = f"http://localhost:{PORT}/login"
        log.info("처음 실행이라 치지직 로그인이 필요합니다. 브라우저에서 %s 를 여세요.", url)
        webbrowser.open(url)
    log.info("플레이어: http://localhost:%d/player", PORT)
    app.run(host="127.0.0.1", port=PORT, threaded=True)
