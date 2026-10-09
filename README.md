# Ember — 산불·불꽃 후보 모니터링

공개 소스 저장소: `200-Pro/fire-detection`. YOLO 학습 저장소 `200-Pro/fire-ai`와 분리한 서비스 프로젝트입니다. **새로 clone하면 모델·API 키·GIS 데이터·예제 이미지는 포함되지 않습니다.** 먼저 [팀원 설치·공개 범위 안내](docs/GITHUB_SETUP.md)를 확인하세요. GitHub 업로드와 AWS 서비스 배포는 별개입니다.

2026-10-09 최신: 사용자가 기관의 상시 AI 분석·이미지 저장 허용을 확인했다고 답한 뒤 ITS 4대의 1시간 연결 시험을 시작했습니다. [현재 시험·사용 방법](docs/CCTV_SOAK_TEST.md)을 먼저 보세요. 자동 위치/확산은 실제 카메라 보정이 없어 OFF이며 UTIC는 아직 미연결입니다. [기능 설명](docs/CCTV_MONITORING.md), [이전 검증 기록](docs/MONITOR_VERIFICATION.md)은 아래 최신 안내와 함께 읽으세요.

FastAPI + React/TypeScript로 만든 **연구·시연용 동작 프로토타입**입니다. 요청한 작업 위치는 `D:\fire-dettection`입니다. 원본 학습 프로젝트와 ZIP은 변경하지 않았고 검증한 YOLO11n `best.pt` 사본을 사용합니다.

## 바로 확인

PC 관제 화면: **http://localhost:5173**. 휴대폰 LAN HTTPS: **https://192.168.0.6:8443/camera**. 휴대폰 인증서 신뢰·카메라 권한은 직접 설정해야 합니다.

- 아이디: `admin`
- 로컬 기본 비밀번호: `fire-demo-local`
- `예제 테스트 → 불꽃 예제 → 6프레임 테스트 시작`으로 실제 모델 추론과 웹 알람을 확인합니다.
- 이 예제는 정지 이미지 반복이며 실시간 카메라로 위장하지 않습니다. 샘플 알람에는 DEMO 표시가 붙습니다.
- 탐지·알람 예제와 수동 확산 시나리오는 외부 API 키가 필요하지 않습니다. 실제 기상청 실황과 산불위험예보 조회는 서버 `.env`의 별도 키를 사용합니다.
- 로컬 기본 계정은 외부 공개용이 아닙니다. 공개 전 별도 강한 비밀번호·HTTPS가 필요합니다.
- 휴대폰 테스트 전에 `시스템 설정 → 계정 보안`에서 16자 이상 새 비밀번호로 바꾸세요. 이미 변경했다면 기본 비밀번호는 더 이상 유효하지 않습니다.

서버가 종료됐다면 PowerShell에서:

```powershell
Set-Location "D:\fire-dettection"
& ".\scripts\start-local.ps1"
```

휴대폰을 함께 테스트할 때는 `& ".\scripts\start-local.ps1" -LanAddress "192.168.0.6"`로 시작합니다. 자세한 기기별 절차와 공개 인증서 파일 위치는 [PHONE_TEST.md](docs/PHONE_TEST.md)에 있습니다. 실행 중인 인스턴스가 있다면 먼저 `stop-local.ps1`로 종료하세요.

실행 정책이 막으면 정책을 영구 변경하지 말고, 터미널 두 개에서 각각 직접 실행할 수 있습니다.

