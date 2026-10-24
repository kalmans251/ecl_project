# 모니터링 웹 음성통화 테스트

Pi와 서버를 함께 업데이트합니다. 이 변경에는 P4/WROOM/S3 펌웨어 변경이 없습니다.
브라우저의 마이크/스피커를 사용하므로 Pi USB 마이크와 AUX 스피커는 필요하지 않습니다.
통화는 PLC 한 회선(게이트웨이)당 하나이며, 실제 음질과 전환 지연은 장비로 확인해야 합니다.

## 1. Spring Boot 실행 (Codec2 내장)

별도 Python 변환 서비스, `CODEC_TOKEN`, `CODEC_URL`, 9200 포트는 더 이상 사용하지 않습니다.
Java JNA가 동일 JVM에서 Codec2를 직접 호출합니다. JAR에 포함된 네이티브 라이브러리는 임시 폴더에 풀어 로드합니다.
통화/방향/PTT epoch별 상태를 분리하고 종료·소켓 해제·60초 유휴 시 native 메모리를 정리합니다.

### Windows: Git 업데이트 후 기존 Maven 명령으로 실행 (권장)

Java 17 x64, Maven 3.9+, Git이 설치되어 있으면 됩니다. 기존 서버를 종료하고,
토큰이 설정된 동일한 PowerShell 창의 `monitoring-server` 폴더에서 실행하세요.

```powershell
git pull
mvn spring-boot:run
```

Windows용 Maven 프로파일이 자동 활성화되어 최초 실행 시 약 40 MB의
w64devkit 2.5.0을 공식 GitHub에서 내려받고 고정 SHA-256을 검증한 뒤 압축을 풉니다.
관리자 권한, CMake/Ninja/MSYS2 수동 설치, Actions 아티팩트 수동 다운로드는 필요 없습니다.
컴파일러는 `%LOCALAPPDATA%/ecl-monitoring-tools`에 보관합니다. 컴파일 중에만 해당 도구 경로를 임시 PATH에 추가하여 `as.exe`/`ld.exe`를 찾고, 성공·실패 모두 기존 PATH로 복원합니다. 시스템 PATH는 변경하지 않습니다.
펌웨어와 같은 Codec2 커밋을 받아 2400 모드 DLL을 빌드하고 Maven 리소스에 포함합니다.
두 번째 실행부터 DLL 해시·빌드 스크립트가 일치하면 캐시를 사용합니다.
`mvn clean` 이후에도 같은 명령으로 자동 재생성합니다. 다운로드/빌드 실패 시 서버 실행을 중단합니다.

`mvn verify`로 테스트·JAR 생성도 가능합니다. 기존 DB와 토큰은 그대로 사용합니다.
과거 `CODEC2_LIBRARY`를 별도로 지정했다면 해당 값이 내장 DLL보다 우선하므로,
내장 DLL을 쓰려면 현재 PowerShell에서 `Remove-Item Env:CODEC2_LIBRARY -ErrorAction SilentlyContinue`로 해제하세요.

### Windows 운영: DLL이 포함된 JAR 사용 (선택)

GitHub Actions → **Monitoring server** → 병합된 최신 커밋의 성공한 실행 →
**monitoring-server-Windows-x64** 아티팩트를 다운로드하고 압축을 풉니다.
64비트 Java 17 이상이 필요합니다. Python, CMake, GCC는 운영 PC에 필요하지 않습니다.
기존 서버를 종료한 뒤, **기존 monitoring-server 디렉터리에서** 다음을 실행합니다.
DB 상대 경로를 유지하려면 기존 서버와 같은 작업 디렉터리를 사용해야 합니다.

```powershell
# JAR은 다운로드한 실제 경로를 사용하세요.
java -jar .\monitoring-server-0.1.0.jar --codec-self-test
java -jar .\monitoring-server-0.1.0.jar
```

기존 `MONITOR_GATEWAY_TOKEN` 등 서버 환경변수는 그대로 설정합니다. 별도 Codec 토큰은 없습니다.
시작 로그의 `Codec2 2400 ready in Spring Boot`를 확인합니다.
다른 버전 DLL을 수동 사용하려면 `CODEC2_LIBRARY`에 절대 경로를 지정할 수 있습니다.
내장 DLL을 사용할 때는 과거 `CODEC2_LIBRARY` 설정을 제거합니다.
Linux x64에서는 **monitoring-server-Linux-x64** 아티팩트를 사용합니다.
운영체제가 다른 아티팩트를 혼용하지 않습니다.

### Linux 또는 수동 CMake 빌드

Linux는 Git/GCC/CMake/Ninja를 설치하고 아래 명령을 사용합니다.
Windows에서도 이 프로파일을 명시하면 자동 준비 대신 기존 MinGW-w64 x64/CMake/Ninja를 사용합니다.

```sh
mvn -Pnative-codec verify
mvn spring-boot:run
```

`native-codec` 프로파일과 Dockerfile은 같은 펌웨어 고정 커밋을 사용합니다.
Windows 자동 빌드 스크립트와 CMake 빌드 모두 라이선스 및 대응 소스를 JAR에 포함합니다.

라이브러리 로드 실패 시 웹 제어 서버는 시작되지만 `voice_available=false`가 됩니다.
음성 성공으로 표시하지 않으며, 자기 진단으로 DLL 아키텍처·로드 오류를 확인할 수 있습니다.

