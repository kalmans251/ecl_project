# 처음부터 다시 연결하기: DB 초기화 → 서버 → 난간 Pi → CCTV

이 문서 하나를 위에서 아래로 따라가면 **기본 현장 1개, 난간 1번, 카메라 cctv01**을
새 DB에서 연결할 수 있다. Windows 서버는 omtest.duckdns.org, Nginx는 C:\nginx,
MediaMTX는 C:\mediamtx를 예로 든다. 설치 위치가 다르면 경로만 변경한다.

**이 절차는 테스트 환경의 완전 재설정이다. 평소 서버 재시작 때는 DB를 지우지 않는다.**
평소 종료·재실행은 마지막 12절을 사용한다.
여기서는 삭제 대신 기존 DB와 Pi 기록을 날짜별 백업으로 옮겨 새 파일로 시작한다.
관리자 계정, 사용자/현장/장치 등록, 카메라 인증, 통화/명령/이벤트 기록은 새 DB에 승계되지 않는다.
인증서, SD 음악 파일, 펌웨어는 삭제하지 않는다.

## 0. 터미널과 장비 구분

| 이름 | 실행 위치 | 실행 내용 |
|---|---|---|
| 서버 창 A | Windows 서버 PC PowerShell | 토큰 생성, Spring Boot |
| 서버 창 B | 같은 PC PowerShell | Nginx 검사·재적용, MediaMTX |
| 서버 창 C | 같은 PC PowerShell | YOLO 분석 |
| 난간 Pi 창 | PLC에 연결된 Pi 4B | raspberry-pi/main.py |
| CCTV Pi 창 | 카메라에 연결된 별도 Pi | cctv-pi/agent.py |

난간 Pi와 CCTV Pi는 다른 장치다. 난간 Pi는 /dev/serial0으로 PLC를 제어하고,
CCTV Pi는 카메라 RTSP를 받아 서버로 송출한다.
명령 블록의 PowerShell은 Windows에서, bash는 해당 Pi에서 실행한다.
미리 서버 PC에는 Git, Java 17, Maven 3.9+, Nginx, MediaMTX v1.21.2,
분석용 Python 3.11을 설치한다. 기존 HTTPS 인증서가 유효해야 한다.

## 1. 기존 실행을 전부 정리

1. 모니터링에서 활성 통화를 모두 종료하고 종료 확인을 받는다.
2. CCTV 보기 종료 및 CCTV 사용 중지. 분석 프로그램과 CCTV Pi 에이전트/기존 FFmpeg를 종료한다.
3. 난간 Pi의 main.py는 quit으로 종료한다. hardware_test.py, voice_send.py,
   mock_gateway.py와 자동 재시작 서비스도 함께 종료한다.
4. Windows Spring Boot는 실행 창에서 Ctrl+C로 종료한다.
5. 기존 MediaMTX도 실행 창에서 Ctrl+C로 종료한다. 서비스라면 해당 서비스를 중지한다.
6. 연결된 **모든 난간의 P4·WROOM·S3 전원을 끄고**, Pi 송수신 프로세스가 멈춘 상태에서
   다시 켠다. 전원 상태나 릴레이 출력이 바뀔 수 있으므로 시험 가능한 상태에서 수행한다.

DB 초기화는 이벤트 번호도 새로 시작하게 만든다. P4의 이전 이벤트/통화 RAM 상태와
새 서버 기록을 섞지 않기 위해 난간 보드도 재부팅한다.
통화 종료 확인이 안 되었을 때는 기록만 지워 잠금을 우회하지 않는다.
이 완전 초기화 절차에서는 실제 보드를 전원 재투입해 이전 통화가 끝났음을 확인한 뒤 진행한다.

Nginx는 실행 중이어도 된다. Spring Boot가 내려간 동안 502가 보일 수 있다.
자동 실행 서비스 이름은 설치마다 다르므로 임의의 서비스 이름으로 중지 명령을 실행하지 않는다.

## 2. 서버 DB를 백업으로 옮겨 초기화

서버 창 A에서 **자신의 저장소 경로**로 이동한다.
아래 C:\work\ecl_project는 예시이므로 실제 경로로 바꾼다.