```powershell
# 터미널 1
Set-Location "D:\fire-dettection\backend"
& "D:\fire-dettection\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

```powershell
# 터미널 2
Set-Location "D:\fire-dettection\frontend"
npm.cmd run dev
```

브라우저는 `127.0.0.1` 대신 설정과 일치하는 **http://localhost:5173**으로 접속하세요. `start-local.ps1`은 사용 중인 포트에 두 번째 서버를 중복 실행하지 않습니다.

## 구현한 기능

- 관리자 로그인·로그아웃, HttpOnly 세션 쿠키, 요청 Origin/CSRF 헤더 검증.
- 현재 비밀번호 확인 후 비밀번호 변경, 다른 로그인 세션 폐기. 실제 변경은 사용자가 화면에서 직접 합니다.
- 카메라 이름/위치 등록, 활성화·중지, 온라인/오프라인 상태.
- 10분 유효 일회용 연결 코드와 QR. 카메라 전송 키는 해당 카메라 프레임 전송에만 사용할 수 있습니다.
- 같은 연결 코드의 동시 교환은 DB의 조건부 갱신으로 한 요청만 성공합니다.
- 휴대폰 후면/전면 카메라와 PC 웹캠의 JPEG 프레임 전송. 약 1초 간격, 이전 요청 완료 후 다음 전송.
- 시작 때 모델 한 번 로드, 단일 추론 실행기, 동시 요청 제한과 프레임 크기/해상도 검사.
- 검증한 fire 후처리 적용. 모델/설정 SHA 확인, 클래스 `0=smoke`, `1=fire` 검사.
- 여러 프레임의 fire 후보를 확인한 뒤 웹 알람. 같은 지속 신호의 중복 알림 억제.
- WebSocket 실시간 통지 + REST 주기 조회 보완. 알람과 증거는 DB/스토리지에 보관합니다.
- 증거 사진·박스·모델/설정 해시, 알람 확인/종료, 처리 감사 로그.
- 알람을 먼저 DB에 기록하고 사진 I/O는 별도로 처리합니다. 사진 저장 실패 시 알람은 남고 실패 설명이 표시됩니다.
- 사용자 클릭으로 소리 활성화. 브라우저가 지원하고 사용자가 허용하면 시스템 알림.
- 명시적으로 DEMO로 구분하는 실제 모델 예제 테스트.
- 별도 edge 스크립트의 PC 웹캠/RTSP 프레임 업로드. 서버는 임의 RTSP URL을 직접 가져오지 않습니다.
- 반응형 대시보드·카메라 관리·알람 기록·시스템 정보·휴대폰 연결 화면.
- 대구 일부 DEM·임상도 기반 연구용 확산 지도, 수동 발화점, 기상청 실황·가상 기상 구분.
- 원형/풍향 타원 기준선과 바람·경사·숲 CA, 10/30/60 모델분 비교, 반복 비율 지도.
- 국립산림과학원 대구 시도 산불위험지수와 이후 시각 자료 표시. 위험지수는 확산 속도에 적용하지 않습니다.
- 별도 CPU 프로세스의 확산 작업, 사용자별 결과 이력, seed·입력·자료/코드 해시 저장, 지도 PNG/GeoJSON 내보내기.

## 확산 시뮬레이션 시작

`확산 시뮬레이션 → 검증된 숲 격자 지점으로 초기화 → 기상 입력 선택 → 연구용 확인 체크 → 실행` 순서입니다. 알람 상세의 `발화점 지정·확산 실험`으로 해당 알람과 연결할 수도 있습니다. 카메라 위치를 실제 발화점으로 자동 변환하지 않습니다.

지금 버전은 **실제 산불로 보정하지 않은 연구용 시나리오**입니다. 대피 경로, 실제 도달시각, 화재 확률을 제공하지 않습니다. 다운로드한 원본 ZIP·IMG는 변경하지 않습니다. 사용·비교 실험·파일 구조·팀원 준비: [SPREAD_GUIDE.md](docs/SPREAD_GUIDE.md).

팀 시연은 [TEAM_DEMO.md](docs/TEAM_DEMO.md), 단일 변수 비교 실험은 [SPREAD_EXPERIMENTS.md](docs/SPREAD_EXPERIMENTS.md), 최종 검증 범위는 [VERIFICATION.md](docs/VERIFICATION.md)를 참고하세요.

## 카메라 테스트

실제 위성·일반지도와 공공 ITS CCTV는 [MAPS_CCTV.md](docs/MAPS_CCTV.md)를 참고하세요. `공공 CCTV`에서 대구 주변 목록을 조회하고 한 지점을 선택합니다. UTIC는 별도 승인·키·허용 IP가 필요하며 현재 미연결입니다. 주소 검색과 지도 클릭은 발화점 지정 보조이며 자동 위치 추정이 아닙니다.

1. 로그인하고 `카메라 연결`에서 이름·위치를 입력합니다.
2. PC 웹캠은 `이 PC에서 열기`로 `/camera`를 열고 연결합니다.
3. `전송 시작`을 누르면 해당 기기의 카메라 권한을 요청합니다. 마이크는 사용하지 않습니다.
4. 관제 화면에서 최근 프레임과 박스, 알람을 확인합니다.
5. 실제 불이나 위험한 상황을 만들지 말고 이미 준비된 불꽃 예제나 화면상의 안전한 테스트 이미지로 시험하세요. 이 방식도 실제 산불 환경 검증은 아닙니다.

**휴대폰은 HTTPS가 필수입니다.** PC의 `http://192.168.x.x`는 카메라 브라우저 권한이 동작하지 않는 경우가 아니라, 보안 조건 자체가 충족되지 않습니다. QR이 localhost 주소이면 휴대폰 연결용이 아닙니다. [휴대폰 안내](docs/PHONE_TEST.md)를 먼저 확인하세요.

