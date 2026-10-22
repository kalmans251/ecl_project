# 난간별 실제 음악 상태 동기화

WROOM이 실제로 선택·재생한 곡을 Pi가 조회해 서버 화면에 표시한다.
서버가 다음 곡을 추측하거나 재생 순서를 결정하지 않는다. 셔플/연령별 재생도
조회 시점의 실제 파일명과 재생 위치를 표시한다. P4/WROOM은 음악 조회가 추가된
펌웨어(PR #57 이후)를 사용한다. 이번 변경으로 펌웨어를 다시 올릴 필요는 없다.

## 먼저 Pi에서 확인

기존 `main.py`, `hardware_test.py`, `voice_send.py`를 모두 종료하고 하나만 실행한다.

```bash
cd raspberry-pi
source .venv/bin/activate
python main.py --port /dev/serial0 --event-railings 1 --music-sync
```

콘솔에서 `music-sync-status`로 난간별 마지막 조회 결과를 확인한다.
기존 `led 1 music`, `music 1 start`, `music 1 next`, `music 1 pause`,
`music 1 resume`, `music 1 stop` 명령을 사용할 수 있다.
`available: false`는 정지 확인이 아니라 조회 실패/보류다.
서버 없이도 이 단계까지 테스트할 수 있다. 이 옵션은 `main.py`용이다.

## 모니터링 연결

서버 관리 화면에 게이트웨이와 해당 난간 번호를 먼저 등록한다. 난간 번호는
게이트웨이 안에서 구분되며 다른 게이트웨이의 같은 번호와 섞이지 않는다.
Pi에는 해당 게이트웨이에 등록된 토큰을 사용한다. 토큰을 명령행 URL에 넣지 않는다.
Pi와 서버의 시간을 NTP로 맞춘다.

```bash
python -m pip install -r requirements-monitoring.txt
read -rs -p 'Gateway token: ' MONITOR_GATEWAY_TOKEN
export MONITOR_GATEWAY_TOKEN
python main.py --port /dev/serial0 --event-railings 1 \
  --monitor-url wss://monitor.example/ws/gateways/gateway-01
```

`monitor.example`은 실제 TLS 서버 주소로 교체한다. 서버의 기존 HTTPS/WSS
리버스 프록시 설정을 사용한다. 원격 평문 `ws://`는 거부하며 로컬 루프백만 허용한다.
동일 gateway ID의 `mock_gateway.py`를 함께 실행하지 않는다(새 연결이 이전 연결을 대체).
마이크/AUX 테스트도 함께 하려면 기존 `--local-audio --audio-railing 1
--mic-device 1 --speaker-device 0` 옵션을 추가한다. 장치 번호는 먼저 확인한다.

이 어댑터는 **음악 상태 전송만** 지원한다. 모니터링에서 내려오는 제어·CCTV 요청은
`FAILED`로 응답하며 실제 PLC 제어를 실행하지 않는다. 콘솔 제어는 기존대로 가능하다.
통합 원격 제어 어댑터, 화면의 음악 목록/곡 선택, 총 길이/seek는 후속 작업이다.

## 동작과 표시 지연

- `--event-railings`에는 실제 설치된 번호만 지정한다. 여러 대는 `1,2,3`처럼 지정한다.
- 기본 2초 간격으로 **한 대씩** 조회한다. `--music-poll-interval`은 1~30초이며
  난간별 주기가 아니다. 10대이면 한 바퀴 약 20초 + 응답 시간이 걸린다.
- PLC가 다른 요청으로 사용 중이거나 통화/비상/미확정 통화가 있으면 조회를 건너뛴다.
  조회 응답 대기는 최대 0.6초이며 진행 중인 단일 조회만큼 제어가 늦어질 수 있다.
- 곡 끝/다음 곡을 별도 이벤트로 모두 기록하는 기능은 아니다. 다음 조회 때 현재 곡을
  갱신하므로 짧은 중간 상태는 생략될 수 있다. PLC에 모든 난간이 동시에 알림을 보내지 않는다.
- 서버 화면은 2초마다 상태를 가져오고, 최신 `playing` 상태만 화면에서 경과 시간을 보간한다.
  실제 위치 기준은 WROOM이 I2S에 제출한 PCM이며 청취 위치와 약간 차이가 있을 수 있다.
- paused/idle/조회 실패/오프라인/기한 초과 시 시간을 추측해 증가시키지 않는다.
  stale일 때 보이는 값은 마지막 장치 측정값이다. 총 길이는 아직 `--:--`로 표시한다.
- 재연결 시 과거 상태를 쌓아 재전송하지 않는다. Pi는 난간마다 최신 한 건만 보관하며
  5초가 지난 송신 대기값을 폐기한다. 서버는 대체된 연결의 데이터와 순서가 뒤집힌 샘플을 거부한다.
- 음악 상태는 기존 전원/센서 `reported` 상태를 덮어쓰지 않는다.

## 확인 순서

1. Pi 콘솔에서 재생/다음 곡/일시정지/재개/정지를 수행하고 `music-sync-status`를 확인한다.
2. 화면에서 난간 하나를 선택하고 실제 곡명과 경과 시간이 바뀌는지 확인한다.
3. 자연스럽게 곡이 끝난 뒤 다음 조회 주기 안에 새 곡과 초기 시간이 표시되는지 확인한다.
4. 다른 난간을 선택해 곡명·시간이 독립적인지 확인한다.
5. 통화 시작/종료 및 서버 연결 끊김/복구 시 상태 확인 대기와 정상 갱신을 확인한다.

자동 테스트는 프로토콜 상관관계, PLC 잠금 양보, 난간 격리, WebSocket→권한 있는
상태 API, 오래된 상태 처리와 화면 보간을 검증한다. 실물의 음질·PLC 부하·TLS 배포는
실제 연결에서 별도 확인해야 한다.