```powershell
cd C:\work\ecl_project
git pull

$repoRoot = (Get-Location).Path
Set-Location "$repoRoot\monitoring-server"

Get-Location
$env:DATABASE_URL
Get-ChildItem .\data -ErrorAction SilentlyContinue
```

기본 DB URL은 jdbc:h2:file:./data/monitoring이다.
monitoring-server 폴더에서 실행했으면 DB는 그 아래 data\monitoring.mv.db에 있다.
DATABASE_URL을 따로 설정했거나 다른 작업 폴더에서 JAR를 실행했다면 위치가 다를 수 있다.
그 경우 실제 DB 위치부터 확인한다. 이 문서의 초기화 명령은 **기본 로컬 H2 구성에만** 해당한다.

서버가 완전히 종료된 후, 아래를 실행한다. 잠금/이동 실패가 나면 강제로 삭제하지 말고
Spring Boot 또는 관련 서비스가 아직 실행 중인지 확인한다.

```powershell
if ($env:DATABASE_URL -and $env:DATABASE_URL -ne "jdbc:h2:file:./data/monitoring") {
    throw "사용자 지정 DATABASE_URL입니다. 실제 DB 경로를 확인한 뒤 별도 백업하세요."
}

$stamp = Get-Date -Format yyyyMMdd-HHmmss
if (Test-Path .\data) {
    $backupRoot = Join-Path $env:LOCALAPPDATA "ECL\backups"
    New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
    $backup = Join-Path $backupRoot "monitoring-data-$stamp"
    Move-Item -LiteralPath .\data -Destination $backup -ErrorAction Stop
    Write-Host "기존 DB 백업: $backup"
}

$env:DATABASE_URL = "jdbc:h2:file:./data/monitoring"
```

기존 DB를 옮겼으므로 다음 서버 시작 시 data 폴더와 DB가 새로 생성된다.
H2 콘솔을 열거나 DB 비밀번호를 바꿀 필요는 없다.
백업은 저장소 밖의 %LOCALAPPDATA%\ECL\backups에 보관된다.
백업에는 계정·장치 인증 정보의 해시 및 운영 기록이 들어 있으므로 공개하지 않는다.

## 3. 난간 Pi의 이전 통화·명령 기록도 새로 시작

**1절의 모든 프로세스 종료와 난간 보드 재부팅을 완료했을 때만** 이 단계를 실행한다.
평소 서버 재시작이나 hangup 실패 해결을 위해 이 기록을 지우면 안 된다.

Pi의 기본 기록은 다음과 같다:

- ~/.local/state/ecl-railing/calls.json: 미확정 통화 세션
- ~/.local/state/ecl-railing/music-requests.sqlite3: 원격 명령 중복 방지 및 웹 통화 연결 기록

난간 Pi에서 확인하고 기본 기록 폴더를 통째로 백업한다. SQLite 보조 파일도 함께 이동된다.

```bash
printf 'ECL_CALL_STATE_FILE=%s\n' "$ECL_CALL_STATE_FILE"
ls -la "$HOME/.local/state/ecl-railing"

# 기본 경로를 사용한 경우에만:
state_dir="$HOME/.local/state/ecl-railing"
if [ -d "$state_dir" ]; then
    backup_dir="${state_dir}.backup-$(date +%Y%m%d-%H%M%S)"
    mv -- "$state_dir" "$backup_dir" || exit 1
    printf '이전 Pi 기록 백업: %s\n' "$backup_dir"
fi
```

--call-state-file, --music-journal 또는 ECL_CALL_STATE_FILE로 다른 경로를 사용했다면
그 실제 경로를 기준으로 백업해야 한다. 다른 사용자/root로 실행했던 기록도 위치가 다르다.
이후 같은 사용자와 같은 경로로 실행한다. 이 단계는 펌웨어 초기화나 SD 음악 삭제가 아니다.

## 4. 새 서버 토큰과 관리자 계정으로 시작

서버 창 A는 계속 monitoring-server 폴더에 둔다.
다음은 **빈 DB 최초 시작 때 한 번** 실행한다.

