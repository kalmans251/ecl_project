# CCTV 이벤트 수신 검증

난간 Pi의 main.py를 종료하고 이 변경을 적용한 뒤 기존 게이트웨이 옵션으로 다시 실행합니다. 서버 DB나 토큰 초기화, ESP32 펌웨어 재설치는 필요하지 않습니다.

카메라를 활성화하고 난간 감지 모드를 CCTV로 전환합니다. analytics-server를 실행한 뒤 화면 밖에서 사람이 다시 들어옵니다.

Pi 로그에서 `CCTV event rail=1 type=cctv.enter seq=...`와 `CCTV event result ... status=PLC_SENT`를 확인합니다. 연령 추정이 꺼져도 기존 분석기는 age=keep 이벤트를 보낼 수 있습니다.

PLC_SENT는 기존 서버 프로토콜의 응답 이름입니다. 이 수신기는 DeviceControls의 P4 확인을 기다린 뒤 해당 응답을 보냅니다. 물리적인 LED/음악 동작은 별도로 확인해야 합니다. 실패나 시간 초과는 FAILED이며 자동 재전송하지 않습니다. 실행 직전 저장한 저널로 같은 메시지 ID의 재실행을 막습니다. UNKNOWN 또는 FAILED를 없애려고 저널을 삭제하지 마세요.

통화 중에는 기존 DeviceControls 제한을 유지하고, 다른 원격 명령 처리 중이면 BUSY를 반환합니다. 만료·다른 난간·잘못된 순번/연령 데이터는 PLC로 전송하지 않습니다.

자동 검증 (raspberry-pi 폴더):

```sh
PYTHONPATH=.:tests python -m unittest test_cctv_remote test_music_remote test_control_remote test_music_sync test_call_remote test_device_control
```
