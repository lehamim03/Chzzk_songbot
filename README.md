# 치지직 신청곡 봇

치지직 채팅에서 `!신청곡 유튜브링크` 또는 `!신청곡 노래제목` 으로 노래를 신청받아 방송에 틀어주는 봇입니다.

## 1. 실행 (스트리머)
1. [Python 3.10 이상](https://www.python.org/downloads/) 설치 (설치할 때 **"Add python.exe to PATH" 체크**)
2. 이 저장소를 받아서 (`Code` → `Download ZIP` → 압축 풀기) **`run.bat` 더블클릭**
   - 처음 실행 때 필요한 프로그램을 자동으로 설치합니다 (1~2분)
3. 브라우저가 열리면 **스트리머 본인 치지직 계정으로 로그인** → 권한 동의
   - 봇은 **로그인한 계정의 채널 채팅을 읽고, 그 계정 이름으로 안내 채팅을 보냅니다.**
   - 다른 계정으로 로그인됐다면 `http://localhost:8080/switch` 에서 네이버 로그아웃 후 다시 로그인하세요.
   - 로그인 정보는 `tokens.json` 에 저장되어 다음부터는 자동으로 로그인됩니다.

치지직 개발자 센터 등록은 필요 없습니다. (배포자의 인증 서버를 통해 로그인)

## 2. OBS 설정
소스 추가 → **브라우저** → URL: `http://localhost:8080/player`, 너비 1280 / 높이 720
- **"OBS를 통해 오디오 제어" 체크 해제** (데스크톱 오디오 캡처를 쓰는 경우)
  - 노래가 PC 기본 스피커/헤드폰으로 나와서 스트리머도 듣고, 데스크톱 오디오로 방송에 한 번만 나감
  - 체크한 상태에서 모니터링까지 켜면 데스크톱 오디오에 한 번 더 잡혀서 소리가 두 번 나가니 주의
  - 노래 볼륨은 채팅 `!볼륨` 명령어나 `config.json` 의 `volume` 으로 조절
- 주소 옵션 (조합 가능, 예: `/player?mode=audio&info=0`)
  - `?mode=audio` 영상 숨기고 제목 카드만
  - `?info=0` 제목 카드 숨김

## 채팅 명령어
| 명령어 | 설명 |
|---|---|
| `!신청곡 유튜브링크` / `!신청곡 노래제목` | 대기열에 추가 (검색어면 원곡일 가능성이 가장 높은 영상) |
| `!다시` | 스트리머/매니저 전용. 재생 중인 곡이 엉뚱하면 다음 검색 후보로 교체 |
| `!볼륨` / `!볼륨 30` / `!볼륨 +10` / `!볼륨 -10` | 스트리머/매니저 전용. 현재 볼륨 확인 / 변경 (0~100) |
| `!대기열` | 대기 중인 곡 |
| `!현재곡` | 지금 재생 중인 곡 |
| `!취소` | 내가 마지막으로 신청한 곡 취소 |
| `!스킵` | 스트리머/매니저, 또는 현재 곡 신청자 본인만 |

## 설정 (config.json)
처음 실행할 때 `config.example.json` 을 복사해서 자동으로 만들어집니다.

| 키 | 기본값 | 설명 |
|---|---|---|
| `auth_server` | | 인증 서버 주소 (배포자가 미리 넣어 둠, 바꾸지 마세요) |
| `port` | 8080 | 봇 웹 서버 포트 (플레이어 주소 `http://localhost:포트/player`) |
| `max_duration_sec` | 600 | 곡 최대 길이(초), 0이면 제한 없음 |
| `per_user_limit` | 2 | 한 사람이 대기열에 넣을 수 있는 곡 수 |
| `max_queue` | 30 | 대기열 최대 크기 |
| `chat_replies` | true | 봇이 채팅으로 안내할지 |
| `volume` | 70 | 봇을 켰을 때 시작 볼륨 (0~100) |

## 검색 정확도
노래 제목으로 신청하면 유튜브 검색 결과 10개에 점수를 매겨서 고릅니다.
- 조회수, 공식/레이블 채널(1theK, SMTOWN, HYBE LABELS, `- Topic`, `Official` 등), 제목의 MV/Official/가사 → 가산점
- 커버, 노래방, 라이브, 방송 무대, 1시간 반복, 안무 연습, 리믹스 등 → 감점
- 단, 검색어에 직접 쓴 버전은 우대 (`!신청곡 밤편지 라이브` → 라이브 영상)
- 10분 넘는 영상, 퍼가기가 막힌 영상은 후보에서 제외
- 키워드 목록은 `songs.py` 의 `_BAD_WORDS`, `_GOOD_CHANNEL_RE` 에서 수정할 수 있어요.

## 참고
- 퍼가기(임베드)가 막힌 영상은 신청 단계에서 거르고, 그래도 재생 오류가 나면 다음 후보로 자동 교체합니다.
- 대기열은 메모리에만 있어서 봇을 끄면 사라집니다.
- 일반 브라우저에서 플레이어를 열면 소리 자동재생이 막혀 있을 수 있어요 → 화면을 한 번 클릭. (OBS에서는 문제 없음)
- 30일 넘게 봇을 안 켜면 로그인이 만료됩니다. 콘솔 안내대로 `http://localhost:8080/login` 을 열어 다시 로그인하세요.

---

## 인증 서버 (배포자용)
치지직 Client Secret 은 `auth-server/` 의 Cloudflare Worker 에만 저장되고, 스트리머 PC 에는 토큰만 전달됩니다.

```
스트리머 PC 봇 ──/login──> 인증 서버 ──> 치지직 로그인 ──/callback──> 인증 서버 (Secret 으로 토큰 발급)
      ^                                                                   │
      └──────────── http://localhost:포트/auth#토큰 ────────────────────────┘
토큰 갱신: 봇 ──POST /refresh──> 인증 서버 ──> 치지직
```

### 배포 방법
1. [Cloudflare](https://dash.cloudflare.com/sign-up) 가입 (무료)
2. 터미널에서:
   ```
   cd auth-server
   npm install
   npx wrangler login
   npx wrangler secret put CHZZK_CLIENT_ID
   npx wrangler secret put CHZZK_CLIENT_SECRET
   npx wrangler deploy
   ```
   배포가 끝나면 `https://chzzk-songbot-auth.<내 서브도메인>.workers.dev` 주소가 나옵니다.
3. [치지직 개발자 센터](https://developers.chzzk.naver.com) 앱 설정
   - **로그인 리디렉션 URL**: `https://chzzk-songbot-auth.<내 서브도메인>.workers.dev/callback`
   - **API Scope**: `채팅 메시지 조회`, `채팅 메시지 쓰기`, `유저 정보 조회` (로그인 계정 이름 표시용)
4. `config.example.json` 의 `auth_server` 를 위 주소로 바꿔서 커밋 → 스트리머들은 받아서 바로 사용

로컬 테스트: `auth-server/.dev.vars` 에 `CHZZK_CLIENT_ID=...`, `CHZZK_CLIENT_SECRET=...` 를 적고 `npx wrangler dev` (이 파일은 커밋되지 않습니다).