```powershell
function New-Token {
    $b = New-Object byte[] 32
    $r = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $r.GetBytes($b)
    $r.Dispose()
    [Convert]::ToBase64String($b)
}

$env:MONITOR_ADMIN_TOKEN = New-Token
$env:MONITOR_ANALYTICS_TOKEN = New-Token
$env:MONITOR_GATEWAY_TOKEN = New-Token
$env:MONITOR_BOOTSTRAP_USER = "admin"

$bootstrapPassword = Read-Host "새 관리자 비밀번호 (12자 이상)" -AsSecureString
$env:MONITOR_BOOTSTRAP_PASSWORD = (
    New-Object System.Net.NetworkCredential("", $bootstrapPassword)
).Password
Remove-Variable bootstrapPassword

$env:SERVER_ADDRESS = "127.0.0.1"
$env:SERVER_FORWARD_HEADERS_STRATEGY = "framework"
$env:COOKIE_SECURE = "true"

# 다음 난간 Pi 단계에서 입력할 값. 자신의 PC 화면에서만 확인한다.
Write-Host "난간 Pi에 입력할 Gateway 토큰:"
Write-Host $env:MONITOR_GATEWAY_TOKEN
Set-Clipboard -Value $env:MONITOR_GATEWAY_TOKEN

mvn verify
if ($LASTEXITCODE -ne 0) {
    throw "빌드/검증 실패. 위 오류를 해결한 다음 실행하세요."
}
mvn spring-boot:run
```

이 설정은 현재 PowerShell 프로세스에만 적용된다. 시스템 환경변수나 파일로 자동 저장하지 않는다.
따라서 **이 창을 닫으면 토큰은 환경변수에서 사라진다**.
영구 저장을 하지 않으려면 실행·재시작 동안 이 창을 유지한다.
나중에 새 창에서 기존 DB를 유지해 시작하려면 동일한 값을 다시 넣어야 한다.
특히 gateway-01의 토큰 해시는 DB에 저장되므로 환경변수에서 새 토큰을 생성해도
기존 게이트웨이 등록 토큰은 자동으로 바뀌지 않는다.

MONITOR_BOOTSTRAP_PASSWORD도 빈 DB의 관리자 생성에만 적용된다.
이후 환경변수를 바꿔도 기존 admin 비밀번호는 바뀌지 않는다.

최초 DB에는 다음 연결이 기본 등록된다:

| 항목 | 값 |
|---|---|
| 현장 | site-01 |
| 게이트웨이 | gateway-01 |
| 난간 번호 | 1 |
| 카메라 | cctv01 |

기본 카메라 행은 만들어지지만 CCTV 제어/송출/분석 인증은 아직 등록되지 않았다.
카메라 인증은 8절에서 따로 생성한다.

## 5. Nginx 적용 및 관리자 로그인

서버 창 B에서 저장소 경로를 자신의 위치로 지정한다.

```powershell
$repoRoot = "C:\work\ecl_project"
$nginxDir = "C:\nginx"
$stamp = Get-Date -Format yyyyMMdd-HHmmss

Copy-Item "$nginxDir\conf\nginx.conf" "$nginxDir\conf\nginx.conf.$stamp.bak"
Copy-Item "$repoRoot\deployment\cctv\nginx.conf" "$nginxDir\conf\nginx.conf"
notepad "$nginxDir\conf\nginx.conf"
```

도메인 및 인증서 경로가 실제 파일과 같은지 확인한다.
기존 인증서/개인 키는 삭제하지 않는다. 이미 PR #82의 설정을 적용했다면
복사를 반복할 필요 없이 현재 설정을 검사하면 된다.

```powershell
cd C:\nginx
.\nginx.exe -t
if ($LASTEXITCODE -eq 0) {
    .\nginx.exe -s reload
}
```

Nginx가 실행 중이지 않으면 검사 성공 후 .\nginx.exe로 시작한다.
이제 https://omtest.duckdns.org/function-test.html 에 접속한다.
admin과 **4절에서 입력한 관리자 비밀번호**로 로그인하고 Ctrl+F5로 갱신한다.
COOKIE_SECURE=true이므로 http://localhost:8080 대신 위 HTTPS 주소를 사용한다.
이전 DB의 브라우저 로그인 세션은 다시 로그인해야 한다.

