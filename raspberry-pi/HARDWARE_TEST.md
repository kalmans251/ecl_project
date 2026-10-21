# Pi ↔ P4 ↔ WROOM ↔ S3 통합 검증

모니터링 서버 없이 Pi가 시험 관제 역할을 한다. 도구는 별도 프로토콜을 구현하지 않고
운영 코드의 PlcBus, DeviceControls, AudioManager, EventPoller, VoiceRelay,
선택적 LocalAudio를 사용한다. TCP listener나 서버 WebSocket을 열지 않는다.

## 준비

1. 네 장치에 서로 호환되는 최신 코드를 적용한다. 펌웨어 버전/커밋을 시험 메모에 기록한다.
2. **기존 main.py, 서비스로 실행한 Pi 프로그램, voice_send.py 및 UART 테스트 프로그램을 종료한다.**
   동일 UART를 두 프로세스가 읽으면 응답을 빼앗는다. 이 도구가 다른 프로세스를 자동 종료하지 않는다.
3. Pi 프로젝트 디렉터리에서 기존 가상환경을 활성화하고 의존성을 설치한다.

```bash
cd ~/ecl_prj/ecl_project/raspberry-pi
source .venv/bin/activate
pip install -r requirements.txt
python tools/hardware_test.py --help
```

기본 포트는 `/dev/serial0`, 9600 baud다. GPIO14 TX=물리 8번, GPIO15 RX=물리 10번
UART 설정을 사용한다. 포트가 다르면 `--port`를 지정한다.
`--rails`에는 실제 설치되어 있고 ID가 서로 다른 난간만 넣는다.

`--call-state-file` 기본값은 main.py와 같은 `~/.local/state/ecl-railing/calls.json`이다.
기존 운영 설정에서 다른 경로를 썼다면 같은 경로를 지정한다. 미확인 통화가 남아 있으면
자동 시험을 시작하지 않으며, 파일을 삭제해서 우회하지 말고 수동 `hangup <id>`로 정리한다.

## 1. 통신 반복 검사 — 첫 시험

```bash
python tools/hardware_test.py --suite communication --rails 1 --cycles 10
```

각 회차마다 P4 ping, P4/WROOM/S3 상태 조회를 순차 실행한다. 수신 난간·발신 노드·요청 ID가
맞는 응답만 운영 매니저가 확인한다. 재전송으로 실패를 숨기지 않고 각 시도의 시간/결과를 기록한다.
상태 조회 성공은 해당 코드 경로의 응답 증거이며 모든 센서/출력의 물리 동작 증거는 아니다.

여러 난간은 같은 버스에서 순차 검사한다.

```bash
python tools/hardware_test.py --suite communication --rails 1,2,3,4 --cycles 100 --debug
```

`--debug`는 runtime.log에 UART 원시 RX/TX를 포함하므로 파일이 커진다.
CRC 오류나 잘린 프레임은 로그와 함께 분석한다. 시험 결과만으로 충돌이 없다고 단정하지 않는다.

## 2. 통화 상태 반복 검사

```bash
python tools/hardware_test.py --suite calls --rails 1 --cycles 10 --hold 3
```

`call → FIELD_TX 유지 → ptt on → CONTROL_TX 유지 → ptt off → FIELD_TX 유지 → hangup`
순서로 실행한다. 한 단계라도 실패하면 반복을 중단하고, 이 실행에서 시작한 미확인 통화에
종료를 시도한다. 종료가 확인되지 않으면 다음 난간으로 넘어가지 않는다.
`--rails 1,2,3,4`로 여러 난간을 **한 번에 하나씩** 검사할 수 있다.
이 모드는 `--local-audio`가 없으면 Pi 마이크 음성을 생성하지 않는다. 방향 전환 성공과
실제 양방향 음성 성공은 별개다.

## 3. 실제 음성·출력 수동 검사

```bash
pip install -r requirements-playback.txt
python tools/hardware_test.py --list-audio-devices
python tools/hardware_test.py --suite manual --rails 1 --local-audio --mic-device 0 --speaker-device 1
```

위 장치 번호 0/1은 예시다. 현재 목록에서 입력 채널이 있는 USB 마이크와 bcm2835
Headphones AUX 출력을 골라 바꾼다. 로컬 음성 시험은 한 난간씩 수행한다.

```text
 test> call 1
 test> wait 10
 test> check pass 난간 마이크를 말했을 때 Pi AUX에서 명료하게 들림
 test> ptt 1 on
 test> wait 10
 test> check pass Pi USB 마이크를 말했을 때 난간 스피커에서 명료하게 들림
 test> ptt 1 off
 test> status
 test> hangup 1
 test> check pass 통화 종료 후 이전 음악 상태가 복원됨
 test> quit
```

