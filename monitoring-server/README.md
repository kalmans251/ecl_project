# Monitoring server — 모니터링 화면과 현장별 제어 서버

Spring Boot 4.1.1 / Java 17 / Maven 3.9+. 기존 모니터링 화면을 새 계정·현장 권한·장치 명령 구조에 연결했습니다.

화면 이식 범위와 지원 상태는 [UI_MIGRATION.md](UI_MIGRATION.md), 새 Pi 어댑터 규격은 [DEVICE_PROTOCOL.md](DEVICE_PROTOCOL.md)를 확인하세요.
기존 Pi/P4/WROOM/S3 펌웨어는 이 변경에서 수정하지 않습니다. 실물 연결에는 새 서버 규격을 처리하는 Pi 어댑터가 필요합니다.

## 실행

Java 17과 Maven 3.9+를 설치합니다. 기본은 **127.0.0.1:8080**에만 바인딩됩니다.
인증 토큰이 비어 있거나, 서로 같거나, 32자 미만이면 시작하지 않습니다.
각 토큰은 비밀번호처럼 관리하고 Git에 저장하지 않습니다.

PowerShell (서버 터미널):

```powershell
cd monitoring-server
function New-Token { $b = New-Object byte[] 32; $r = [System.Security.Cryptography.RandomNumberGenerator]::Create(); $r.GetBytes($b); $r.Dispose(); [Convert]::ToBase64String($b) }
$env:MONITOR_ADMIN_TOKEN = New-Token
$env:MONITOR_ANALYTICS_TOKEN = New-Token
$env:MONITOR_GATEWAY_TOKEN = New-Token
$env:MONITOR_BOOTSTRAP_USER = "admin"
$env:MONITOR_BOOTSTRAP_PASSWORD = Read-Host "최초 관리자 비밀번호 (12자 이상)"
mvn verify
mvn spring-boot:run
```

브라우저에서 http://localhost:8080 을 열어 위 관리자 계정으로 로그인합니다.
최초 빈 DB에만 관리자를 생성합니다. 이후 환경변수 변경은 기존 비밀번호를 바꾸지 않습니다.

다른 테스트 터미널에는 해당 역할의 토큰만 같은 값으로 설정합니다.
서버를 다시 실행할 때 기존 토큰을 다시 설정해야 합니다. 토큰은 URL이나 로그에 넣지 않습니다.

Linux/macOS에서는 세 토큰과 최초 관리자 비밀번호 환경변수를 export한 뒤 같은 Maven 명령으로 실행합니다.
패키징: `mvn verify`, 실행: `java -jar target/monitoring-server-0.1.0.jar`.
Docker: 세 토큰과 최초 관리자 비밀번호 환경변수를 설정하고 `docker compose up --build`.
Docker 볼륨에는 DB가 보존되며 `down -v`는 이벤트 번호/기록을 삭제하므로 운영 중 사용하지 않습니다.

## 로컬 동작 테스트

