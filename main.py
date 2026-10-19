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
logging.getLogger("werkzeug").setLevel(logging.WARNING)
log = logging.getLogger("main")

if not os.path.exists("config.json"):
    sys.exit("config.json 이 없습니다. config.example.json 을 복사해서 config.json 을 만들고 Client ID/Secret 을 넣어 주세요.")
with open("config.json", encoding="utf-8") as f:
    config = json.load(f)

PORT = int(config.get("port", 8080))
REDIRECT_URI = f"http://localhost:{PORT}/callback"

api = ChzzkApi(config["client_id"], config["client_secret"], token_path="tokens.json")
queue = SongQueue(
    max_queue=int(config.get("max_queue", 30)),
    per_user_limit=int(config.get("per_user_limit", 2)),
    volume=max(0, min(100, int(config.get("volume", 70)))),
)
bot = SongBot(api, queue, config)

app = Flask(__name__, static_folder=None)
_pending_states = set()


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
    state = secrets.token_urlsafe(16)
    _pending_states.add(state)
    return redirect(api.auth_url(REDIRECT_URI, state))


@app.route("/callback")
def callback():
    code, state = request.args.get("code"), request.args.get("state")
    if not code or state not in _pending_states:
        return "잘못된 로그인 요청입니다. <a href='/login'>다시 시도</a>", 400
    _pending_states.discard(state)
    try:
        api.exchange_code(code, state)
    except Exception as e:
        log.exception("토큰 발급 실패")
        return f"토큰 발급 실패: {e}", 500
    log.info("치지직 로그인 완료")
    bot.start()
    return redirect("/")


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
