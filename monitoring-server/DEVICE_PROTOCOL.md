# Device WebSocket v1

Pi는 `/ws/gateways/{gateway_id}`에 자신의 Bearer 토큰으로 접속합니다.
WSS 운영, loopback 개발만 WS. 기존 CCTV 이벤트 규격은 README를 참고하세요.
새 서버에는 Pi 프로세스에 결합할 어댑터가 아직 포함되지 않습니다.
아래는 해당 어댑터가 구현해야 하는 규격입니다. `tools/mock_gateway.py`는 시뮬레이터입니다.

## 일반 명령

```json
{"version":1,"type":"command","message_id":"UUID","railing_id":1,"operation":"volume","value":"20","expires_at":"2026-10-08T00:00:15Z"}
```

Pi는 자신의 PLC 버스 작업 큐에 넣고 메시지 UUID 중복과 만료를 먼저 검사해야 합니다.
기존 CLI 문자열을 shell에 실행하지 말고 Python의 기존 제어 매니저 메서드에 매핑합니다.
같은 gateway의 일반 명령은 서버에서도 한 번에 하나씩 전달합니다.
CCTV와 음성은 별도 메시지이므로 Pi의 기존 통화 우선순위·제어 창 정책을 그대로 지켜야 합니다.

| operation | value | Pi CLI에 대응하는 기능 |
|---|---|---|
| power | ac/battery/on/off | power `<id>` `<value>` |
| projector | on/off | projector `<id>` `<value>` |
| led | on/off/basic/music | led `<id>` `<value>` |
| led.basic_pattern | 숫자 문자열 0..5 | led `<id>` basic `<value + 1>` |
| led.music_pattern | 숫자 문자열 0..2 | led `<id>` music `<value + 1>` |
| weather | clear/cloudy/rain/snow | led `<id>` weather `<value>` |
| music.start/stop/pause/resume/next | 없음 | music `<id>` `<action>` |
| music.mode | sequential/shuffle/age | music `<id>` mode `<value>` |
| volume | 숫자 문자열 0..100 | volume `<id>` `<value>` |
| sleep | on/off | sleep `<id>` `<value>` |
| detection | radar/cctv | detection `<id>` `<value>` |
| query | p4/wroom/s3 | query `<id>` `<value>` |
| emergency.ack | 없음 | ack `<id>` |
| call.start/end | 없음 | call/hangup `<id>` |
| ptt.on/off | 없음 | ptt `<id>` on/off |

통화 명령에는 서버가 생성한 `call_id` UUID가 추가됩니다. 음성 프레임은 해당 통화에 귀속됩니다.

```json
{"version":1,"type":"ack","message_id":"동일 UUID","status":"RECEIVED"}
```

- RECEIVED: 작업 큐에 접수. 아직 장치 적용이 아닙니다.
- PLC_SENT: 일반 명령의 PLC 송신 완료. 적용 확인을 의미하지 않습니다.
- APPLIED: volume, music.stop, call.start/end, ptt.on/off의 **실제 장치 응답**을 받은 경우에만 사용합니다.
- BUSY/FAILED/EXPIRED: 실행 불가/실패/만료. ACK는 정확히 네 필드만 보냅니다.
- 확인 가능한 명령은 RECEIVED 다음 실제 APPLIED 또는 실패를 응답해야 합니다. 중간 PLC_SENT로 종료하지 않습니다.
- 서버는 15초 경과 시 실행 전 명령은 EXPIRED, 송신 후 미확인 명령은 UNKNOWN으로 처리합니다.
- 재접속/재시작 뒤 불확실한 명령을 자동 재실행하지 않습니다.
- APPLIED 응답은 서버 화면의 명령 이력을 갱신합니다. 실제 상태 화면은 아래 telemetry로 별도로 갱신합니다.

## 상태

최대 4096바이트. 모든 장치 메시지는 합계 초당 30개 이하입니다.
보통 상태는 난간별 2~10초 주기 또는 상태 변화 시 전달하세요.

```json
{"version":1,"type":"telemetry","railing_id":1,"observed_at":"2026-10-08T00:00:00Z","state":{"power":"ac","power_on":true,"projector":false,"led":"music","led_enabled":true,"sleep":false,"volume":20,"music":"playing","music_mode":"age","detection":"cctv","battery_percent":76,"left_watt":12.5,"right_watt":13.2,"emergency":false,"detection_count":4,"radar":[{"x":0.3,"y":2.1}]}}
```

`state`는 **전체 현재 스냅샷**입니다. 모르는 필드는 생략하며 직전 스냅샷을 덮어씁니다.
레이더 좌표 단위는 m, 최대 3개. 선택 필드: weather(clear/cloudy/rain/snow), wind(m/s), pm10(µg/m³).
통화 제어 상태는 상관관계가 있는 명령 ACK로만 갱신하며 telemetry로 임의 점유를 해제하지 않습니다.
관측 시각이 60초 이상 오래되었거나 2초 이상 미래이면 거절합니다.
브라우저는 15초 동안 새 스냅샷이 없으면 상태 미수신으로 표시합니다.
새 gateway는 그 gateway에 등록된 난간 번호만 보고할 수 있습니다.

## 음성

```json
{"version":1,"type":"voice","call_id":"통화 UUID","railing_id":1,"direction":"FIELD_TX","sequence":27,"codec2":"48바이트 데이터의 base64"}
```

난간→서버는 FIELD_TX, 서버→Pi는 CONTROL_TX입니다.
Codec2 2400: 20ms/160 samples/6 bytes × 8 frames = 160ms/48 bytes.
이 JSON에는 PLC 7바이트 메타데이터가 포함되지 않습니다. Pi에서 기존
`VoicePacket`으로 래핑/해제하여 wire mode/direction enum을 적용합니다.
`sequence`는 0..65535입니다. 재연결/방향 변경 시 오래된 송수신 큐를 폐기하세요.
브라우저 방향은 별도 `/ws/operator/voice/{call_id}`에서 binary PCM 2560바이트를 사용하며,
인증 세션·동일 Origin·통화 소유권·현장 운영 권한·방향을 검사합니다.
Pi는 PCM을 디코딩할 필요 없이 Codec2만 전달하면 됩니다.

## 시뮬레이션 확인

1. Spring 실행 후 로그인.
2. 같은 gateway 토큰으로 `python tools/mock_gateway.py --simulate-device` 실행.
3. 난간 1의 충전량/배터리/레이더가 표시되는지 확인.
4. 음악 탭에서 볼륨 변경 → 전체 적용 → 처리 내역 APPLIED 확인.
5. 통화 시작 → 다른 운영자 계정의 통화/PTT 요청 거부 확인 → 원래 계정에서 종료.
6. 시뮬레이터 종료 → OFFLINE, 상태 미수신 확인.

시뮬레이터는 실제 음성이나 물리 장치 성공을 증명하지 않습니다.
