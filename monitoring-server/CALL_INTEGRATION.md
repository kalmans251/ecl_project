# 실제 Pi 통화 제어 연결

## 이번 연결 범위

`call.start`, `call.end`, `ptt.on`, `ptt.off`를 실제 Pi의 AudioManager에 연결한다.
Pi는 기존 PLC 제어 창·통화 세션·PTT 순서·준비/종료 확인을 그대로 사용한다.
서버 UUID와 PLC 32비트 session_id를 연결하며 장치 확인 이후에만 APPLIED를 보낸다.
서버는 PTT 처리 중 SWITCHING으로 바꾸어 중복 조작과 음성 송신을 막는다.

Pi의 optional `monitoring.py`는 통화 제어 전용이다. 일반 명령·emergency.ack·CCTV
분석 이벤트 및 WebSocket Codec2 음성 중계는 아직 지원하지 않는다. 지원하지 않는
명령은 FAILED이며, 음성 메시지는 전달하지 않는다. 기존 로컬 USB 마이크/AUX
테스트는 유지된다. 브라우저에서 소리가 나온다는 의미가 아니다.

## 실행

서버에 gateway와 난간 번호를 먼저 등록하고, gateway 전용 토큰을 Pi에 설정한다.
관리자 토큰이나 분석용 토큰을 재사용하지 않는다. 명령줄 인자에 토큰을 넣지 않는다.

```bash
pip install -r requirements-monitoring.txt
export ECL_MONITOR_URL='wss://YOUR_SERVER/ws/gateways/gateway-01'
read -rsp 'Gateway token: ' ECL_MONITOR_TOKEN; echo
export ECL_MONITOR_TOKEN
python main.py --no-console --event-railings 1,2,3,4 --disable-voice-relay
```

Pi 로컬 음성으로 테스트하려면 위 실행에 `--local-audio --audio-railing 1
--mic-device <입력 장치> --speaker-device <출력 장치>`를 추가한다.
`--disable-voice-relay`는 외부 TCP listener만 끄며 LocalAudio 기능은 유지한다.
실제 장치 번호는 `python main.py --list-audio-devices`에서 확인한다.
원격 URL은 WSS만 허용하고 인증서 검증을 끄는 옵션은 제공하지 않는다.
개발용 WS는 loopback에만 허용한다. `--monitor-url`로 URL을 직접 지정할 수도 있다.

`--call-state-file`과 `--monitor-state-file`을 재시작 시 그대로 유지해야 한다.
후자는 명령 중복 방지와 서버 UUID 연결/확인된 END를 보관한다. 두 파일을 임의로
삭제하면 복구 증거가 사라지므로 자동으로 종료 성공을 만들어내지 않는다.
모니터 연결 시에는 `--no-console`을 요구해 CLI와 서버가 같은 호출을 동시에
조작하지 않게 한다. 장치 비상 이벤트에 대한 기존 PLC 폴링은 계속 동작한다.

## call_state 메시지

기존 gateway 소켓에서 약 1초마다 송신한다. 최대 4096바이트/초당 30개 정책을 따른다.

```json
{"version":1,"type":"call_state","call_id":"server UUID","railing_id":1,"session_id":123,"sequence":5,"phase":"unknown","direction":"","error":"S3_TIMEOUT"}
```

- phase: starting, active, switching, ending, unknown, ended.
- direction: FIELD_TX, CONTROL_TX 또는 미확인일 때 빈 문자열.
- error: 빈 문자열, GATEWAY_OFFLINE, WROOM_TIMEOUT, S3_TIMEOUT, WROOM_FAILED, S3_FAILED.
- sequence: 양의 정수. 같은 연결 안에서 이전 번호는 무시한다. 교체된 소켓의 메시지는 받지 않는다.
- gateway·등록 난간·서버 call_id·PLC session_id가 모두 일치해야 기존 통화에 반영한다.
- 서버는 정상 스냅샷만으로 UNKNOWN을 ACTIVE로 되돌리지 않는다. 재접속 후 불확실하면
  종료 재시도로 정리한다. 다른 session의 지연된 END로 현재 통화를 해제하지 않는다.
- Pi가 실제 END를 확인하고 전달한 경우에만 점유 해제한다. 최초 보고가 END인 경우는
  명시적인 종료 요청 복구에만 허용한다. 단순 idle/파일 부재는 END 증거가 아니다.
- 연결 해제 시 Pi는 통화를 unknown으로 바꾸어 음성/keepalive를 멈춘다. P4는 기존
  lease 종료 절차를 따른다. 연결 복구 후 기존 명령/음성을 자동 실행하지 않는다.
- 서버가 15초 안에 ACK를 받지 못한 뒤 도착한 ACK는 기존 요청 결과를 덮어쓰지 않는다.
  늦은 실제 종료는 별도 call_state로 정리할 수 있다.

## 남은 작업

| 영역 | 현재 상태 | 남은 작업 |
|---|---|---|
| Pi/P4/WROOM/S3 통화 제어 | 확인·세션·순서·연결 감시 구현, 소프트웨어 검사 | 실제 PLC/BLE 부하·음질·고장 복구 검증 |
| 서버 ↔ Pi 통화 제어/화면 | 이번 PR에서 실제 어댑터 연결 | 실제 배포 환경에서 로그인·재접속·PTT 확인 |
| 관제 브라우저 음성 | 서버 PCM/Codec2 변환 코드 존재 | gateway Codec2 중계 및 세션 매핑·음성 큐·통합 검증 |
| 일반 장치 제어/상태 | 서버 규격, Pi CLI 및 확인 로직 존재 | gateway 명령 매핑·실제 상태 스냅샷 전달·ACK 규격 정합성 |
| CCTV | 서버 이벤트/등록 구조 존재 | 분석기 → 서버 → Pi의 실제 연동, 난간/카메라 매핑 검증 |
| 운영 복구 | 일부 세션·소유권·재접속 처리 구현 | 브라우저 종료/운영자 이탈 정책, 다중 사용자·다중 난간 통합 검증 |
| 배포 | 설정·컨테이너 예제 존재 | 자동 기동·로그 보관·백업·TLS·장치별 설정 점검 |

표는 저장소에서 확인한 기능 경계다. 실장비 검증을 보류한 상태이므로 전체 완료율을
숫자로 산정하거나 현장 운영 준비 완료로 판단하지 않는다.