실제 Pi 없이 서버의 전달 경로를 확인합니다.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r tools/requirements.txt
# gateway 토큰을 설정한 터미널
python tools/mock_gateway.py --simulate-device
# analytics 토큰을 설정한 별도 터미널
python tools/send_event.py
```

`send_event.py`가 출력한 `event_id`를 복사하여 즉시 연령 결과를 보냅니다.

```powershell
python tools/send_event.py --type age --event-id <출력된-UUID> --age-group 20
```

모의 클라이언트에서 두 메시지의 `event_seq`가 같은지 확인합니다.
기본 모의 클라이언트는 RECEIVED만 응답합니다. `--simulate-device`를 추가하면 화면 확인용 가짜 계측과 APPLIED/PLC_SENT 응답도 생성합니다. 실제 PLC나 스피커를 제어하지 않습니다.
연결 상태 및 전달 결과 조회 (관리자 토큰 터미널):

```powershell
$headers = @{ Authorization = "Bearer $env:MONITOR_ADMIN_TOKEN" }
Invoke-RestMethod http://127.0.0.1:8080/api/gateways -Headers $headers
Invoke-RestMethod http://127.0.0.1:8080/api/events/<message_id> -Headers $headers
```

## 인증과 매핑

| 경로 | 인증 | 용도 |
|---|---|---|
| POST /api/analytics/events | analytics Bearer 토큰 | 분석 이벤트 입력 |
| GET /api/gateways | admin Bearer 토큰 | 장치 연결 상태 |
| GET /api/events/{message_id} | admin Bearer 토큰 | 처리 상태 |
| /ws/gateways/{gateway_id} | 해당 gateway Bearer 토큰 | 네이티브 Pi WebSocket |

초기 카메라→gateway→난간 매핑은 `application.yml`에서 DB에 한 번 등록합니다. 이후 추가는 화면의 관리 메뉴에서 합니다.
초기값은 **cctv01 → gateway-01 → 난간 1**입니다. 한 Pi의 여러 난간은 동일 gateway에 매핑합니다.
카메라 없는 난간에는 camera 항목을 추가하지 않습니다. gateway 토큰은 장치별로 다르게 지정합니다.
설정은 서버 운영자가 관리하며 분석 요청이 임의의 난간 번호를 지정할 수 없습니다.
브라우저 Origin이 있는 장치 WebSocket 요청은 거절합니다. 웹 화면은 별도 세션 인증과 현장 권한을 사용합니다.

## 분석 입력 규격

새로운 방문/진입 사건마다 UUID를 생성합니다. ByteTrack ID 자체는 재시작/재연결 때 재사용될 수 있어
event_id로 직접 사용하지 않습니다. 같은 사람을 매 프레임마다 enter로 보내지 않습니다.
가림 후 ID 변경, 재진입 기준, 관심 영역은 분석 프로그램에서 결정해야 합니다.

```json
{"camera_id":"cctv01","event_id":"1e10e004-c1cd-49c5-b32a-872c2a489e63","type":"enter","observed_at":"2026-10-07T08:00:00Z"}
```

```json
{"camera_id":"cctv01","event_id":"1e10e004-c1cd-49c5-b32a-872c2a489e63","type":"age","age_group":"20","observed_at":"2026-10-07T08:00:01Z"}
```

- 시간은 UTC/offset ISO-8601. 서버/분석 PC/Pi의 시계를 동기화합니다.
- 입력은 발생 후 5초 이내, 미래 시각은 최대 2초 허용. Pi도 expires_at을 확인해야 합니다.
- 연령 결과도 최초 감지 후 5초 안에 도착해야 합니다.
- enter가 먼저 전달되어야 age를 처리합니다. 같은 카메라/event_id의 두 결과는 같은 32비트 event_seq를 사용합니다.
- age_group은 문자열 `10`, `20`, `30`, `40`, `keep`만 허용합니다.
- 연령 판별 실패 또는 지원하지 않는 연령은 우선 `keep`으로 전달합니다.
  10세 미만/50세 이상을 다른 음악 그룹으로 묶는 정책은 아직 확정하지 않았습니다.
- P4의 슬립 연령 대기는 현재 2초입니다. 가능하면 그 안에 age/keep을 전달합니다.
  서버의 5초 유효시간이 P4 대기를 늘리지는 않습니다.
- 같은 camera/event_id/type와 같은 내용은 재전송하지 않고 기존 결과를 반환합니다.
  같은 ID로 내용/시각을 바꾸면 409. 재시도할 때 최초 요청 내용 그대로 사용합니다.

## Pi WebSocket 규격

접속 직후 welcome: `{"version":1,"type":"welcome","gateway_id":"gateway-01"}`.
서버→Pi:

```json
{"version":1,"message_id":"4cfe09b1-df1f-4414-bfef-990d53c309ea","type":"cctv.enter","camera_id":"cctv01","railing_id":1,"event_seq":123,"observed_at":"2026-10-07T08:00:00Z","expires_at":"2026-10-07T08:00:05Z"}
```

age 메시지는 type=`cctv.age`와 age_group을 추가합니다.
Pi→서버:

```json
{"version":1,"type":"ack","message_id":"4cfe09b1-df1f-4414-bfef-990d53c309ea","status":"PLC_SENT"}
```

| 상태 | 의미 |
|---|---|
| SENT | 서버가 WebSocket 송신을 마침; Pi 수신 확인 전 |
| RECEIVED | 인증된 Pi가 수신했다고 응답 |
| PLC_SENT | Pi가 PLC 전송을 마쳤다고 응답; P4 적용 확인은 아님 |
| BUSY | 통화/비상 등으로 Pi가 거절 |
| FAILED | Pi 처리/전송 실패 |
| EXPIRED | Pi에서 유효시간 초과로 폐기 |
| UNKNOWN | 연결/송신 실패, 응답 시간 초과 또는 서버 재시작으로 결과 불명 |

CCTV 이벤트 결과는 device_application_confirmed=false를 반환합니다. 일반 제어의 APPLIED 구분은 DEVICE_PROTOCOL.md를 참고하세요.
서버는 실패/불명 결과를 자동 재전송하지 않으며 재연결 때 오래된 감지를 재생하지 않습니다.
CCTV 수신은 P4 적용 응답이 없으므로 전달 성공만으로 음악/슬립 적용을 단정하지 않습니다.
Pi 클라이언트는 수신/PLC 작업을 분리하고, 통화 중에는 BUSY를 응답하며,
동일 message_id 처리 중복과 만료 메시지를 차단해야 합니다.
서버는 20초마다 ping을 보내며 60초 동안 pong이 없으면 연결을 정리합니다.
한 gateway는 한 연결만 유지하며 새 인증 연결이 기존 연결을 대체합니다.

## 운영 연결

이 서버의 8080은 내부/loopback에 두고 Nginx 등에서 유효한 TLS 인증서로
HTTPS/WSS 443을 제공합니다. WebSocket Upgrade 전달과 proxy_read_timeout을 설정합니다.
인터넷에서 HTTP/WS로 Bearer 토큰을 보내거나 Pi에서 인증서 검증을 끄지 않습니다.
Pi는 서버로 접속하므로 Pi 수신 포트 개방은 필요 없습니다.

초기 제한: 네이티브 API 본문/WebSocket 메시지 4KiB, 인증 역할/장치당 HTTP 600회/분,
연결당 ack 30회/초, WebSocket 송신 버퍼 32KiB, 장치당 연결 1개.
DB는 단일 서버 로컬 H2이며 전달 기록 10만 건에서 신규 입력을 중단합니다.
장기 운영 전 기록 보존/정리 및 운영 DB 정책을 추가해야 합니다. DB를 삭제하면 번호가 재사용되므로
연결된 P4의 이벤트 기록도 초기화하지 않은 상태에서 DB를 삭제하지 않습니다.
초기 장치 토큰은 DB에 해시로 등록됩니다. 환경변수 변경만으로 기존 장치 토큰을 덮어쓰지 않습니다.
운영 배포 전 계정 비밀번호 재설정·장치 토큰 교체 절차와 로그인 시도 제한을 추가해야 합니다.

## 검증 범위와 다음 작업

`mvn verify`에는 실제 HTTP/WebSocket 연결을 사용하는 인증·권한·메시지 전달·번호 매칭·중복·ack 테스트가 포함됩니다.
GitHub Actions에서도 monitoring-server 변경 시 별도 빌드합니다.
다음 단계는 난간 Pi의 WSS 어댑터와 실제 분석 프로그램 송신 어댑터입니다.
일반 제어/통화/화면의 서버 처리는 구현되어 있고, 실물 장치 적용 확인은 Pi 연동 후 검증합니다.
펌웨어/PLC 하드웨어 테스트는 이 서버 테스트와 별도로 필요합니다.

이번 검증: Java HTTP/WebSocket 통합 테스트 9개, 실제 libcodec2 변환 테스트 3개,
실제 서버와 시뮬레이터를 연결한 DOM/API 테스트(로그인, 상태 수신, 옵션 적용, 처리 이력, 통화 시작/종료, 관리 화면).
실행 환경의 브라우저 제약으로 픽셀 렌더링·마이크·실제 CCTV 영상은 검증하지 않았습니다.
