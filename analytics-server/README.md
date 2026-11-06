# 서버 PC CCTV 분석

[전체 설치·보안·연동 절차](../deployment/cctv/README.md)를 따르세요.
`main.py --config config.json`은 한 카메라의 YOLO/ByteTrack과 선택적 MiVOLO를 실행합니다.
분석 상태가 켜진 경우에만 로컬 MediaMTX를 읽고 카메라별 인증 API로 enter/age를 전송합니다.
ROI와 추적 이력은 카메라별로 격리됩니다. 테스트는 모델 다운로드 없이 실행할 수 있습니다.

## 얼굴+전신 나이 추정 (선택 기능)

기본 설정은 기존 운영 방식과 호환되도록 `age.enabled=false`, `face_model=null`입니다.
실제 나이 추정 기능을 활성화하려면 `config.json`에서 다음을 설정합니다.

- `age.enabled=true`: 별도 나이 추정 프로세스 실행
- `age.repo`: 설치된 [MiVOLO](https://github.com/WildChlamydia/MiVOLO) 소스 경로
- `age.checkpoint`: 해당 MiVOLO 코드와 호환되는 **face+body** 체크포인트 경로. v2로 변경 시 해당 버전의 가중치/의존성 조합을 별도 검증해야 합니다.
- `age.face_model`: [OpenCV Zoo YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)의 로컬 ONNX 모델 파일 경로
- `age.require_face=true`: 검출된 얼굴이 없거나 품질이 부족하면 전신만으로 나이를 확정하지 않음
- `age.min_face_width=64`: 최소 얼굴 박스 폭·높이(px)
- `age.min_face_sharpness=35`: Laplacian 분산 기준의 초기 흐림 임계값(현장 영상에서 재조정 필요)
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
