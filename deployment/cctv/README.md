# CCTV 연결과 난간 연동 (MediaMTX v1.21.2)

## 구성과 보안 경계

CCTV → CCTV 전용 Pi(FFmpeg 복사 송출) → SRT/UDP 8890 → 서버 MediaMTX.
서버의 analytics-server가 로컬 RTSP 영상을 읽고 YOLO/ByteTrack으로 진입을 판단한다.
카메라 전용 분석 토큰으로 Spring Boot에 enter/age를 보내면 서버가 등록된
camera → rail → gateway 매핑을 적용해 기존 난간 Pi WSS → PLC → P4로 전달한다.
CCTV Pi에는 PLC 게이트웨이 토큰이나 관리자 토큰을 넣지 않는다.

- CCTV Pi는 외부 인바운드 포트를 열지 않고 WSS로 접속한다.
- 제어, 송출, 분석 토큰은 각각 별도 256비트 난수이며 서버 DB에는 SHA-256만 저장한다.
- 서버는 등록된 카메라에 대해 stream=true/false와 15초 lease만 보낸다.
  원격 셸/FFmpeg 인자/RTSP 주소 변경 기능은 없다.
- 제어 연결 종료 시 송출을 중지한다. 조용한 연결 장애도 마지막 lease 후 15초와
  프로세스 종료 대기 최대 3초 이내에 중지한다. 네트워크 단절 중 계속 분석하지 않는다.
- 실제 FFmpeg 출력 타임스탬프가 진행해야 streaming으로 표시한다. 이것은 서버의
  영상 수신 증명이 아니므로 서버 analysis_fresh/available와 실제 화면도 확인한다.
- 분석은 마지막으로 확인된 detection=cctv 모드 또는 관측된 CCTV 모드에서만 켜진다.
  사용 허용(enabled)만으로 난간 모드가 바뀌지 않는다. 카메라 없는 난간은 등록하지 않는다.
- 시청 lease는 45초, 화면은 10초마다 갱신. 마지막 시청 종료 후 약 10초 유예와
  제어 갱신 주기(5초) 후 송출 중지. CCTV 모드일 때에는 시청자 없이 계속 분석한다.
- 읽기 토큰은 사용자 세션/카메라에 묶이고 5분 만료, WebRTC는 4분마다 다시 연결한다.
  로그아웃/권한 철회 이후 새 인증은 거절된다. 이미 연결된 미디어는 최대 5분까지
  남을 수 있다(MediaMTX expireAt). 즉시 미디어 회수 기능은 포함하지 않았다.
- SRT passphrase는 영상 암호화용이며 송출 토큰과 다르다. SRT streamid 등 핸드셰이크
  메타데이터 전체를 TLS처럼 보호한다고 가정하지 않는다. 공인망 메타데이터 보호까지
  필요하면 SRT 경로를 VPN으로 제한한다. 송출 토큰만으로는 passphrase 없이 접속할 수 없다.
- FFmpeg 인자의 카메라 암호는 같은 계정/관리자가 프로세스 정보를 읽으면 볼 수 있다.
  전용 OS 계정, 0600 설정 파일, 로그/백업 접근 제한을 적용한다. Git에 비밀을 넣지 않는다.
- 기존 /api/analytics/events의 전체 analytics 토큰은 신뢰된 서버 운영용 레거시 권한이다.
  새 분석 프로세스에는 이 토큰 대신 카메라별 analysis_token만 사용한다.

## 1. 서버 업데이트와 카메라 등록

기존 통화를 종료하고 서버를 업데이트한다. 기존 MONITOR_* 환경변수와 DB는 유지한다.

```powershell
cd monitoring-server
git pull
mvn verify
mvn spring-boot:run
```

로그인 후 `https://omtest.duckdns.org/cctv-test.html`에 접속한다.
기본 cctv01은 gateway-01/난간 1에 연결되어 있다. 다른 현장은 기존 관리 화면에서
현장, 게이트웨이, 난간, 카메라를 등록하고 사용자 소속을 지정한다.
카메라 ID는 서버 전체에서 고유해야 한다. 난간 번호 1은 게이트웨이마다 반복 가능하다.

관리자로 **인증 정보 생성 → 등록/교체 → 설정용 토큰 복사**를 실행한다.
제어(control), 송출(publish), 분석(analysis) 토큰을 해당 장치의 설정 파일에 넣는다.
등록/교체는 카메라를 비활성화하고 기존 시청 lease를 제거한다.

SRT 암호화용 별도 passphrase를 PowerShell에서 생성한다:

```powershell
$b = New-Object byte[] 32
$r = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$r.GetBytes($b); $r.Dispose()
[Convert]::ToBase64String($b).TrimEnd('=').Replace('+','-').Replace('/','_')
```

