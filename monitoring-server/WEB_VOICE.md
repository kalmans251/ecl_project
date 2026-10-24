# 모니터링 웹 음성통화 테스트

Pi와 서버를 함께 업데이트합니다. 이 변경에는 P4/WROOM/S3 펌웨어 변경이 없습니다.
브라우저의 마이크/스피커를 사용하므로 Pi USB 마이크와 AUX 스피커는 필요하지 않습니다.
통화는 PLC 한 회선(게이트웨이)당 하나이며, 실제 음질과 전환 지연은 장비로 확인해야 합니다.

## 1. Spring Boot 실행 (Codec2 내장)

별도 Python 변환 서비스, `CODEC_TOKEN`, `CODEC_URL`, 9200 포트는 더 이상 사용하지 않습니다.
Java JNA가 동일 JVM에서 Codec2를 직접 호출합니다. JAR에 포함된 네이티브 라이브러리는 임시 폴더에 풀어 로드합니다.
통화/방향/PTT epoch별 상태를 분리하고 종료·소켓 해제·60초 유휴 시 native 메모리를 정리합니다.

### Windows 운영: DLL이 포함된 JAR 사용

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

### 소스에서 개발·빌드하는 경우

Linux는 Git/GCC/CMake/Ninja, Windows는 Git/CMake/Ninja 및 **MinGW-w64 x64 GCC**가 PATH에 필요합니다.
Windows에서 Visual Studio C 컴파일러 대신 MinGW-w64를 사용합니다.

```powershell
mvn -Pnative-codec verify
mvn spring-boot:run
```

`native-codec` 프로파일은 펌웨어와 같은 고정 커밋의 Codec2를 빌드해 JAR에 포함합니다.
`mvn clean` 후에는 다시 `-Pnative-codec`로 빌드합니다. 일반 `mvn spring-boot:run`만으로
DLL을 새로 내려받거나 C 코드를 컴파일하지 않습니다. CI 배포 JAR은 이 준비를 완료한 결과물입니다.
Dockerfile도 같은 프로파일로 라이브러리를 내장하므로 별도 변환 컨테이너가 필요 없습니다.

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
기록을 지우기 전에 통화 종료 확인을 받으세요. 현장 상태를 확인하지 않고
서버 예약만 해제하거나 다른 통화 세션으로 종료를 보내지 않습니다.