## 기술 선택과 배포

- 프론트엔드: React + TypeScript + Vite, 로컬 아이콘/QR, 외부 폰트/CDN 없음.
- 백엔드: FastAPI + SQLAlchemy + Alembic, 모델 추론 어댑터 분리.
- 로컬 DB: SQLite. Docker/AWS: PostgreSQL. 대용량 영상은 DB에 저장하지 않습니다.
- 증거 저장: 로컬 볼륨 또는 IAM 역할 기반 S3. 평상시 최근 프레임은 메모리에서 일시 처리합니다.
- Docker: `compose.yaml`에 PostgreSQL·API·React/Nginx 구성. 모델은 읽기 전용 볼륨으로 교체 가능합니다.
- AWS: HTTPS ALB + ECS + RDS + S3 구성 제안. **실제 AWS 자원 생성/배포는 하지 않았습니다.**

아키텍처와 운영 전 요구 사항: [ARCHITECTURE.md](docs/ARCHITECTURE.md), Docker/AWS 실행 안내: [DEPLOYMENT.md](docs/DEPLOYMENT.md).

현재 알람 게이트·프리뷰·WebSocket 팬아웃은 단일 프로세스 메모리 상태입니다. **`--workers 1`, API replica 1로 실행하세요.** 다중 인스턴스/고가용성은 Redis 또는 브로커 기반 상태·추론 분리가 추가로 필요합니다. 파일을 Docker로 묶었다고 실서비스의 안전성과 고가용성이 검증되는 것은 아닙니다.

## 모델을 나중에 바꾸는 방법

1. 새 모델을 별도 validation/사용 카메라 데이터로 검증합니다.
2. 그 모델에 맞는 후처리 설정을 고르고 해시를 기록합니다.
3. `models/best.pt`와 `models/fire_policy_v1.json`을 함께 배포합니다. 이전 모델·설정 사본은 따로 보존하세요.
4. 서버를 재시작하고 `scripts/check-model.py`와 프레임·알람 테스트를 실행합니다.
5. API 결과 형식과 클래스 의미가 같으면 React 화면은 그대로 사용합니다.

해시만 억지로 바꿔 검사를 통과시키는 것은 검증이 아닙니다. 현재 파일의 옛 validation 수치도 새 모델의 성능으로 재사용하면 안 됩니다.

## 설치와 자동 테스트

현재 PC에는 프로젝트 내부 `.venv`와 `frontend/node_modules`를 설치했습니다. 새 PC에는 Python 3.12와 Node.js 24를 설치한 뒤 `scripts/setup-local.ps1`을 실행합니다. 모델 사본은 팀 내부에서 별도 제공해야 합니다.

```powershell
Set-Location "D:\fire-dettection"
& ".\.venv\Scripts\python.exe" -m pytest backend\tests -q
$env:EMBER_RUN_MODEL_TEST = "1"
& ".\.venv\Scripts\python.exe" -m pytest backend\tests -q
Set-Location "frontend"
npm.cmd test
npm.cmd run build
```

검증 기록과 **아직 실행하지 못한 검증**은 [VERIFICATION.md](docs/VERIFICATION.md)에 구분했습니다.

## 데이터·안전·라이선스

현재 알람은 불꽃 후보이며 확정 화재/자동 신고가 아닙니다. 실제 CCTV, 날씨, 작은 불꽃, 지속 감지 기준은 별도 검증해야 합니다. 브라우저 화면이 숨겨지면 휴대폰 전송을 일시 중지하고, 웹 창을 닫으면 이 버전에서는 백그라운드 푸시가 전달되지 않습니다.

실제 카메라의 사람·위치가 포함된 사진을 수집하기 전에 동의, 접근 권한, 보존 기간을 결정하세요. 자동 삭제는 이번 버전에 켜지 않았습니다. Ultralytics 및 D-Fire의 라이선스/재배포 권리를 확인한 뒤 외부 공개하세요.
