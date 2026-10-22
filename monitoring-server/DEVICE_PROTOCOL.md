# Device WebSocket v1

Pi는 `/ws/gateways/{gateway_id}`에 자신의 Bearer 토큰으로 접속합니다.
WSS 운영, loopback 개발만 WS. 기존 CCTV 이벤트 규격은 README를 참고하세요.
Pi main.py에는 음악 상태/목록/선택 재생 어댑터가 포함되어 있습니다.
나머지 명령은 향후 통합 어댑터가 구현해야 하는 규격입니다. `tools/mock_gateway.py`는 시뮬레이터입니다.

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

## 음악 현재 상태 (version 1, music_state)

인증된 게이트웨이 WebSocket에서 별도로 보내는 부분 상태다. 일반 `telemetry`와
병합해 전원/센서 값을 덮어쓰지 않는다. `railing_id`는 인증된 게이트웨이에 등록되어야 한다.

```json
{"version":1,"type":"music_state","railing_id":1,"observed_at":"2026-10-22T10:00:00Z","fresh_ms":10000,"state":{"available":true,"state":"playing","filename":"song.mp3","position_ms":12345}}
```

조회 실패/통화 중 조회 보류는 `state: {"available":false}`만 전달한다.
state는 `idle|playing|paused`, filename은 문자열 또는 null, position_ms는 uint32이다.
fresh_ms는 1000~120000이며 Pi의 전체 난간 순회 주기에 맞춘 유효기간이다.
관측 시각은 서버 기준 과거 60초~미래 2초 안이어야 한다. 구 연결과 역순 샘플은 적용하지 않는다.
`GET /api/portal/sites/{site}/state`의 난간별 `music_status`에서 최신 값과
`fresh`, `age_ms`, `fresh_ms`를 제공한다. 접속 사이트 권한을 그대로 적용한다.
Pi 연결/실물 테스트 방법은 [MUSIC_SYNC.md](MUSIC_SYNC.md)를 참조한다.


## 음악 목록/선택 재생 명령

기존 POST `/api/portal/commands`를 사용한다. 운영 권한과 단일 난간 선택이 필요하다.
`GET /api/portal/commands/{id}`는 해당 현장 조회 권한을 확인한 뒤 지속 저장된 결과를 반환한다.

| operation | value | 제한 |
|---|---|---|
| music.list | `default:0` 등 `group:offset` | group=default/10/20/30/40, offset=0/8/16/24, 최대 8곡, 45초 |
| music.play | `5:default:0` 등 `catalog_version:group:index` | version=uint32, index=0..31, 15초 |

`music.play`는 Pi가 조회한 목록의 버전과 항목을 확인하고 WROOM의 첫 PCM 출력을 확인한다.
단순 `ack APPLIED`로 완료할 수 없으며 아래 상관관계가 있는 `music_result`를 사용한다.
목록 완료는 COMPLETED로서 재생 성공(APPLIED)을 뜻하지 않는다.

```json
{"version":1,"type":"music_result","message_id":"요청 UUID","status":"COMPLETED","data":{"railing_id":1,"catalog_version":5,"group":"default","offset":0,"total":1,"tracks":[{"group":"default","index":0,"filename":"a.mp3"}]}}
```

```json
{"version":1,"type":"music_result","message_id":"요청 UUID","status":"APPLIED","data":{"railing_id":1,"catalog_version":5,"group":"default","index":0,"filename":"a.mp3","state":"playing","device_application_confirmed":true}}
```

실패 결과는 status=FAILED/UNKNOWN/EXPIRED, data=null이다. 서버는 인증된 gateway와 요청 ID,
난간, operation, group/offset 또는 catalog version/index 및 필드 범위를 검증한다.
만료/종결된 요청을 늦게 온 응답으로 성공 처리하지 않는다. 중복 요청은 Pi의 영속 기록으로
재실행을 막으며, 연결 끊김/실패 시 자동 재전송하지 않는다. 메시지 4096바이트 제한을 유지한다.
