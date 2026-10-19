"""유튜브 곡 검색 + 신청곡 대기열."""
import math
import re
import threading
from collections import deque
from dataclasses import dataclass, field

import requests
import yt_dlp

YOUTUBE_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/|embed/)|youtu\.be/|music\.youtube\.com/watch\?(?:.*&)?v=)"
    r"([A-Za-z0-9_-]{11})"
)


class SongError(Exception):
    """사용자에게 그대로 보여줄 수 있는 오류."""


@dataclass
class Candidate:
    video_id: str
    title: str
    duration: int  # 초, 알 수 없으면 0


@dataclass
class Song:
    video_id: str
    title: str
    duration: int
    requester: str
    requester_id: str
    candidates: list = field(default_factory=list, repr=False)  # 검색 후보 (!다시 / 재생 오류 시 사용)
    cand_idx: int = 0

    def use(self, idx):
        c = self.candidates[idx]
        self.cand_idx = idx
        self.video_id, self.title, self.duration = c.video_id, c.title, c.duration

    def to_dict(self):
        return {
            "video_id": self.video_id,
            "title": self.title,
            "duration": self.duration,
            "requester": self.requester,
        }


# ---------- 검색 정확도 점수 ----------
# 원곡이 아닐 가능성이 높은 영상의 단어들. 한 줄 = 같은 뜻의 묶음.
# 제목에 있으면 감점, 단 검색어에도 같은 묶음 단어가 있으면(예: "밤편지 라이브") 우대.
_BAD_WORDS = [
    "cover|커버|불러|부르는|부른", "karaoke|노래방|tj|금영", "reaction|리액션",
    "1시간|1 ?hours?|loop|반복|연속 ?듣기", "tutorial|강좌|레슨|악보|tab|chords?",
    "piano|피아노", "guitar|기타", "drums?|드럼", "teaser|티저", "shorts|쇼츠", "remix|리믹스",
    "inst|instrumental|mr", "live|라이브|콘서트|concert", "직캠|fancam",
    "방송|가요대전|가요대축제|스케치북|뮤직뱅크|인기가요|엠카운트다운|음악중심|쇼챔피언|더쇼",
    "playlist|플레이리스트|모음", "해석", "sped ?up|slowed|8d|nightcore",
    "dance practice|practice|안무|choreography", "behind|비하인드|making|메이킹",
]
_BAD_RE = [re.compile(rf"(?<![a-z])(?:{w})(?![a-z])", re.I) for w in _BAD_WORDS]
_GOOD_TITLE_RE = re.compile(r"\b(m/?v|official|audio|lyrics?)\b|가사|공식|뮤직비디오", re.I)
# 공식/레이블 채널
_GOOD_CHANNEL_RE = re.compile(
    r"official|- topic$|vevo|1thek|stone music|smtown|hybe labels|jyp|yg ?entertainment|"
    r"starship|kozent|genie ?music|kakao ?entertainment|\bcj ?e&m\b|bighit|\bador\b|the black label",
    re.I,
)


def _score(entry, rank, query):
    title = entry.get("title") or ""
    channel = entry.get("channel") or entry.get("uploader") or ""
    q = query.lower()
    s = math.log10((entry.get("view_count") or 0) + 10)  # 조회수가 많을수록 원곡일 확률이 큼
    s += (10 - rank) * 0.15  # 유튜브 원래 순위도 조금 반영
    if _GOOD_CHANNEL_RE.search(channel):
        s += 2
    if entry.get("channel_is_verified"):
        s += 0.5
    if _GOOD_TITLE_RE.search(title):
        s += 1.5
    for r in _BAD_RE:
        if r.search(q):
            # 검색어에 직접 쓴 버전(예: "밤편지 커버")이면 그 버전을 우대
            s += 3 if r.search(title) else -3
        elif r.search(title):
            s -= 3
    dur = int(entry.get("duration") or 0)
    if dur and (dur > 600 or dur < 60):
        s -= 4
    return s


# ---------- 검색 ----------
_YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
    "ignore_no_formats_error": True,
}


def check_embeddable(video_id):
    """oEmbed 로 영상이 존재하고 퍼가기가 허용되는지 확인. (제목, 가능여부) 반환."""
    try:
        r = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            timeout=10,
        )
    except requests.RequestException:
        return None, True  # 확인 실패 시 일단 허용 (플레이어에서 다시 걸러짐)
    if r.status_code != 200:
        return None, False
    return r.json().get("title"), True


