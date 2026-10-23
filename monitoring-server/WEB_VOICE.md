# 모니터링 웹 음성통화 테스트

Pi와 서버를 함께 업데이트합니다. 이 변경에는 P4/WROOM/S3 펌웨어 변경이 없습니다.
브라우저의 마이크/스피커를 사용하므로 Pi USB 마이크와 AUX 스피커는 필요하지 않습니다.
통화는 PLC 한 회선(게이트웨이)당 하나이며, 실제 음질과 전환 지연은 장비로 확인해야 합니다.

## 1. 서버의 Codec2 변환 서비스

브라우저 PCM(8kHz, mono, int16 LE)을 Codec2 2400으로 변환하는 별도 프로세스가 필요합니다.
Spring Boot와 **동일한 컴퓨터**에서 `tools/codec_adapter.py`를 실행합니다.
Python 3와 Codec2 공유 라이브러리가 필요합니다. Linux에서는 `libcodec2-dev`를 설치합니다.
Windows에서는 Python과 동일한 아키텍처의 Codec2 DLL 및 DLL의 종속 라이브러리를 준비하고
`CODEC2_LIBRARY`를 DLL의 절대 경로로 설정합니다. Python 패키지 설치만으로 DLL이 설치되지는 않습니다.

Windows PowerShell 예시(실제 DLL 경로로 변경):

```powershell
cd monitoring-server
$env:CODEC2_LIBRARY = "C:\codec2\bin\libcodec2.dll"
$env:CODEC_TOKEN = Read-Host "Codec 전용 토큰 (32자 이상)"
python tools/codec_adapter.py
```

Spring Boot를 실행하는 **다른 PowerShell**에도 동일한 `CODEC_TOKEN`을 입력하고 재시작합니다.
기존 관리자/게이트웨이 토큰 및 DB 설정은 유지합니다. Codec 토큰과 Gateway 토큰은 별개입니다.

```powershell
$env:CODEC_TOKEN = Read-Host "위 Codec 서비스와 동일한 토큰"
mvn spring-boot:run
```

Codec 서비스는 `127.0.0.1:9200`에서만 수신합니다. 공유기 포트 개방이나 Nginx 경로 추가가 필요 없습니다.
`voice_available`은 토큰 설정 여부이며 Codec 프로세스/DLL 정상 동작을 보장하지 않습니다.
Docker/WSL을 별도 네트워크로 실행한다면 localhost가 같다고 가정하지 말고 서버와 Codec 프로세스를 같은 환경에서 실행합니다.

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
권한 거부 또는 Codec 서비스 오류가 발생하면 종료 버튼으로 정리한 뒤 다시 시작합니다.
브라우저 음성 연결이 사라진 통화는 15초 유예 후 상태 불명으로 전환하고 Pi 통화 갱신을 중단합니다.
장비 종료를 추정하여 성공 표시하지 않으며, 재연결 후 **명시적으로 통화 종료**하여 확인해야 합니다.

명령 ID, 웹 통화 ID, PLC 세션, PTT 전환 epoch를 연결합니다. 중복 명령을 다시 PLC로 보내지 않고,
이전 PTT 음성·다른 난간 음성·오래된 큐를 버립니다. 네트워크 지연이나 PLC 손실이 없어지는 것은 아닙니다.