`check`는 관찰 기록이다. 자동 검사 결과를 바꾸지 않으며 실제 확인한 내용만 적는다.
끊김/잡음이 있으면 `check fail ...`, 확인할 수 없으면 `check skip ...`를 사용한다.
`status`/`wait` 뒤 스냅샷에는 음성 카운터와 LocalAudio 누락/드롭/버퍼 상태가 포함된다.
0개 누락 카운터만으로 실제 스피커 음질 정상이라고 판단하지 않는다.

LED/음악/볼륨/프로젝터는 같은 수동 모드에서 운영 CLI 명령을 사용할 수 있다.

```text
 test> volume 1 10
 test> led 1 basic
 test> check pass 기본 LED 패턴 확인
 test> led 1 music
 test> music 1 start
 test> check pass 음악 재생과 LED 반응 확인
 test> music 1 stop
 test> check pass 실제 음악 정지 확인
```

`help`로 문법을 확인한다. 전원·음악·LED·슬립 등의 수동 변경은 자동으로 원래 값으로
되돌리지 않는다. 시험 종료 전에 원하는 상태로 직접 복구한다. 통화는 기존 통화 관리자의
복원 정책을 사용한다.

## 4. 비상·슬립·연결 끊김 및 복구

수동 모드에서 실제 장치를 조작하고 `check`로 기록한다.

- 비상벨: 버튼 누름 → 이벤트 수신을 `status`에서 확인 → `ack 1` → 양방향 PTT →
  `hangup 1` → 경보/음악/LED 복원 상태 확인. 비상벨 이벤트가 없는데 ACK를 성공으로 간주하지 않는다.
- 슬립: `sleep 1 on` 후 실제 슬립 진입과 레이더 감지에 따른 복귀 확인. 음악/LED 모드별로
  확인한 뒤 `sleep 1 off` 등 원래 설정으로 복구한다.
- 연결 이상: 통화 중 S3 연결 또는 해당 저전압 장치 전원을 중단 → `wait 8` → `status`로
  통화가 unknown/종료 과정에 들어가는지 확인 → 연결 복구 → `hangup 1`로 확인된 종료 확인.
  이미 자동 END를 수신해 종료된 경우 추가 hangup은 'locally idle; no remote confirmation'으로
  기록될 수 있다. 이는 새 종료 확인을 얻지 못했다는 뜻이며 앞선 END 로그와 함께 판단한다.
- 복구 후 새 `call 1`로 시험한다. 미확인 통화가 남으면 다음 시험을 시작하지 않는다.
- 장시간: 통신/통화 cycles를 늘리거나 수동 통화를 유지한다. 비상벨·고장 주입은 자동으로 발생시키지 않는다.

## 결과 읽기

기본 `test-results/<시각>/` 또는 `--output <새 디렉터리>`에 저장한다. 기존 디렉터리는 덮어쓰지 않는다.

| 파일/판정 | 의미 |
|---|---|
| events.jsonl | 설정, 제어 수신 프레임, 단계 결과, 상태 스냅샷 |
| results.csv | 단계별 판정·소요 시간·실패 이유; Excel에서 열기 가능 |
| summary.json | 명령별 횟수·판정 분포·확인 비율·평균/최대 시간 |
| runtime.log | 운영 매니저 로그; --debug 사용 시 원시 UART 데이터 포함 |
| PASS | 해당 매니저가 명령/응답을 확인함; 실제 소리/빛 정상이라는 뜻은 아님 |
| POLICY_ONLY | P4의 음악 정책 적용만 확인; WROOM 재생은 미확인 |
| FAIL | 거부·시간 초과·실행 실패; 재시도 성공으로 과거 실패를 지우지 않음 |
| HUMAN_PASS/FAIL/SKIP | 사람이 직접 기록한 관찰; 자동 판정과 별도 |
| INTERRUPTED | Ctrl+C/입력 종료로 시험 중단; 가능한 경우 종료 정리 시도 |

summary의 `confirmed_rate`는 그 명령의 전체 기록 중 자동 PASS 비율이다. POLICY_ONLY와
사람의 관찰은 자동 성공으로 계산하지 않는다. 지연 통계에는 실패/시간 초과도 포함한다.
FAIL/HUMAN_FAIL/중단/정리 실패가 있으면 프로세스 종료 코드는 1이다.

처음에는 **난간 1의 통신 10회 결과**를 확인하고 통화 상태 시험으로 넘어가는 것을 권장한다.
결과를 공유할 때 위 네 파일과 P4/WROOM/S3 로그, 각 장치 펌웨어 커밋을 함께 제공한다.