def _resolve_link(video_id):
    try:
        with yt_dlp.YoutubeDL(_YDL_OPTS) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=False, process=False
            )
    except Exception:
        # yt-dlp가 실패해도 제목만이라도 가져옵니다(길이 제한은 확인 불가).
        title, ok = check_embeddable(video_id)
        if not ok:
            raise SongError("영상을 찾을 수 없거나 퍼가기가 막힌 영상이에요.")
        return Candidate(video_id, title or video_id, 0)
    if info.get("is_live"):
        raise SongError("라이브 영상은 신청할 수 없어요.")
    return Candidate(video_id, info.get("title") or video_id, int(info.get("duration") or 0))


def resolve(query):
    """유튜브 링크나 검색어를 (후보 리스트, 링크여부)로 바꿉니다. 후보는 좋은 순서로 정렬됨."""
    m = YOUTUBE_ID_RE.search(query)
    if m:
        return [_resolve_link(m.group(1))], True
    if query.startswith("http"):
        raise SongError("유튜브 링크만 신청할 수 있어요.")

    opts = dict(_YDL_OPTS, extract_flat="in_playlist")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch10:{query}", download=False)
    except Exception:
        raise SongError("검색 중 오류가 났어요. 잠시 후 다시 시도해 주세요.")

    scored = []
    for rank, e in enumerate(info.get("entries") or []):
        if not e or not e.get("id") or len(e["id"]) != 11 or e.get("live_status") == "is_live":
            continue
        scored.append((_score(e, rank, query), Candidate(e["id"], e.get("title") or e["id"], int(e.get("duration") or 0))))
    if not scored:
        raise SongError("검색 결과가 없어요.")
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored], False


# ---------- 대기열 ----------
class SongQueue:
    def __init__(self, max_queue=30, per_user_limit=2, volume=70):
        self.max_queue = max_queue
        self.per_user_limit = per_user_limit
        self.volume = volume  # 플레이어 볼륨 (0~100)
        self._lock = threading.Lock()
        self._items = deque()
        self.current = None
        self.seq = 0  # 곡이 바뀔 때마다 증가 (플레이어 동기화용)

    def _advance(self):
        self.current = self._items.popleft() if self._items else None
        self.seq += 1

    def _all(self):
        return list(self._items) + ([self.current] if self.current else [])

    def check_can_add(self, requester_id):
        """검색 전에 미리 확인 (검색은 느리니까)."""
        with self._lock:
            if len(self._items) >= self.max_queue:
                raise SongError("대기열이 꽉 찼어요.")
            mine = sum(1 for s in self._items if s.requester_id == requester_id)
            if self.per_user_limit and mine >= self.per_user_limit:
                raise SongError(f"한 사람당 {self.per_user_limit}곡까지 신청할 수 있어요.")

    def has(self, video_id):
        with self._lock:
            return any(s.video_id == video_id for s in self._all())

    def contains(self, song):
        with self._lock:
            return any(s is song for s in self._all())

    def add(self, song):
        """대기 순번을 반환합니다. 0이면 바로 재생."""
        with self._lock:
            if any(s.video_id == song.video_id for s in self._all()):
                raise SongError("이미 대기열에 있는 곡이에요.")
            if len(self._items) >= self.max_queue:
                raise SongError("대기열이 꽉 찼어요.")
            mine = sum(1 for s in self._items if s.requester_id == song.requester_id)
            if self.per_user_limit and mine >= self.per_user_limit:
                raise SongError(f"한 사람당 {self.per_user_limit}곡까지 신청할 수 있어요.")
            self._items.append(song)
            if self.current is None:
                self._advance()
                return 0
            return len(self._items)

    def replace(self, song, cand_idx):
        """신청곡을 다른 후보로 교체. 재생 중인 곡이면 플레이어가 새 곡을 틀도록 seq 증가."""
        with self._lock:
            if not any(s is song for s in self._all()):
                return False
            song.use(cand_idx)
            if song is self.current:
                self.seq += 1
            return True

    def skip(self):
        with self._lock:
            prev = self.current
            self._advance()
            return prev, self.current

    def finished(self, seq):
        """플레이어가 곡이 끝났다고 알려올 때. 이미 넘어간 곡이면 무시."""
        with self._lock:
            if seq != self.seq:
                return None, None
            prev = self.current
            self._advance()
            return prev, self.current

    def cancel_last(self, requester_id):
        with self._lock:
            for s in reversed(self._items):
                if s.requester_id == requester_id:
                    self._items.remove(s)
                    return s
            return None

    def upcoming(self):
        with self._lock:
            return list(self._items)

    def state(self):
        with self._lock:
            return {
                "seq": self.seq,
                "volume": self.volume,
                "current": self.current.to_dict() if self.current else None,
                "queue": [s.to_dict() for s in self._items],
            }