이 값을 Pi 설정과 MediaMTX 해당 경로에 동일하게 입력한다. 토큰과 passphrase는 채팅에
붙이지 말고 자신의 설정 파일에 저장한다. 이전 공개된 카메라 암호는 교체하고
가능하면 카메라의 영상 조회 전용 계정을 사용한다.

## 2. MediaMTX와 Nginx

공식 MediaMTX **v1.21.2 Windows amd64** 배포본을 설치한다.
`mediamtx.example.yml`을 실제 `mediamtx.yml`로 복사하고 다음을 설정한다.

- cctv01_raw.srtPublishPassphrase: 방금 생성한 값
- 도메인이 다르면 webrtcAllowOrigins / webrtcAdditionalHosts 수정
- 추가 카메라마다 명시적인 `<camera_id>_raw` 경로와 별도 passphrase 추가
- all_others/익명 허용 경로를 추가하지 않는다.

기존 MediaMTX를 종료한 뒤 새 설정으로 실행한다:

```powershell
.\mediamtx.exe .\mediamtx.yml
```

`nginx-locations.conf` 조각을 기존 **443 server 블록**에 반영한다.
동일 location을 중복 추가하지 말고 이전 `/cctv/` 영상 프록시를 제거/교체한다.
일반 `/` → Spring Boot, 기존 난간/음성 WebSocket 설정과 ACME 설정은 유지한다.
사용자 지정 CSP가 있으면 WebRTC connect-src 'self', media-src 'self' blob:를 허용한다.
외부 요청의 X-Forwarded-*는 Nginx가 덮어쓰게 하고 Spring Boot는 loopback에 둔다.
운영 HTTPS에서는 `COOKIE_SECURE=true`와 기존 framework 전달 헤더 설정을 사용한다.

```powershell
cd C:\nginx
.\nginx.exe -t
.\nginx.exe -s reload
```

필요한 외부 포트:

| 포트 | 용도 |
|---|---|
| TCP 443 | 기존 웹/WSS 및 인증된 WebRTC SDP |
| UDP 8890 | 암호화 SRT 송출; 가능하면 현장 IP/VPN으로 제한 |
| UDP 8189 | WebRTC 미디어; 브라우저와 서버 사이 연결 |

8554, 8889, 8080은 **127.0.0.1 전용**, 외부 포트포워딩 금지.
외부 `/api/cctv/media-auth` 요청은 Nginx에서 404여야 한다.
이 콜백은 서버 로컬 MediaMTX만 사용한다. WebRTC/RTSP/SRT의 read/publish 권한은
콜백이 카메라·동작·프로토콜을 확인한다. 관리 API/녹화/HLS/RTMP/MoQ는 비활성화한다.
UDP가 차단된 기업망에서는 TURN 등 추가 구성이 필요하다. 현재 예제는 공개 UDP 서버
주소로 연결하는 구성이다. 카메라 영상은 브라우저 호환 H.264로 설정한다.
`-c:v copy`이므로 H.265 등은 자동으로 H.264 변환되지 않는다.

## 3. CCTV Pi

기존 수동 FFmpeg 명령과 기존 자동 송출 서비스를 종료해 중복 송출을 막는다.
**난간 PLC Pi가 아니라 카메라가 연결된 Pi**에서:

```bash
sudo apt update
sudo apt install ffmpeg python3-venv
cd ~/ecl_project/cctv-pi
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.json config.json
chmod 600 config.json
nano config.json
.venv/bin/python agent.py --config config.json
```

config.json의 카메라 RTSP 주소, control_token, publish_token, srt_passphrase를 입력한다.
암호에 @, :, # 등이 있으면 URL 인코딩한다. camera_id와 WSS 경로가 같아야 한다.
서버 인증서 검증을 끄지 않는다. TLS 오류는 인증서/시간부터 수정한다.

자동 실행 시 저장소를 `/opt/ecl_project`, 가상환경을 그 아래 cctv-pi/.venv에 두고
전용 cctv OS 계정을 만든다. 설정은 `/etc/ecl-cctv/config.json`, 소유자는 cctv,
권한 0600으로 설치한다. 예제 service의 경로가 실제와 같은지 확인한다.

```bash
sudo cp cctv-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cctv-agent
sudo journalctl -u cctv-agent -f
```

실행 프로그램/가상환경은 root 소유·읽기 실행 가능, 설정만 cctv가 읽을 수 있게 둔다.
처음에는 서비스로 올리기 전에 위 수동 실행으로 연결을 확인한다.

## 4. 서버 PC의 분석 프로그램

Python 3.11 별도 가상환경 사용. 우선 연령 분석을 끄고 사람 검출 연결부터 확인한다.

```powershell
cd analytics-server
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.json config.json
notepad config.json
.\.venv\Scripts\python.exe main.py --config config.json
```