로그인에 실패하면 비밀번호를 무작정 새로 생성하지 말고,
실제로 2절의 DB 위치를 초기화했는지, 올바른 서버 인스턴스에 접속했는지 확인한다.

## 6. 난간 Pi 게이트웨이 연결

난간 Pi에서 자신의 저장소 경로로 이동한다. 이전 작업 경로 예시는 다음과 같다.

```bash
cd ~/ecl_prj/ecl_project
git pull
cd raspberry-pi

# 가상환경이 없을 때만 생성
test -d .venv || python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-monitoring.txt

# UART는 main.py 한 프로세스만 사용해야 한다.
ls -l /dev/serial0
sudo fuser -v /dev/serial0

read -rs -p 'Gateway token: ' MONITOR_GATEWAY_TOKEN
printf '\n'
export MONITOR_GATEWAY_TOKEN
```

입력 대기 상태에서 **서버 창 A에서 생성한 MONITOR_GATEWAY_TOKEN 값**을 붙여 넣고 Enter.
보안 입력이므로 글자가 보이지 않는 것이 정상이다.
토큰 앞뒤에 따옴표나 공백을 붙이지 않는다. 토큰을 URL에 넣지 않는다.

fuser에 다른 프로그램이 표시되었다면 그 프로그램을 종료한 후 실행한다.

```bash
python main.py \
  --port /dev/serial0 \
  --baud 9600 \
  --event-railings 1 \
  --monitor-url wss://omtest.duckdns.org/ws/gateways/gateway-01 \
  --web-voice
```

- 이 명령 하나가 일반 제어·음악 상태·웹 통화 연결을 담당한다.
- --monitor-url을 사용하면 음악 상태 동기화도 켜진다.
- --web-voice에서는 PC 브라우저 마이크를 사용한다.
  --local-audio를 붙이거나 voice_send.py를 따로 실행하지 않는다.
- 기본 PLC 핀은 Pi 4B GPIO14/15, 물리 핀 8/10, /dev/serial0이다.
- 설치 난간이 여러 대면 --event-railings 1,2,3처럼 실제 번호만 적는다.
- Music monitoring connection established 로그는 정상적인 서버 연결 메시지이며 통화 시작이 아니다.

모니터링에서 기본 현장/난간 1을 선택하고 P4·WROOM·S3 조회를 한다.
게이트웨이 온라인 표시만으로 실제 장치 통신까지 성공했다고 보지는 않는다.
장치 조회의 확인 응답과 실제 LED·음악 동작을 확인한 후 CCTV로 넘어간다.

## 7. 웹 통화와 기본 제어 확인

/function-test.html에서 다음 순서로 검사한다:

1. P4/WROOM/S3 조회가 확인 응답으로 완료되는지 확인.
2. LED basic/music, 음악 목록 조회·선택·재생·일시정지·재개와 볼륨을 확인.
3. 통화 시작·듣기 → 난간 마이크 소리가 PC로 들리는지 확인.
4. 말하기·마이크 켜기 → 브라우저 마이크 권한 허용 → 난간 스피커로 말이 나오는지 확인.
5. 듣기·마이크 끄기 → 다시 난간 소리를 듣고, 통화 종료 확인.
6. 통화 종료 후 일반 조회가 다시 가능한지 확인.

웹 통화 모드에서 Pi 콘솔 call/ptt/hangup이 웹 버튼 사용을 안내하는 것은 정상이다.
실패한 통화는 종료 확인으로 해소한다. UNKNOWN 상태를 단순 DB 삭제로 정상 처리하지 않는다.
CCTV 설정은 우선 통화가 종료된 상태에서 진행한다.

## 8. 카메라 인증 정보 등록

https://omtest.duckdns.org/cctv-test.html 에 로그인 상태로 접속한다.

1. 카메라 ID를 cctv01로 둔다.
2. 인증 정보 생성.
3. 등록 / 교체.
4. 설정용 토큰 복사.

복사한 JSON에서 다음 세 값을 구분한다. 이들은 4절의 서버 공통 토큰과 다른 값이다.