## 2. Pi 실행

기존 `main.py`, `hardware_test.py`, `voice_send.py`를 종료하여 PLC 수신자가 하나만 남도록 합니다.
기존 `.venv`를 활성화하고 서버에 등록된 동일한 Gateway 토큰을 설정합니다.

```bash
cd ~/ecl_prj/ecl_project/raspberry-pi
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-monitoring.txt
read -rsp 'Gateway token: ' MONITOR_GATEWAY_TOKEN; echo
export MONITOR_GATEWAY_TOKEN
python main.py --port /dev/serial0 --baud 9600 --event-railings 1 \
  --monitor-url wss://omtest.duckdns.org/ws/gateways/gateway-01 --web-voice
```

설치된 난간만 `--event-railings`에 지정합니다. `--local-audio`와 `--web-voice`는 동시 사용하지 않습니다.
웹 음성 모드에서는 기존 TCP 음성 포트를 열지 않으며 콘솔 통화 명령도 막습니다.
기존 통화/명령 journal 파일은 삭제하지 않습니다. 자동으로 이전 통화를 재개하지 않습니다.

## 3. 브라우저 테스트

1. `https://omtest.duckdns.org/function-test.html`에 로그인하고 온라인 난간 하나를 선택합니다.
2. 통화 시작 → 실제 P4 시작 확인 후 `ACTIVE / FIELD_TX`를 확인하고 난간 마이크를 듣습니다.
3. 말하기(PTT ON) → 브라우저 마이크 권한 허용 → `CONTROL_TX` 확인 후 말합니다.
4. 듣기(PTT OFF) → `FIELD_TX` 확인 후 난간 음성을 듣습니다.
5. 통화 종료 → 실제 종료 확인 후 통화 항목이 사라지는지 확인합니다.

HTTPS 인증서와 Nginx `/ws/` WebSocket Upgrade 설정이 정상이어야 합니다.
권한 거부 또는 Codec2 로드 오류가 발생하면 종료 버튼으로 정리한 뒤 다시 시작합니다.
브라우저 음성 연결이 사라진 통화는 15초 유예 후 상태 불명으로 전환하고 Pi 통화 갱신을 중단합니다.
장비 종료를 추정하여 성공 표시하지 않으며, 재연결 후 **명시적으로 통화 종료**하여 확인해야 합니다.

명령 ID, 웹 통화 ID, PLC 세션, PTT 전환 epoch를 연결합니다. 중복 명령을 다시 PLC로 보내지 않고,
이전 PTT 음성·다른 난간 음성·오래된 큐를 버립니다. 네트워크 지연이나 PLC 손실이 없어지는 것은 아닙니다.

## 통화 시작 실패 후 복구

Pi와 서버를 함께 업데이트하세요. `--web-voice`를 빠뜨리거나 Pi가 새 웹 통화를
PLC 송신 전에 거절하면 `NOT_STARTED` 확인으로 서버 예약을 해제합니다.
단순 `FAILED`, 타임아웃, 연결 끊김은 실행되지 않았다는 증거가 아니므로
`UNKNOWN` 예약을 유지합니다. 이때 통화 소유자/관리자의 종료 재시도는 허용합니다.
기능 테스트 화면은 실패 후 상태를 다시 조회하며, 종료 요청은 브라우저 오디오
초기화 성공 여부에 의존하지 않습니다.

Pi 로그의 `Web call request`와 `Web call failed`를 확인하세요.
이미 남아 있는 `UNKNOWN` 기록은 자동 삭제하지 않습니다. 특히 Pi 통화 기록을
삭제하면 서버 통화 ID와 PLC 세션 연결이 사라져 웹 종료가 거절될 수 있습니다.
기록을 지우기 전에 통화 종료 확인을 받으세요.

### 이미 Pi 통화 기록을 지워 웹 종료가 거절되는 경우

서버와 Pi를 함께 업데이트하고 Pi는 `--web-voice`로 실행합니다.
모니터링 화면에서 해당 난간을 선택해 **통화 종료**를 누릅니다. DB 삭제는 필요 없습니다.
서버는 종료 요청에 `recover=true`와 알고 있는 PLC 세션을 전달합니다.
Pi는 다른 통화가 버스를 소유하지 않을 때만 누락된 웹 통화 연결을 복구합니다.
서버에도 PLC 세션이 없으면 종료 전용 세션을 생성해 기록하고 P4에 STOP만 전송합니다.
P4는 다른 활성 세션을 거절하며, 유휴 상태에서는 WROOM/S3의 정지 확인 후 END를 보냅니다.
Pi가 일치하는 END를 수신하고 서버가 call ID·난간·명령 ID·세션을 검증해야 잠금이 해제됩니다.

`Web hangup recovery ... waiting for physical END confirmation` 다음에
`CALL end confirmed`가 나오는지 확인합니다. 이후 `query p4` 등 일반 제어가 가능합니다.
다른 통화가 실제로 활성화되어 있거나 P4/WROOM/S3가 응답하지 않으면 UNKNOWN을 유지합니다.
실패 후 종료 재시도는 같은 복구 세션을 사용하며, 시간 경과만으로 종료 성공을 표시하지 않습니다.
이 복구는 현재 펌웨어의 세션별 STOP/장치 readiness를 사용하므로 펌웨어 변경은 없습니다.
