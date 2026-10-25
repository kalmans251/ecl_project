# Windows 서버 CCTV 설정 적용 가이드

**[DB 초기화부터 서버·난간 Pi·CCTV까지 순서대로 연결하기](../FRESH_START.md)** —
완전 초기화와 평소 재시작을 구분한 통합 설명서입니다.

이 문서는 Spring Boot, Nginx, MediaMTX가 **동일한 Windows PC**에서 실행되는
omtest.duckdns.org 환경 기준이다. 먼저 CCTV 기능(PR #81)이 포함된 main을 업데이트한다.
설정 파일을 GitHub에 올리는 것만으로 실행 중인 PC 설정이 바뀌지는 않는다.

## 1. 사용할 파일과 설치 위치

| 저장소 파일 | 복사할 실제 위치 | 설명 |
|---|---|---|
| nginx.conf | C:\nginx\conf\nginx.conf | 전체 설정. 조각 파일과 동시에 붙여 넣지 않는다 |
| mediamtx.example.yml | MediaMTX 설치 폴더의 mediamtx.yml | 전체 설정. 암호화 키를 반드시 교체 |
| nginx-locations.conf | 기존 사용자 설정에 수동 병합할 때만 사용 | 전체 nginx.conf를 적용하면 불필요 |

MediaMTX는 **v1.21.2 Windows amd64**를 기준으로 검증했다.
[공식 배포본](https://github.com/bluenviron/mediamtx/releases/tag/v1.21.2)을 사용한다.
아래 명령은 저장소 루트에서 시작한다. 경로 두 개는 자신의 설치 위치로 바꾼다.

```powershell
git pull
$repoRoot = (Get-Location).Path
$nginxDir = "C:\nginx"
$mediaDir = "C:\mediamtx"
$stamp = Get-Date -Format yyyyMMdd-HHmmss

Copy-Item "$nginxDir\conf\nginx.conf" "$nginxDir\conf\nginx.conf.$stamp.bak"
if (Test-Path "$mediaDir\mediamtx.yml") {
    Copy-Item "$mediaDir\mediamtx.yml" "$mediaDir\mediamtx.yml.$stamp.bak"
}

Copy-Item "$repoRoot\deployment\cctv\nginx.conf" "$nginxDir\conf\nginx.conf"
Copy-Item "$repoRoot\deployment\cctv\mediamtx.example.yml" "$mediaDir\mediamtx.yml"

notepad "$nginxDir\conf\nginx.conf"
notepad "$mediaDir\mediamtx.yml"
```

실제 인증서와 개인 키는 기존 C:\nginx\conf\ssl 파일을 유지한다.
다른 도메인이면 Nginx server_name/리다이렉트/인증서 경로와 MediaMTX
webrtcAllowOrigins/webrtcAdditionalHosts, Pi control_url/server_host를 함께 수정한다.
개인 키·토큰·실제 운영 mediamtx.yml은 저장소에 커밋하지 않는다.
예제의 REPLACE_WITH_... 문자열은 유효한 운영 비밀이 아니다.

## 2. 인증 정보는 네 종류다

| 값 | 생성 위치 | 입력 위치 |
|---|---|---|
| control_token | 관리자 CCTV 테스트 화면 | CCTV Pi config.json |
| publish_token | 관리자 CCTV 테스트 화면 | CCTV Pi config.json |
| analysis_token | 관리자 CCTV 테스트 화면 | 서버 analytics-server/config.json |
| SRT passphrase | 아래 PowerShell 명령 | MediaMTX srtPublishPassphrase + CCTV Pi srt_passphrase |

기존 난간 MONITOR_GATEWAY_TOKEN을 CCTV Pi에 복사하지 않는다.
카메라 토큰 3개는 로그인 후 /cctv-test.html에서 카메라 ID를 선택하고
**인증 정보 생성 → 등록/교체 → 설정용 토큰 복사**로 만든다.
등록된 카메라만 가능하며, 새 카메라는 먼저 관리 화면에서 현장·게이트웨이·난간에 연결한다.
등록/교체 후에는 비활성 상태이므로 설정을 마친 다음 CCTV 사용 허용을 켠다.
서버는 토큰 해시만 보관하므로 생성한 값은 안전한 로컬 설정에 보관한다.
잊었다면 새로 등록/교체하고 Pi/분석 프로그램의 관련 토큰도 갱신한다.

SRT 암호화 키는 PC에서 한 번 생성한다:

```powershell
$b = New-Object byte[] 32
$r = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$r.GetBytes($b)
$r.Dispose()
[Convert]::ToBase64String($b).TrimEnd('=').Replace('+','-').Replace('/','_')
```

출력값을 MediaMTX의 cctv01_raw.srtPublishPassphrase 따옴표 안에 넣고,
**같은 값**을 CCTV Pi의 srt_passphrase에 넣는다. 토큰 3개는 각각 다른 값이다.
매번 실행할 때 새 키를 만들 필요는 없다. 교체한다면 양쪽을 함께 바꾼다.
Windows 파일 ACL은 실행 계정/관리자만 읽도록 제한하고, Pi 설정은 chmod 600을 적용한다.

## 3. 서버 프로그램 실행

Spring Boot는 기존 토큰과 DB를 유지해서 실행한다. 기존 MONITOR_* 환경변수가
설정된 PowerShell 창에서 다음을 사용한다. 새 창에는 환경변수가 없을 수 있다.
토큰을 무조건 재생성하거나 DB를 삭제하지 않는다.

```powershell
$env:SERVER_ADDRESS = "127.0.0.1"
$env:SERVER_FORWARD_HEADERS_STRATEGY = "framework"
$env:COOKIE_SECURE = "true"
cd monitoring-server
mvn verify
if ($LASTEXITCODE -eq 0) {
    mvn spring-boot:run
}
```

별도 PowerShell 창에서 기존 MediaMTX를 종료한 뒤 실행한다.
아래 C:\mediamtx는 실제 설치 경로로 바꾼다.

```powershell
cd C:\mediamtx
.\mediamtx.exe --version
.\mediamtx.exe .\mediamtx.yml
```

이 창은 계속 실행 상태로 둔다. 서비스로 실행 중이었다면 그 서비스를 중지/재시작하고
두 프로세스를 동시에 띄우지 않는다. unknown field 오류면 버전부터 확인한다.
port already in use 오류면 기존 MediaMTX 중복 실행 여부를 확인한다.

다른 PowerShell 창에서 Nginx를 검사하고 성공했을 때만 다시 읽힌다:

```powershell
cd C:\nginx
.\nginx.exe -t
if ($LASTEXITCODE -eq 0) {
    .\nginx.exe -s reload
}
```

reload는 Nginx가 이미 실행 중일 때 사용하는 명령이다.
실행 중인 Nginx가 없다면 검사 성공 후 .\nginx.exe로 시작한다.
기존 /ws/ 통화·난간 연결과 /ws-stomp, 인증서 갱신용 HTTP 경로는 포함되어 있다.
인증서 갱신은 기존 win-acme 작업이 수행하며 이 설정 자체가 갱신 작업을 만들지는 않는다.

## 4. 방화벽과 공유기

| 포트 | 용도 | 외부 접근 |
|---|---|---|
| TCP 80 | 기존 win-acme HTTP 검증, HTTPS 리다이렉트 | 기존 설정 유지 |
| TCP 443 | 웹, WSS, WebRTC 연결 요청 | 허용 |
| UDP 8890 | CCTV Pi → MediaMTX SRT 영상 | 허용; 가능하면 현장 IP/VPN 제한 |
| UDP 8189 | 브라우저 ↔ MediaMTX WebRTC 영상 | 허용 |
| TCP 8080/8554/8889/9997 | 서버 내부 API/분석/영상/관리 | localhost 전용, 외부 개방 금지 |

Nginx는 UDP 8890/8189 영상을 대신 전달하지 않는다.
공유기 포트포워딩은 서버 PC의 고정 LAN 주소로, Windows 방화벽도 동일 포트를 허용한다.
UDP는 Test-NetConnection의 TCP 포트 검사만으로 정상 여부를 판단할 수 없다.
같은 LAN에서 공인 도메인 접속이 실패하면 공유기 NAT loopback 지원도 확인한다.

9997은 localhost에서 인증을 제외한 관리 API이므로 이 PC 자체를 신뢰할 수 있어야 한다.
Nginx location을 추가해 외부로 노출하지 않는다.

## 5. CCTV Pi와 분석 프로그램 연결

CCTV Pi에서 기존 수동 FFmpeg/자동 송출 서비스를 중지한다.
새 cctv-pi/config.json의 camera_id=cctv01,
control_url=wss://omtest.duckdns.org/ws/cameras/cctv01,
server_host=omtest.duckdns.org와 RTSP 카메라 주소 및 위 인증 정보를 입력한다.
카메라 암호는 RTSP URL에 맞게 인코딩하며 카메라는 H.264로 설정한다.

```bash
cd ~/ecl_project/cctv-pi
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# 최초 설정 때만 복사한다. 기존 설정을 덮어쓰지 않는다.
cp -n config.example.json config.json
chmod 600 config.json
nano config.json
.venv/bin/python agent.py --config config.json
```

카메라 토큰은 난간 Pi가 아니라 **CCTV Pi**에 입력한다.
서버 분석 프로그램은 별도이며 [전체 연결 설명서](README.md)의 4절에 따라
analysis_token을 넣어 실행한다. 분석 프로그램이 없어도 권한 있는 영상 시청은 가능하다.
사람 검출로 난간을 깨우려면 난간의 detection=cctv 확인과 분석 프로그램 실행이 모두 필요하다.

## 6. 성공 확인과 증상별 점검

먼저 서버 PC에서:

```powershell
curl.exe -i http://127.0.0.1:9997/v3/webrtcsessions/list
curl.exe -i https://omtest.duckdns.org/api/cctv/media-auth
```

첫 요청은 HTTP 200(세션이 없어도 정상), 두 번째는 **404가 정상**이다.
인증서 검증을 끄는 -k 옵션을 쓰지 않는다.
테스트 화면 https://omtest.duckdns.org/cctv-test.html에서:

1. 카메라 등록/토큰 입력 후 CCTV 사용 허용.
2. 상태에서 device.connected=true, camera.media_control_ready=true 확인.
3. 영상 보기 → 움직이는 실제 영상 확인. 레이더 모드에서는 분석이 꺼져 있어도 정상.
4. 보기 종료 → 레이더 모드라면 유예 후 Pi 송출 종료 확인.
5. 난간을 CCTV 모드로 전환하고 장치 확인 성공 → 분석 프로그램 실행.
6. camera.analysis=true, analysis_fresh=true, analysis_state.available=true 및
   실제 사람 진입 시 해당 난간의 동작 확인.

| 증상 | 먼저 확인할 것 |
|---|---|
| /cctv-test.html이 404 | Spring Boot 코드 업데이트·재시작 여부 |
| device.connected=false | Pi control_url/control_token, Nginx /ws/cameras/, TLS 인증서 |
| media_control_ready=false | MediaMTX 실행, api=true, 127.0.0.1:9997 접근 |
| 영상 인증 거절 | 카메라 사용 허용, 사용자 현장 권한, publish_token과 등록값 일치 |
| SRT 연결 실패 | 양쪽 passphrase 일치, UDP 8890, 기존 송출 프로세스 중복 |
| Pi streaming인데 웹 영상 없음 | UDP 8189/NAT, 도메인, H.264, 브라우저 오류 |
| 영상은 보이는데 난간이 반응 없음 | 확인된 CCTV 모드, 분석 실행·토큰, 카메라/난간 매핑, PLC 상태 |
| 예전 /cctv/ 주소가 404 | 의도된 변경. /cctv-test.html로 접근 |

미디어 인증은 Spring Boot 실행이 필요하다. 운영 전에 기존 음악·통화·난간 명령도 다시 확인한다.

## 7. 여러 난간·사용자·카메라 추가

카메라 ID는 서버 전체에서 고유하게 사용한다(예: site_a_cam01, site_b_cam01).
난간 번호는 게이트웨이가 다르면 둘 다 1이어도 된다.
각 카메라마다 다음 작업을 모두 수행한다:

1. 관리 화면에서 현장 → 게이트웨이 → 난간 → 카메라 연결과 사용자 현장 권한 등록.
2. 카메라 전용 control/publish/analysis 토큰 3개 생성.
3. MediaMTX paths에 <camera_id>_raw 경로와 별도 SRT passphrase 추가.
4. 해당 CCTV Pi의 camera_id, control_url 끝 ID, 인증 정보 설정.
5. 카메라별 분석 설정/프로세스 실행.

예를 들어 paths 아래에 다음을 추가한다(기존 cctv01_raw 항목 옆, 같은 들여쓰기):

```yaml
  site_b_cam01_raw:
    source: publisher
    overridePublisher: false
    srtPublishPassphrase: "REPLACE_WITH_ANOTHER_RANDOM_SRT_PASSPHRASE"
```

다른 사용자가 같은 현장 권한을 받으면 그 현장 카메라를 볼 수 있다.
완전 별도 사용자 시스템이라면 현장과 사용자 소속도 분리해야 한다.
영상/토큰/이벤트는 카메라별로 구분하지만 서버 GPU와 네트워크 자원은 공유한다.
동시 카메라 수와 추론 속도는 실제 장비에서 검증한다.

## 8. 되돌리기

작업 전에 만든 .bak 파일 중 정확한 파일을 골라 운영 파일에 복사하고,
Nginx는 -t 성공 후 reload, MediaMTX는 기존 프로세스 종료 후 다시 실행한다.
예전 설정으로 돌아가면 익명 영상 공개가 재활성화될 수 있으므로 외부 노출을 재검토한다.
Git의 예제에 실제 키를 넣지 않으면 git pull로 운영 비밀이 덮어써지지 않는다.