| 값 | 넣을 곳 |
|---|---|
| control_token | CCTV Pi config.json |
| publish_token | CCTV Pi config.json |
| analysis_token | 서버 PC analytics-server/config.json |

등록 시 카메라는 비활성화된다. 아래 MediaMTX/Pi 설정을 마친 뒤 CCTV 사용 허용을 누른다.
서버 DB를 새로 만들었으므로 예전 CCTV Pi/분석 설정의 토큰도 새 값으로 교체해야 한다.

## 9. MediaMTX 암호화 설정과 실행

서버 창 B에서 MediaMTX 폴더를 준비한다. 공식 v1.21.2 Windows amd64 기준이다.
파일이 이미 설치되어 있다면 재설치할 필요 없이 버전을 확인한다.
토큰과 다른 **SRT 암호화 키**를 한 번 생성한다.

```powershell
$b = New-Object byte[] 32
$r = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$r.GetBytes($b)
$r.Dispose()
$srtPassphrase = [Convert]::ToBase64String($b).TrimEnd('=').Replace('+','-').Replace('/','_')
Write-Host $srtPassphrase
Set-Clipboard -Value $srtPassphrase
```

이 값을 MediaMTX와 CCTV Pi 두 곳에 동일하게 사용한다.

```powershell
$repoRoot = "C:\work\ecl_project"
$mediaDir = "C:\mediamtx"
$stamp = Get-Date -Format yyyyMMdd-HHmmss

if (Test-Path "$mediaDir\mediamtx.yml") {
    Copy-Item "$mediaDir\mediamtx.yml" "$mediaDir\mediamtx.yml.$stamp.bak"
}
Copy-Item "$repoRoot\deployment\cctv\mediamtx.example.yml" "$mediaDir\mediamtx.yml"
notepad "$mediaDir\mediamtx.yml"
```

cctv01_raw 아래 srtPublishPassphrase의 REPLACE_WITH_...를 방금 생성한 값으로 바꾼다.
SRT 키는 control_token이나 publish_token으로 대신하지 않는다.

```powershell
cd C:\mediamtx
.\mediamtx.exe --version
.\mediamtx.exe .\mediamtx.yml
```

MediaMTX는 계속 실행해 둔다. 정상 대기 중 로그가 적은 것은 logLevel=warn 때문일 수 있다.

서버 방화벽/공유기에서 다음을 확인한다:

| 포트 | 목적 |
|---|---|
| TCP 80 | 기존 인증서 HTTP 검증 |
| TCP 443 | 웹/WSS/영상 연결 요청 |
| UDP 8890 | CCTV Pi SRT 송출 수신 |
| UDP 8189 | 브라우저 WebRTC 영상 |

8080/8554/8889/9997은 서버 localhost 전용이며 외부 포트포워딩하지 않는다.
Nginx 설정만 바꿔서는 UDP 포트가 열리지 않는다.
다른 PowerShell에서 아래를 확인한다.

```powershell
curl.exe -i http://127.0.0.1:9997/v3/webrtcsessions/list
curl.exe -i https://omtest.duckdns.org/api/cctv/media-auth
```

첫 응답은 200, 두 번째는 **404가 정상**이다.
인증서 오류를 -k로 우회하지 않는다.

## 10. CCTV Pi 연결과 실제 영상 확인

**카메라에 연결된 별도 Pi**에서 수행한다. 이전 수동 FFmpeg 송출은 종료한다.
저장소가 아직 없다면 git clone https://github.com/kalmans251/ecl_project.git 로 받는다.
이미 있다면 그 폴더에서 git pull 후 진행한다.

```bash
cd ~/ecl_project
git pull
cd cctv-pi

sudo apt update
sudo apt install ffmpeg python3-venv
test -d .venv || python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 처음에만 복사. 이미 있다면 기존 파일을 열어 토큰을 교체한다.
test -f config.json || cp config.example.json config.json
chmod 600 config.json
nano config.json
```

설정 내용의 형태는 다음과 같다. REPLACE_...를 실제 로컬 값으로 바꾼다.