analysis_token은 해당 카메라 전용 토큰이다. server_url은 같은 PC이면
http://127.0.0.1:8080으로 둔다. 다른 PC는 HTTPS를 사용한다.
Windows 설정 파일은 해당 실행 계정/관리자만 읽도록 ACL을 제한한다.
model은 신뢰한 YOLO11 모델 경로, device는 cpu 또는 GPU 환경에 맞는 값(예: "0")이다.
CUDA/PyTorch는 GPU에 맞춰 별도 설치하고 실제 추론을 검증한다.
카메라별 독립 프로세스/설정 파일로 시작하며, 30대 동시 GPU 처리 성능을 보장하지 않는다.

roi=[왼쪽,위,오른쪽,아래]는 0..1 비율이며 사람 박스의 발 위치로 진입을 판단한다.
처음 세 번 연속 감지 후 한 번 enter를 전송한다. 같은 track은 반복 카운트하지 않는다.
추적 ID가 바뀌는 심한 가림/재연결에서는 중복 진입이 가능하므로 실제 현장에서 ROI와
재진입 정책을 조정해야 한다. 영상/추론이 오래되면 이벤트를 보내지 않고 unavailable로 둔다.
현재 표시는 인원수/분석상태이며 영상에 박스 오버레이는 그리지 않는다.

MiVOLO는 이후 선택적으로 켠다. 기존 사용하던 검증된 MiVOLO v1 소스와
face+body 체크포인트를 사용하고 requirements-age.txt를 설치한다.
config의 age.enabled=true, repo, checkpoint, device를 지정한다.
몸 기반 연령 추정값을 실제 나이로 취급하지 않는다. 두 샘플이 준비되고 지원하는
10/20/30/40 구간일 때만 age, 그 외에는 keep을 보낸다. 모델 실패도 사람 검출은 유지한다.
1.5초 안에 연령이 준비되지 않으면 keep을 큐에 넣지만, GPU/네트워크 지연에 따라
P4의 2초 대기를 넘을 수 있다. 실제 슬립→기상 음악 선택은 장비에서 확인해야 한다.
이벤트/재시도는 원래 UUID와 시간을 유지하고 오래된 작업은 재생하지 않는다.
영상 녹화나 얼굴 이미지 저장은 하지 않는다.

## 5. 성공 확인 순서

1. 로그인 → `/cctv-test.html` → CCTV 사용 허용 → 상태 조회.
   device.connected=true, 레이더 모드·시청자 없으면 camera.wanted=false.
2. 영상 보기. Pi starting→streaming, 브라우저에 실제 움직이는 영상이 보여야 한다.
   이 시점에는 분석이 꺼져 있어도 정상이다.
3. 보기 종료. 레이더 모드라면 유예 후 FFmpeg가 종료되는지 확인한다.
4. 기존 난간 제어 화면에서 detection=cctv를 보내고 **장치 확인 성공**을 기다린다.
   이 모드 확인이 실패하면 자동 분석을 켰다고 가정하지 않는다.
5. analytics-server 실행. 시청자 없어도 wanted=true, analysis=true,
   analysis_fresh=true, analysis_state.available=true를 확인한다.
6. ROI로 실제 사람이 진입했을 때 난간 Pi 로그에 CCTV 이벤트가 도착하고
   P4의 실제 감지/슬립 해제가 수행되는지 확인한다. PLC_SENT는 P4 적용 확인과 다르다.
7. detection=radar로 확인 전환 → 시청자 없으면 분석과 송출 종료.
8. 다른 현장 사용자/잘못된 토큰/다른 camera_id로 조회·전송이 거절되는지 확인한다.
9. CCTV Pi 인터넷 끊기 → lease 만료/송출 중지 → 재접속 시 현재 서버 요구만 수행.

통화 중 PLC가 BUSY이면 CCTV 이벤트가 적용되지 않을 수 있다. 만료된 감지를 뒤늦게
재생하지 않는다. Pi·P4·WROOM·S3의 기존 CCTV 입력 규약은 변경하지 않았다.

## 검증 범위와 운영

자동 테스트는 인증/권한/수요 제어/분석 이벤트의 게이트웨이 전달, lease 만료,
중복 검출 및 연령 실패 처리를 검증한다. 실제 카메라 코덱, NAT/방화벽, GPU 가중치,
난간 슬립 복귀 및 다중 카메라 처리량은 현장 확인 대상이다.

공식 참고:
- https://mediamtx.org/docs/features/authentication
- https://mediamtx.org/docs/features/srt-specific-features
- https://github.com/bluenviron/mediamtx/releases/tag/v1.21.2
- 이전 분석 어댑터: https://github.com/kalmans251/ECO_LUMINOUS_CCTV_YOLO_MIVOLO
