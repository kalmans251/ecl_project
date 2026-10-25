# 서버 PC CCTV 분석

[전체 설치·보안·연동 절차](../deployment/cctv/README.md)를 따르세요.
`main.py --config config.json`은 한 카메라의 YOLO/ByteTrack과 선택적 MiVOLO를 실행합니다.
분석 상태가 켜진 경우에만 로컬 MediaMTX를 읽고 카메라별 인증 API로 enter/age를 전송합니다.
ROI와 추적 이력은 카메라별로 격리됩니다. 테스트는 모델 다운로드 없이 실행할 수 있습니다.
