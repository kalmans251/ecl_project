# 서버 PC CCTV 분석

[전체 설치·보안·연동 절차](../deployment/cctv/README.md)를 따르세요.
`main.py --config config.json`은 한 카메라의 YOLO/ByteTrack과 선택적 MiVOLO를 실행합니다.
분석 상태가 켜진 경우에만 로컬 MediaMTX를 읽고 카메라별 인증 API로 enter/age를 전송합니다.
ROI와 추적 이력은 카메라별로 격리됩니다. 테스트는 모델 다운로드 없이 실행할 수 있습니다.

## 얼굴+전신 나이 추정 (선택 기능)

기본 설정은 기존 운영을 변경하지 않도록 `age.enabled=false`입니다.
새 서버에서는 `config.example.json`의 `age.backend=v2`를 사용할 수 있고,
기존 `config.json`에 `backend`가 없으면 예전 `v1` 방식이 그대로 유지됩니다.

### Windows 설정 (YuNet 파일은 수동 제공)

1. 기존 설정 파일 `analytics-server/config.json`을 유지합니다 (토큰을 Git에 올리지 마세요).
2. YuNet 파일을 `analytics-server/models/face_detection_yunet_2023mar.onnx`에 복사합니다.
3. 기존 `.venv`가 있는 서버에서 `powershell -ExecutionPolicy Bypass -File .\setup-age.ps1 -InstallDependencies`를 실행합니다.
   스크립트는 구형 MiVOLO의 `pkg_resources` 빌드 의존성을 위해 호환 가능한 setuptools를 설치하고,
   MiVOLO 패키지는 `--no-deps --no-build-isolation`으로 설치합니다. 이렇게 해야 기존 YOLO11에 필요한
   Ultralytics가 구형 `8.1.0`으로 내려가지 않습니다.
4. 이 명령은 `config.json.backup.<timestamp>`를 만든 다음 **`age` 필드만 갱신**합니다. 카메라 ID, URL, 인증 토큰은 유지합니다.
5. `\.venv\Scripts\python.exe main.py --config config.json`으로 실행하고 `backend=v2 | face=True` 로그를 확인합니다.

최초 실행 시 Hugging Face 모델 다운로드가 필요합니다. 서버가 인터넷에 연결되지 않았다면
미리 내려받은 모델 디렉터리를 `age.model_id`로 지정해야 합니다.
`age.backend=v2`는 Hugging Face `iitolstykh/mivolo_v2`를 `transformers`로 로드합니다.
공식 모델 카드의 BGR 얼굴/전신 384px 전처리 및 추론 API를 사용합니다.

**라이선스 주의:** 위 공개 MiVOLO v2 가중치는 `CC-BY-NC-4.0`으로 표시되어 있습니다.
상업용 스마트 난간 운영에 사용하려면 권리자에게 별도 사용 허가를 확인해야 합니다.
설치 스크립트는 이 사항을 경고하며 라이선스 승인을 대신하지 않습니다.

실제 나이 추정 기능을 활성화하려면 다음을 확인합니다.

- `age.enabled=true`: 별도 나이 추정 프로세스 실행
- `age.backend`: `v1`(기존 체크포인트) 또는 `v2`(Hugging Face 모델)
- `age.repo`, `age.checkpoint`: `v1` 모드에서만 사용하는 기존 경로
- `age.model_id`: `v2` Hugging Face 모델 ID 또는 사전에 다운로드한 로컬 모델 경로
- `age.face_model`: [OpenCV Zoo YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)의 로컬 ONNX 모델 파일 경로
- `age.require_face=true`: 검출된 얼굴이 없거나 품질이 부족하면 전신만으로 나이를 확정하지 않음
- `age.min_face_width=24`: 최소 얼굴 박스 폭·높이(px), 진단용 완화값
- `age.min_face_sharpness=5`: Laplacian 분산 기준의 진단용 흐림 임계값(현장 영상에서 재조정 필요)
- 높은 곳의 CCTV에서 검출률 진단을 위한 시작값은 `face_conf=0.65`, `min_face_width=24`, `min_face_sharpness=5`입니다.
  좁고 흐린 얼굴까지 통과하므로 **나이 추정 정확도를 보장하지 않으며**, 현장 검증 뒤 조정해야 합니다.
- 관제 오버레이의 `얼굴 미검출`, `얼굴 크기 부족`, `선명도 부족`, `유효 프레임 부족`, `나이 추론 실패`는
  분석 실패 원인입니다. `미인식`이 반복되면 각 원인의 빈도를 먼저 확인하세요.
- `age.window_seconds=4`, `age.min_samples=3`: 복수 샘플을 모을 시간과 최소 샘플 수

`face_model=null`이면 기존 **body-only** 경로가 유지됩니다. 얼굴 검출 파일을 설정하면
한 명의 추적된 사람 크롭 안에서 YuNet 얼굴 박스를 찾고, MiVOLO에 얼굴과 전신을 함께 전달합니다.
유효 얼굴이 없으면 결과를 반환하지 않고 후속 프레임에서 재시도합니다.
입력은 YOLO의 640px 축소 영상이 아니라 RTSP 원본 프레임의 사람 크롭입니다.

기존 Spring Boot `/events` 계약은 `age_group=10|20|30|40|keep`로 유지됩니다.
50대 이상이나 충분하지 않은 추정값은 `keep`으로 전달하며 음악 선택에 영향을 주지 않습니다.
사람별 소수점 나이 중앙값은 별도의 overlay 경로에서만 표시될 수 있습니다.
**이 구성은 ±3~5세 정확도 보증을 의미하지 않습니다.** 실제 나이 레이블이 있는 동의된 현장 시험 영상으로 검증해야 합니다.

GPU에서 모델 초기화 실패 시 `[Age/MiVOLO Init Error]` 로그와 `age=unavailable` 상태를 확인하세요.
기존 CCTV 이벤트는 나이 추정 엔진 실패와 독립적으로 운영됩니다.
