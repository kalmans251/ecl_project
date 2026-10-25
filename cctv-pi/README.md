# CCTV 전용 Pi

[전체 설치·보안·연동 절차](../deployment/cctv/README.md)를 따르세요.
`agent.py --config config.json`이 WSS 제어 lease에 따라 고정된 FFmpeg 복사 송출을 관리합니다.
`config.example.json`을 복사한 실제 설정에는 카메라 비밀번호와 장치 토큰이 들어가므로
Git에 올리지 말고 소유자 전용 권한으로 보관하세요.