```json
{
  "camera_id": "cctv01",
  "control_url": "wss://omtest.duckdns.org/ws/cameras/cctv01",
  "control_token": "REPLACE_WITH_NEW_CONTROL_TOKEN",
  "camera_url": "rtsp://VIEW_ONLY_USER:URL_ENCODED_PASSWORD@192.168.1.2:554/1/2",
  "server_host": "omtest.duckdns.org",
  "publish_token": "REPLACE_WITH_NEW_PUBLISH_TOKEN",
  "srt_passphrase": "REPLACE_WITH_SAME_SRT_PASSPHRASE_AS_MEDIAMTX"
}
```

RTSP 주소와 IP는 실제 카메라 설정에 맞춘다.
카메라 암호의 @, :, # 등은 URL 인코딩하며 영상은 H.264로 설정한다.
이 에이전트는 영상 코덱을 변환하지 않고 복사 송출한다.
분석 토큰이나 난간 게이트웨이 토큰은 이 파일에 넣지 않는다.

```bash
.venv/bin/python agent.py --config config.json
```

웹 /cctv-test.html에서 CCTV 사용 허용 → 상태 조회를 한다.

- device.connected=true: CCTV Pi 제어 연결 정상.
- camera.media_control_ready=true: MediaMTX 관리 API 접근 정상.
- 레이더 모드·시청자 없음일 때 wanted=false: 불필요한 송출을 쉬는 정상 상태.

영상 보기를 누르면 Pi가 송출을 시작하고 실제 영상이 표시되어야 한다.
레이더 모드에서 보기 종료 후 유예 시간이 지나면 송출이 중지되어야 한다.
이 단계까지는 YOLO 분석을 실행하지 않아도 된다.

## 11. 서버 영상 분석 → 난간 제어 연결

서버 창 C에서 분석용 Python 3.11 환경을 준비한다.

```powershell
cd C:\work\ecl_project\analytics-server
if (-not (Test-Path .\.venv)) {
    py -3.11 -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .\config.json)) {
    Copy-Item .\config.example.json .\config.json
}
notepad .\config.json
```

먼저 연령 분석을 끄고 사람 검출부터 연결한다.

```json
{
  "camera_id": "cctv01",
  "server_url": "http://127.0.0.1:8080",
  "analysis_token": "REPLACE_WITH_NEW_ANALYSIS_TOKEN",
  "model": "yolo11n.pt",
  "device": "cpu",
  "roi": [0, 0, 1, 1],
  "age": {
    "enabled": false,
    "repo": "MiVOLO",
    "checkpoint": "models/mivolo_imdb.pth.tar",
    "device": "cpu"
  }
}
```

모델 파일은 신뢰하는 YOLO11 가중치를 사용한다. 처음 자동 다운로드가 필요한 환경에서는
인터넷 접근과 다운로드 완료를 확인한다. GPU 사용은 호환 CUDA/PyTorch 설치 후
device를 "0" 등으로 바꾸어 확인한다. CPU 설정은 연결 확인용이며 처리 속도를 보장하지 않는다.

모니터링 난간 제어 화면에서 **난간 1의 감지 모드를 CCTV로 전환하고 확인 응답을 기다린다.**
CCTV 사용 허용만 누르는 것은 난간의 감지 모드 전환이 아니다.

```powershell
.\.venv\Scripts\python.exe main.py --config config.json
```

웹 상태에서 다음을 확인한다:

- camera.analysis=true
- camera.wanted=true
- camera.analysis_fresh=true
- camera.analysis_state.available=true

영상 보기 창을 닫아도 CCTV 감지 모드에서는 분석용 송출이 계속된다.
실제 사람이 ROI에 들어오면 해당 카메라와 연결된 난간 Pi로 이벤트가 전달되는지,
P4의 감지/슬립 복귀가 실제 발생하는지 확인한다.
PLC_SENT는 Pi의 전송 결과이며 P4의 물리 동작 확인을 대신하지 않는다.
비상/통화로 BUSY이면 이벤트가 적용되지 않을 수 있으며 만료된 감지는 나중에 재생하지 않는다.

