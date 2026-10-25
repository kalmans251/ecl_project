# 브라우저 Codec2 음성통화

## 실행과 업데이트

음성 Codec2 인코딩·디코딩은 각 사용자 브라우저의 전용 Web Worker에서 수행합니다.
AudioWorklet은 마이크를 8 kHz PCM으로 변환합니다. Spring Boot는 권한·통화 상태를 검증하고
48바이트 Codec2 패킷만 중계합니다. 서버 공통 Codec2 잠금이나 DLL 로딩은 통화에 사용하지 않습니다.

서버를 업데이트하고 기존 토큰이 설정된 창에서 실행하세요.

```powershell
git pull
cd monitoring-server # 이미 이 폴더라면 생략
mvn verify
mvn spring-boot:run
```

브라우저에서 Ctrl+F5로 새 코드를 불러오세요. Windows C 컴파일러/Codec2 DLL/별도 Python은 필요 없습니다.
WASM은 저장소와 JAR에 포함됩니다. HTTPS/WSS와 마이크 권한은 필요합니다.
Nginx가 CSP를 추가한다면 `script-src`에 `'wasm-unsafe-eval'`, `worker-src 'self'`가 필요합니다.
서버의 기본 CSP에는 포함되어 있습니다. 일반 JavaScript `'unsafe-eval'`은 추가하지 마세요.

Pi는 기존 명령을 그대로 사용합니다. Pi/P4/WROOM/S3의 음성 패킷 변경은 없습니다.

```bash
python main.py --port /dev/serial0 --baud 9600 --event-railings 1 \
  --monitor-url wss://omtest.duckdns.org/ws/gateways/gateway-01 --web-voice
```

## 통화

통화 시작·듣기 → 말하기·마이크 켜기 → 듣기·마이크 끄기 → 종료 순서로 확인하세요.
말하기 활성화 전에 Codec2 로딩과 P4 방향 확인을 기다립니다.
진단의 PCM 수/전송 수/peak는 사용자 PC의 캡처와 압축 전 입력입니다.
서버 전송 로그는 난간 스피커의 실제 출력 확인을 의미하지 않습니다.

각 브라우저는 독립 WASM 메모리와 인코더·디코더를 갖습니다. 다른 사용자의 음성 데이터를 공유하지 않습니다.
PTT epoch 변경 시 codec 상태를 초기화하고 오래된 변환 결과를 버립니다.
변환 대기는 방향별 2개로 제한하며 초과 음성은 폐기합니다. 화면/연결 전환으로 지연된 음성을 나중에 몰아서 보내지 않습니다.
일시적인 패킷 도착 간격 변동은 서버의 기존 rate limiter로 허용하며, 지속 과속은 연결을 유지한 채 폐기합니다.

## 전송 규약

웹 음성 socket은 통화 중 유지합니다. bind에 `codec: "codec2-2400-v1"`을 명시하며 서버 ready 응답도 이를 확인합니다.
양방향 바이너리는 `36 ASCII bytes epoch UUID + 48 bytes Codec2` = 84바이트입니다.
구형 PCM 클라이언트는 거부되므로 새 서버 적용 후 페이지 새로고침이 필수입니다.
게이트웨이 JSON과 PLC 세션·순서·방향 검사는 기존과 같습니다.

## 빌드와 검증

- `node --test src/test/js/*.test.js`: 실제 WASM round trip, 고정 native 호환 벡터, worker epoch, 오래된 PCM 폐기 테스트.
- `mvn verify`: 네이티브 Codec2 없이 서버의 인증된 WebSocket 중계 테스트.
- 선택적 native 비교 테스트는 Linux `mvn -Pnative-codec verify`, Windows `mvn -Pwindows-codec-auto verify`.
  서버 음성 운영에는 필요하지 않습니다.
- WASM 재빌드: Emscripten 3.1.64 환경에서 `python tools/build-codec-browser.py`.
  Codec2 소스 커밋은 `3e347e0b70fc72af9357fbbd32b10a125321d6c5`, API 모드 1(2400), 160 samples/6 bytes입니다.
- `/codec2/LICENSE.txt`, `/codec2/source.tar.gz.base64.txt`에 라이선스와 정확한 소스·재빌드 스크립트를 배포합니다.
  소스 파일은 base64 해독 후 tar.gz로 풉니다. `/codec2/manifest.json`에는 번들 해시가 있습니다.

실제 장비에서 양방향 10분 통화, PTT 반복, 탭 전환, 연결 끊김·재연결을 검증하세요.
30명 동시 통화 성능이나 P4 전환 지연 개선을 보장하는 변경은 아닙니다.

## Independent sites and disconnect recovery

Each site must have its own gateway ID/token and user memberships. Local rail numbers
may overlap (for example, both gateways may have rail 1); routing uses gateway and
call identity, not the local rail number alone. A foreign gateway's voice envelope
is rejected on the sending connection without closing the target operator socket.

A current gateway disconnect makes only its calls UNKNOWN. A delayed close callback
from an old gateway connection cannot invalidate its replacement. Browser media loss
uses the existing 15-second grace period and pauses that call's renewal; physical
termination must still be confirmed before releasing its reservation.

`PortalTest.twoSitesKeepVoiceAndRecoveryIndependent` uses two authenticated users,
two sites, and two simulated gateway WebSockets. It checks simultaneous calls and
both audio directions, cross-site access denial, foreign voice rejection, reconnect
and confirmed hangup, and browser disconnect recovery. `GatewayDisconnectTest`
covers closed-session callbacks and obsolete callbacks after replacement.
These tests do not measure 30-call capacity or real PLC audio quality.
