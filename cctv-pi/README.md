# CCTV 전용 Pi

[전체 설치·보안·연동 절차](../deployment/cctv/README.md)를 따르세요.
`agent.py --config config.json`이 WSS 제어 lease에 따라 고정된 FFmpeg 복사 송출을 관리합니다.
`config.example.json`을 복사한 실제 설정에는 카메라 비밀번호와 장치 토큰이 들어가므로
Git에 올리지 말고 소유자 전용 권한으로 보관하세요.

## 카메라 시간 자동 동기화 (Pi 유선망에만 연결된 CCTV)

Pi가 Wi-Fi로 인터넷 시간을 받은 뒤, 유선 카메라에 ONVIF로 UTC 시간을 설정합니다.
카메라가 인터넷에 직접 접속하거나 Pi에서 라우팅/NTP 서버를 켤 필요는 없습니다.
영상 송출 여부 및 관제 WSS 연결과 독립적으로 시작 시 및 60초마다 확인합니다.
5초 넘게 차이가 나거나 시간대가 다르면 수정하고 다시 조회해 검증합니다.
재부팅으로 카메라 시간이 1970년으로 돌아가도 다음 검사에서 재시도합니다.

기존 `config.json`을 덮어쓰지 말고 다음 `time_sync` 항목을 추가하세요.
IP와 포트는 실제 카메라 ONVIF 설정에 맞춰야 합니다. 80은 예시입니다.

```json
"time_sync": {
  "enabled": true,
  "device_url": "http://192.168.1.2:80/onvif/device_service",
  "username": "카메라_ONVIF_시간설정_권한_계정",
  "password": "실제 비밀번호",
  "timezone": "KST-9"
}
```

- 카메라에서 ONVIF 및 시간 변경을 허용하세요. RTSP 조회 전용 계정은 권한이 부족할 수 있습니다.
- ONVIF 계정은 RTSP 주소에서 추출하지 않습니다. 비밀번호는 URL 인코딩하지 않은 원문입니다.
- `device_url`은 `camera_url`과 같은 호스트만 허용하며 리다이렉트를 따르지 않습니다.
- `KST-9`는 POSIX 표기로 한국 시간 UTC+09:00입니다. 서머타임은 끕니다.
- 시간 설정 방식은 **Manual**로 바뀝니다. 이후 주기적 보정은 Pi 에이전트가 담당합니다.
- 설정이 없거나 `enabled=false`이면 기존 동작을 유지합니다.

CCTV Pi의 기존 저장소에서 업데이트한 뒤:

```bash
git pull --ff-only
cd cctv-pi
.venv/bin/pip install -r requirements.txt
chmod 600 config.json
timedatectl show -p NTPSynchronized --value
# yes인지 확인하고 기존 에이전트를 종료한 뒤 다시 실행
.venv/bin/python agent.py --config config.json
```

서비스로 운영 중이면 실제 서비스 설정의 config 경로(예: `/etc/ecl-cctv/config.json`)를 수정하고
`sudo systemctl restart cctv-agent`로 재시작하세요. 수동 에이전트를 중복 실행하지 마세요.

Pi는 `timedatectl`이 `NTPSynchronized=yes`를 보고할 때만 카메라 시간을 변경합니다.
`no`이면 Pi의 인터넷 연결과 시간 동기화 서비스를 먼저 확인하세요.
`sudo timedatectl set-ntp true`로 시스템 NTP를 활성화할 수 있으나,
실제 시간 동기화 서비스가 설치되어 실행 중이어야 합니다.
카메라 시간이 1970년이어도 인증할 수 있도록 최초 읽기는 ONVIF PRE_AUTH 조회를 사용하고,
시간 설정의 WS-Security 토큰은 카메라 시각으로 생성합니다. HTTP Digest 인증도 지원합니다.
기기별 ONVIF 구현/권한 차이로 실패할 수 있으며 실물 카메라에서 검증이 필요합니다.

로그의 `camera time synchronized and verified (UTC+09:00)`는 변경 후 조회 검증 성공,
`camera clock verified`는 이미 올바른 시간임을 뜻합니다.
`waiting for Pi NTP synchronization`이면 Pi 시간 동기화 대기,
`time sync failed`이면 ONVIF 주소·포트·권한을 확인하세요.
실패는 다음 검사에서 재시도하며 영상 송출을 중단하지 않습니다.
현재 결과는 Pi 로그에서 확인하며 관제 웹 상태에 별도 전송하지 않습니다.


## FFmpeg RTSP 옵션 호환성

`Option rw_timeout not found`는 카메라 연결 이전에 FFmpeg가 입력 옵션을 거절한 오류입니다.
에이전트 시작 시 로컬 `ffmpeg -h demuxer=rtsp`로 지원 옵션을 확인합니다.
구형 빌드는 `-stimeout`, 최신 빌드는 마이크로초 단위의 `-timeout`을 사용합니다.
어느 옵션도 확인할 수 없으면 해당 옵션을 생략하고 기존 15초 무진행 감시로 재시작합니다.
옵션 탐지는 한 번만 실행되며 카메라 주소·암호를 전달하지 않습니다.
`RTSP timeout option: -timeout` 또는 `-stimeout` / `watchdog only` 로그로 확인할 수 있습니다.
설정을 새로 만들거나 카메라 시간을 되돌릴 필요는 없습니다. 코드 업데이트 후 에이전트를 재시작하세요.
