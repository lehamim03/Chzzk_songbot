"""치지직 채팅을 받아 명령어를 처리합니다."""
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import socketio

from chzzk import ChzzkAuthError
from songs import Song, SongError, check_embeddable, resolve

log = logging.getLogger("bot")

MANAGER_ROLES = {"streamer", "streaming_channel_manager", "streaming_chat_manager", "manager"}


def _short(title, n=40):
    return title if len(title) <= n else title[: n - 1] + "…"


def _fmt_time(sec):
    return f"{sec // 60}:{sec % 60:02d}" if sec else "?"


class SongBot:
    def __init__(self, api, queue, config):
        self.api = api
        self.queue = queue
        self.max_duration = int(config.get("max_duration_sec", 600))
        self.chat_replies = bool(config.get("chat_replies", True))
        self.port = int(config.get("port", 8080))
        self._pool = ThreadPoolExecutor(max_workers=4)
        self._thread = None
        self._sio = None
        self.account_name = None  # 로그인한 치지직 계정 이름
        self.channel_id = None  # 로그인한 계정의 채널 ID

    # ---------- 연결 ----------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def restart(self):
        """다른 계정으로 다시 로그인했을 때: 현재 채팅 연결을 끊고 새 토큰으로 다시 연결."""
        self.account_name = None
        self.channel_id = None
        if self._thread and self._thread.is_alive():
            if self._sio:
                self._sio.disconnect()  # _run 루프가 새 토큰으로 다시 연결합니다
        else:
            self.start()

    def _run(self):
        while True:
            try:
                url = self.api.session_url()
                sio = socketio.Client(reconnection=False)
                sio.on("SYSTEM", self._on_system)
                sio.on("CHAT", self._on_chat)
                sio.on("disconnect", lambda: log.warning("채팅 세션 연결이 끊겼습니다."))
                self._sio = sio
                sio.connect(url, transports=["websocket"])
                sio.wait()
            except ChzzkAuthError as e:
                log.error("%s 브라우저에서 http://localhost:%d/login 을 열어 다시 로그인해 주세요.", e, self.port)
                return
            except Exception:
                log.exception("채팅 세션 오류")
            log.info("5초 후 다시 연결합니다...")
            time.sleep(5)

    @staticmethod
    def _parse(data):
        if isinstance(data, str):
            try:
                return json.loads(data)
            except ValueError:
                return {}
        return data or {}

    def _on_system(self, data):
        data = self._parse(data)
        if data.get("type") == "connected":
            session_key = data["data"]["sessionKey"]
            try:
                self.api.subscribe_chat(session_key)
                log.info("채팅 구독 완료! 이제 !신청곡 을 받을 수 있어요.")
            except Exception:
                log.exception("채팅 구독 실패")
                return
            try:
                self.account_name = self.api.me().get("channelName")
                log.info("로그인 계정: %s (이 채널의 채팅을 읽고, 이 계정 이름으로 채팅을 보냅니다)", self.account_name)
            except Exception:
                log.info("로그인 계정 이름을 확인하려면 치지직 개발자 센터에서 '유저 정보 조회' 권한을 켜 주세요.")
        elif data.get("type") == "subscribed":
            # 구독된 채널 = 로그인한(토큰 주인) 계정의 채널 = 봇이 채팅을 보내는 계정
            self.channel_id = (data.get("data") or {}).get("channelId")
            log.info("봇 연결 채널: https://chzzk.naver.com/%s  ← 이 채널 주인 이름으로 채팅이 나갑니다", self.channel_id)
        else:
            log.info("SYSTEM: %s", data)

    def _on_chat(self, data):
        data = self._parse(data)
        content = (data.get("content") or "").strip()
        if content.startswith("!"):
            self._pool.submit(self._handle, data, content)

    # ---------- 명령어 ----------
    def say(self, message):
        log.info("[봇] %s", message)
        if not self.chat_replies:
            return
        try:
            self.api.send_chat(message)
        except Exception:
            log.exception("채팅 전송 실패")

    def _handle(self, data, content):
        cmd, _, arg = content.partition(" ")
        arg = arg.strip()
        user = {
            "id": data.get("senderChannelId", ""),
            "name": (data.get("profile") or {}).get("nickname") or "익명",
            "is_manager": data.get("userRoleCode") in MANAGER_ROLES,
        }
        log.info("명령어: %s  (보낸 사람: %s, 역할: %s)", content, user["name"], data.get("userRoleCode"))
        try:
            if cmd in ("!신청곡", "!노래"):
                self.cmd_request(user, arg)
            elif cmd == "!스킵":
                self.cmd_skip(user)
            elif cmd in ("!현재곡", "!지금곡"):
                self.cmd_now()
            elif cmd in ("!대기열", "!목록"):
                self.cmd_list()
            elif cmd == "!취소":
                self.cmd_cancel(user)
            elif cmd in ("!다시", "!다른곡"):
                self.cmd_retry(user)
            elif cmd == "!볼륨":
                self.cmd_volume(user, arg)
        except SongError as e:
            self.say(f"{user['name']}님, {e}")
        except Exception:
            log.exception("명령어 처리 오류: %s", content)

    def cmd_request(self, user, arg):
        if not arg:
            self.say("사용법: !신청곡 유튜브링크 또는 !신청곡 노래제목")
            return
        self.queue.check_can_add(user["id"])
        candidates, is_link = resolve(arg)
        if is_link:
            c = candidates[0]
            if self.max_duration and c.duration > self.max_duration:
                raise SongError(
                    f"{_fmt_time(self.max_duration)} 이하 곡만 신청할 수 있어요. ({_fmt_time(c.duration)})"
                )
            if not check_embeddable(c.video_id)[1]:
                raise SongError("퍼가기가 막혀서 방송에서 틀 수 없는 영상이에요.")
            idx = 0
        else:
            idx = self._pick(candidates, 0)
            if idx is None:
                raise SongError("조건에 맞는 곡을 못 찾았어요. '가수 제목'으로 다시 신청해 주세요.")

        song = Song("", "", 0, user["name"], user["id"], candidates=candidates)
        song.use(idx)
        pos = self.queue.add(song)
        log.info("신청: %s - %s (%s)", user["name"], song.title, song.video_id)
        if pos == 0:
            self.say(f"🎵 지금 재생: {_short(song.title)} ({user['name']}님 신청)")
        else:
            self.say(f"🎵 {_short(song.title)} 신청 완료! 대기 {pos}번 ({user['name']}님)")

    def _pick(self, candidates, start):
        """start 번째 후보부터 길이 제한/중복/퍼가기 허용을 통과하는 첫 후보의 인덱스."""
        for i in range(start, len(candidates)):
            c = candidates[i]
            if self.max_duration and c.duration > self.max_duration:
                continue
            if self.queue.has(c.video_id):
                continue
            if not check_embeddable(c.video_id)[1]:
                continue
            return i
        return None

    def cmd_retry(self, user):
        """스트리머/매니저 전용: 재생 중인 곡을 다음 검색 후보로 교체."""
        if not user["is_manager"]:
            return
        song = self.queue.current
        if song is None:
            raise SongError("재생 중인 곡이 없어요.")
        if len(song.candidates) <= 1:
            raise SongError("링크로 신청된 곡이라 바꿀 후보가 없어요. !스킵을 써 주세요.")
        idx = self._pick(song.candidates, song.cand_idx + 1)
        if idx is None or not self.queue.replace(song, idx):
            raise SongError("다른 후보가 없어요. !스킵을 써 주세요.")
        log.info("다시: %s -> %s (%s)", user["name"], song.title, song.video_id)
        self.say(f"🔄 {_short(song.title, 45)}(으)로 바꿨어요. ({song.requester}님 신청곡)")

    def cmd_volume(self, user, arg):
        """스트리머/매니저 전용: !볼륨 (현재 값) / !볼륨 30 / !볼륨 +10 / !볼륨 -10"""
        if not user["is_manager"]:
            return
        cur = self.queue.volume
        if not arg:
            self.say(f"🔊 현재 볼륨: {cur}")
            return
        try:
            n = int(arg.replace(" ", ""))
        except ValueError:
            raise SongError("사용법: !볼륨 30 / !볼륨 +10 / !볼륨 -10 (0~100)")
        new = cur + n if arg[0] in "+-" else n
        new = max(0, min(100, new))
        self.queue.volume = new
        log.info("볼륨: %d -> %d (%s)", cur, new, user["name"])
        self.say(f"🔊 볼륨 {cur} → {new}")

    def on_play_error(self, seq):
        """플레이어에서 재생 오류가 났을 때: 다음 후보로 바꾸고, 없으면 넘어갑니다."""
        song = self.queue.current
        if song is None or seq != self.queue.seq:
            return
        idx = self._pick(song.candidates, song.cand_idx + 1) if len(song.candidates) > 1 else None
        if idx is not None and self.queue.replace(song, idx):
            log.info("재생 오류 -> 다른 후보: %s", song.title)
            self.say(f"⚠ 재생이 안 돼서 다른 영상으로 바꿨어요: {_short(song.title, 40)}")
            return
        prev, _ = self.queue.finished(seq)
        if prev:
            self.say(f"⚠ {_short(prev.title, 30)} 은(는) 재생할 수 없는 영상이라 넘어갔어요.")

    def cmd_skip(self, user):
        cur = self.queue.current
        if cur is None:
            raise SongError("재생 중인 곡이 없어요.")
        if not (user["is_manager"] or cur.requester_id == user["id"]):
            raise SongError("스킵은 스트리머/매니저나 신청한 본인만 할 수 있어요.")
        _, nxt = self.queue.skip()
        msg = f"⏭ {_short(cur.title, 30)} 스킵!"
        if nxt:
            msg += f" 다음 곡: {_short(nxt.title, 30)}"
        self.say(msg)

    def cmd_now(self):
        cur = self.queue.current
        if cur is None:
            self.say("지금은 재생 중인 신청곡이 없어요.")
        else:
            self.say(f"🎶 현재곡: {_short(cur.title)} ({cur.requester}님 신청)")

    def cmd_list(self):
        items = self.queue.upcoming()
        if not items:
            self.say("대기 중인 신청곡이 없어요.")
            return
        head = " / ".join(f"{i}. {_short(s.title, 18)}" for i, s in enumerate(items[:3], 1))
        more = f" 외 {len(items) - 3}곡" if len(items) > 3 else ""
        self.say(f"📋 대기열 {len(items)}곡: {head}{more}")

    def cmd_cancel(self, user):
        song = self.queue.cancel_last(user["id"])
        if song is None:
            raise SongError("대기 중인 신청곡이 없어요.")
        self.say(f"{user['name']}님의 신청곡 {_short(song.title, 30)} 취소했어요.")