연령별 음악은 사람 검출 연결을 확인한 다음
[전체 CCTV 안내의 분석 프로그램 절](cctv/README.md#4-서버-pc의-분석-프로그램)에 따라
검증된 MiVOLO v1 소스·가중치를 설치하고 age.enabled를 켠다.
연령 추정 실패/지연은 keep으로 처리하며 정확한 실제 나이를 보장하지 않는다.

## 12. 이후 평소 종료·재시작: DB 초기화 없이

### 종료

1. 웹 통화 종료 확인.
2. 시험을 마칠 때 CCTV 사용 중지·보기 종료.
3. 분석 프로그램 종료, CCTV Pi 에이전트 종료.
4. 난간 Pi main.py에서 quit.
5. Spring Boot와 MediaMTX 실행 창에서 Ctrl+C.
6. Nginx까지 종료하려면 C:\nginx에서 .\nginx.exe -s quit.

서비스로 실행한 프로그램은 해당 서비스로 종료한다.
화면만 닫아 자동 실행 프로그램이 남지 않도록 한다.

### 다시 실행

1. **DB와 Pi 기록은 그대로 둔다. 토큰 생성 버튼을 다시 누르지 않는다.**
2. 서버 창 A를 유지했다면 monitoring-server에서 mvn spring-boot:run만 실행한다.
3. Nginx가 꺼졌으면 설정 검사 후 시작. MediaMTX를 같은 mediamtx.yml로 실행한다.
4. 난간 Pi에서 가상환경 활성화, 같은 게이트웨이 토큰을 입력하고 6절 명령 실행.
5. CCTV Pi를 기존 config.json으로 실행.
6. 웹 로그인, CCTV 사용 허용, 필요하면 난간 CCTV 모드 확인 후 분석 프로그램 실행.

서버 창을 닫았거나 PC가 재부팅됐다면 임시 환경변수는 사라진다.
기존 토큰을 안전하게 별도 보관했다면 동일한 값으로 다시 설정한다.
보관하지 않았고 등록된 게이트웨이 토큰도 모른다면, 새 난수를 만드는 것만으로
기존 DB의 gateway-01 인증이 갱신되지는 않는다.
정상 재시작과 완전 초기화를 혼동하지 말고 등록 장치 인증을 복구해야 한다.

CCTV Pi와 분석 프로그램의 config.json, MediaMTX passphrase는 운영 파일에 보관된다.
이는 서버 MONITOR_* 환경변수를 영구 저장하지 않는 선택과 별개다.
새 DB로 초기화한 경우에는 8절에서 새로 등록한 카메라 토큰을 두 설정 파일에 다시 반영한다.

## 13. 막혔을 때 확인할 위치

| 현상 | 확인 |
|---|---|
| admin 로그인 실패 | 실제 DB 경로, 최초 입력 비밀번호, HTTPS, 올바른 서버 |
| Gateway 토큰 오류 | 새 DB에 등록한 4절 토큰과 Pi 값 일치 여부 |
| 게이트웨이는 온라인인데 난간 조회 실패 | UART 독점, /dev/serial0, PLC 및 P4 응답 |
| call unknown/버튼 잠김 | 통화 종료 확인; 정상 운영에서는 기록 삭제 금지 |
| Music monitoring connection established | 정상 게이트웨이 연결 로그, 통화 시작 아님 |
| /cctv-test.html 404 | 서버 코드 업데이트와 실행 인스턴스 |
| CCTV device.connected=false | control_token/URL, WSS와 인증서 |
| media_control_ready=false | MediaMTX 9997 localhost 관리 API |
| 영상이 안 나옴 | 카메라 사용 허용, publish_token, passphrase, UDP 8890/8189, H.264 |
| 영상은 정상인데 분석 불가 | analysis_token, CCTV 감지 모드 확인, 모델/추론 지연 |
| cctv01과 난간 연결이 다름 | 관리 화면의 카메라 → 난간 → 게이트웨이 매핑 |

여러 현장/사용자는 현장 권한, 게이트웨이 ID·토큰, 고유 카메라 ID를 각각 나누고
카메라별 MediaMTX 경로·분석 프로세스를 추가한다.
자세한 추가 방법은 [Windows CCTV 가이드](cctv/WINDOWS_SETUP.md#7-여러-난간사용자카메라-추가)를 참고한다.
