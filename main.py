"""치지직 신청곡 봇 실행 파일.

python main.py 로 실행한 뒤 OBS 브라우저 소스에 http://localhost:8080/player 를 추가하세요.
"""
import html
import json
import logging
import os
import secrets
import socket
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
try:
    with open("config.json", encoding="utf-8-sig") as f:  # 메모장이 붙이는 BOM 허용
        config = json.load(f)
    PORT = int(config.get("port", 8080))
except (ValueError, TypeError) as e:
    sys.exit(
        f"config.json 형식이 잘못됐습니다: {e}\n"
        "따옴표/쉼표를 확인하거나, config.json 을 지우고 다시 실행하면 기본값으로 새로 만들어집니다."
    )
CLIENT_ID = str(config.get("client_id") or "").strip()
CLIENT_SECRET = str(config.get("client_secret") or "").strip()
if bool(CLIENT_ID) != bool(CLIENT_SECRET):
    sys.exit("config.json 의 client_id 와 client_secret 을 둘 다 넣거나, 둘 다 비워 두세요.")
if not CLIENT_ID and not str(config.get("auth_server", "")).startswith("https://"):
    sys.exit("config.json 의 auth_server 에 인증 서버 주소(https://...)를 넣어 주세요.")

api = ChzzkApi(
    auth_server=config.get("auth_server"),
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    token_path="tokens.json",
)
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
    if bot.channel_id:
        url = f"https://chzzk.naver.com/{html.escape(bot.channel_id)}"
        name = html.escape(bot.account_name) if bot.account_name else "채널 열어서 확인"
        account = f"<a href='{url}' target='_blank'>{name}</a> <small>({url})</small>"
    else:
        account = "확인 중… (잠시 후 새로고침)"
    return (
        "<meta charset='utf-8'><body style=\"font-family:'Malgun Gothic',sans-serif;padding:40px\">"
        "<h2>치지직 신청곡 봇 실행 중</h2>"
        f"<p>봇 연결 채널: <b>{account}</b><br>"
        "<small>이 채널의 채팅을 읽고 안내 채팅을 보냅니다. "
        "스트리머 채널이 아니면 아래 '다른 계정으로 로그인'을 하세요.</small></p>"
        + (
            "<p>로그인 방식: <b>직접 등록한 앱</b> — 봇 채팅이 로그인한 계정 이름으로 나갑니다.</p>"
            if api.direct
            else "<p>로그인 방식: <b>인증 서버</b> — 봇 채팅이 인증 서버 앱을 등록한 계정 이름으로 나갑니다.</p>"
        )
        +
        f"<p>OBS 브라우저 소스 주소: <code>http://localhost:{PORT}/player</code></p>"
        "<p><a href='/player'>플레이어 열기</a> · <a href='/api/state'>대기열 보기(JSON)</a></p>"
        "<p><a href='/switch'>다른 계정으로 로그인</a></p>"
    )


@app.route("/switch")
def switch():
    return (
        "<meta charset='utf-8'><body style=\"font-family:'Malgun Gothic',sans-serif;padding:40px\">"
        "<h2>다른 계정으로 로그인</h2>"
        "<p>봇은 <b>이 브라우저에 로그인된 네이버 계정</b>으로 자동 연결됩니다.</p>"
        "<h3>방법 1 (가장 확실): 시크릿 창</h3>"
        "<ol>"
        "<li>크롬/엣지에서 <b>Ctrl + Shift + N</b> 으로 시크릿 창 열기</li>"
        f"<li>시크릿 창 주소창에 <code>http://localhost:{PORT}/login</code> 입력</li>"
        "<li>네이버 로그인 화면에서 <b>스트리머 계정</b>으로 로그인 → 권한 동의</li>"
        "</ol>"
        "<h3>방법 2: 지금 브라우저에서</h3>"
        "<ol>"
        "<li><a href='https://nid.naver.com/nidlogin.logout' target='_blank'>네이버 로그아웃</a> (새 탭)</li>"
        "<li><a href='https://chzzk.naver.com' target='_blank'>치지직</a> 에서 <b>스트리머 계정</b>으로 로그인 (새 탭)<br>"
        "<small>오른쪽 위 프로필이 스트리머 계정인지 확인하세요.</small></li>"
        "<li>이 탭으로 돌아와서 아래 버튼 클릭 → 권한 동의</li>"
        "</ol>"
        "<p><a href='/login'><button>스트리머 계정으로 봇 연결</button></a></p>"
        "<p><small>완료되면 봇 첫 화면으로 이동하고, 봇 창에 '치지직 로그인 완료' 가 나옵니다.</small></p>"
    )


@app.route("/login")
def login():
    nonce = secrets.token_urlsafe(16)
    _pending_nonces.add(nonce)
    return redirect(api.login_url(PORT, nonce))


@app.route("/callback")
def callback():
    """직접 방식: 치지직이 로그인 후 돌려보내는 곳 (개발자 센터의 로그인 리디렉션 URL)."""
    code, state = request.args.get("code"), request.args.get("state")
    if not api.direct:
        return "인증 서버 방식에서는 쓰지 않는 주소입니다. <a href='/login'>다시 로그인</a>", 400
    if not code or state not in _pending_nonces:
        return "잘못된 로그인 요청입니다. <a href='/login'>다시 시도</a>", 400
    _pending_nonces.discard(state)
    try:
        api.exchange_code(code, state)
    except Exception as e:
        log.error("토큰 발급 실패: %s", e)
        return f"<meta charset='utf-8'>로그인 실패: {html.escape(str(e))}", 500
    log.info("치지직 로그인 완료")
    bot.restart()
    return redirect("/")


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
    bot.restart()
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


def _port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


if __name__ == "__main__":
    if _port_in_use(PORT):
        sys.exit(
            f"포트 {PORT} 를 다른 프로그램이 쓰고 있습니다. (봇이 이미 켜져 있는지 확인하세요)\n"
            "config.json 의 \"port\" 를 다른 번호(예: 8090)로 바꾼 뒤 다시 실행하세요."
        )
    if api.direct:
        log.info("로그인 방식: 직접 등록한 앱 (봇 채팅이 로그인한 계정 이름으로 나갑니다)")
        log.info("개발자 센터의 로그인 리디렉션 URL: %s", api.redirect_uri(PORT))
    else:
        log.info("로그인 방식: 인증 서버 (봇 채팅이 인증 서버 앱 등록자 이름으로 나갑니다)")
    if api.logged_in:
        bot.start()
    else:
        url = f"http://localhost:{PORT}/login"
        log.info("처음 실행이라 치지직 로그인이 필요합니다. 브라우저에서 %s 를 여세요.", url)
        webbrowser.open(url)
    log.info("플레이어: http://localhost:%d/player", PORT)
    app.run(host="127.0.0.1", port=PORT, threaded=True)
