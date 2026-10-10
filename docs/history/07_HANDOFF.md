# 새 프로젝트·새 팀원 인수인계

## 현재 상태부터 읽기

2026-10-10 기준 Ember는 **실제 YOLO11n 탐지 + 사람 확인형 웹 알람 + 수동 발화점 기반 연구용 확산 지도**를 연결한 로컬 프로토타입이다. Naver 지도·주소 변환, 기상 실황, 산불위험지수, 대구 일부 DEM·임상도와 ITS HLS를 통합했다.

화면을 재생하지 않아도 등록·허용·활성 감시 CCTV는 서버가 분석한다. 현재 공공 감시는 최대 4대다. 최신 2분 시험은 48프레임·오류 0회지만 이전 1시간 시험의 403이 장기적으로 해결됐다고 확정하지 않았다. 실제 보정 자료가 없어 자동 위치·확산은 OFF다. UTIC, 실제 산불 정확도, 대피 경로, 수천 대 운영, Docker/AWS 배포는 미완료다.

## 저장소와 역할

- [서비스 저장소](https://github.com/200-Pro/fire-detection): 로컬 `D:\fire-dettection`.
- [학습 저장소](https://github.com/200-Pro/fire-ai): 현재 공유 `G:\내 드라이브\2026 3학년 2학기 진로탐색\Code\fire-ai`.
- 원본·학습 결과: Drive `Data/DFire`. ZIP·pt·개인별 artifact는 공개 Git에 넣지 않는다.
- 운영 자료: 서비스 `runtime`·`.env`. 계정 DB·API 키·서명 URL·사진·백업은 비공개다.

## 새 Codex 작업의 읽기 순서

1. `docs/history/README.md`와 이 인수인계.
2. `01_PROJECT_HISTORY.md`, `02_DECISIONS_AND_STACK.md`.
3. `docs/CCTV_CAMERA_WORKFLOW.md`: 현재 UI·감시 사용법.
4. `docs/CCTV_SOAK_TEST.md`: 시험·보관·요청 지표. 첫 1시간 실패와 이후 짧은 개선을 분리한다.
5. `docs/SPREAD_GUIDE.md`, `SPREAD_EXPERIMENTS.md`: 계산 입력·가정·면적 해석.
6. `GITHUB_SETUP.md`, `DEPLOYMENT.md`, `ARCHITECTURE.md`: 설치·확장 경계. 초기 미연결·fire-only 설명은 최신 history와 workflow로 보완한다.
7. 학습 저장소 `MODEL_DECISION.md`, `TRAINING_READY.md`, `fire_policy_result_20261005/REPORT.md`.

## VS Code에서 시작·종료

```powershell
cd D:\fire-dettection
.\scripts\start-local.ps1
```

브라우저를 자동으로 열지 않으려면:

```powershell
.\scripts\start-local.ps1 -NoBrowser
```

웹 주소는 `http://localhost:5173/`, 백엔드는 `127.0.0.1:8000`이다. 실제 계정 인증은 유지한다. 공개 초기 demo 비밀번호와 현재 사용자의 비밀번호를 혼동하지 않는다. 비밀번호는 이 문서에 기록하지 않는다.

```powershell
.\scripts\stop-local.ps1
```

포트 이미 사용 오류는 기존 서버가 살아 있는지 먼저 확인한다. 프로젝트 start/stop 스크립트는 소유 프로세스를 검사한다. 다른 프로세스를 PID만 보고 임의 종료하지 않는다.

```powershell
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen |
  Select-Object LocalPort, OwningProcess
```

실행정책 문제만 있다면 해당 터미널의 Process 범위에서 설정하고 영구 정책은 바꾸지 않는다. 시작 스크립트가 `alembic upgrade head`를 수행한다. 수동 Uvicorn 실행은 migration 누락에 주의한다.

## 빈 PC에서 복원

clone만으로 전부 동작하지 않는다. `GITHUB_SETUP.md`·`setup-local.ps1`에 따라 각 PC의 venv·Node 패키지를 설치한다. `.venv`·node_modules를 공유 Drive에서 복사하지 않는다.

별도로 필요한 비공개 자료:

- 신뢰된 `models/best.pt`·해당 `fire_policy_v1.json`, SHA·클래스 검증.
- 허용된 예제 이미지와 사용 목적·출처.
- `runtime/spread-data` 사본 또는 권한 있는 원본 GIS를 받아 전처리.
- 실제 API를 쓸 때의 서버 `.env`. 외부 키 없이 가능한 모델·가상 날씨 demo도 있다.
- 기존 계정·알람을 복구할 때 일관된 DB·evidence·job 백업. 공개 GitHub로 전달하지 않는다.

초기 LAN 주소 `192.168.0.6`은 새 네트워크에서 바뀔 수 있다. 휴대폰은 `PHONE_TEST.md`에 따라 실제 IP·HTTPS·CA 신뢰·카메라 권한을 맞춘다. 사용자 동의를 대신 승인하지 않는다.

## 재검사 명령

서비스 백엔드, 이번 결과 92개 통과:

```powershell
cd D:\fire-dettection\backend
$env:EMBER_RUN_MODEL_TEST='1'
& '..\.venv\Scripts\python.exe' -m pytest -q
```

프론트, 이번 결과 31개 통과·빌드 성공:

```powershell
cd D:\fire-dettection\frontend
npm.cmd run test -- --run
npm.cmd run build
```

학습 코드, 실제 unittest 방식·이번 결과 35개 통과:

```powershell
cd 'G:\내 드라이브\2026 3학년 2학기 진로탐색\Code\fire-ai'
& 'C:\fire-ai-local\.venv\Scripts\python.exe' -m unittest discover -s tests -p 'test_*.py' -v
```

새 위치에서는 cd와 venv를 바꾼다. Windows CPU lock을 Colab에 설치하면 CUDA 환경을 바꿀 수 있으므로 Colab은 `requirements-colab.txt`와 노트북을 사용한다.

기존 공간자료가 있는 상태의 확산 재현·시험 보고 조회:

```powershell
cd D:\fire-dettection
& '.\.venv\Scripts\python.exe' '.\scripts\check-spread.py' --report '.\runtime\spread-verification-final.json'
& '.\.venv\Scripts\python.exe' '.\scripts\cctv-trial.py' report
```

두 번째는 읽기 전용 보고다. 문서를 읽거나 서버를 켰다는 이유만으로 감시 시험을 시작하지 않는다. 실제 수집·보관에는 허용 조건과 사용자 요청을 확인한다.

## 다음 작업의 합격 기준

### P0 — CCTV 장시간 안정성

고정 코드·승인 조건으로 1대→4대 새 시간제 시험을 한다. 성공 프레임·403/429·정체·P95/최대 간격·요청/bytes·재연결·종료 후 늦은 알람을 별도 집계한다. 기존 실패 로그와 섞지 않는다. 무응답·흑화면·과거 프레임이 정상 감시처럼 보이면 안 된다. 개발 재시작도 기록한다.

### P1 — 실제 CCTV 탐지 성능

기관 허용 자료로 카메라·날짜·사건별 분할, 주야간 hard-negative 정답을 만든다. 불꽃·연기별 사건 recall, FP/hour, 탐지 지연 P50/P95를 측정한다. 예제 반복·알람 0건만으로 합격하지 않는다. 시간 필터의 미탐·지연 증가도 확인한다.

### P1 — 자동 위치·확산

고정 카메라 1대의 기준점 4개·검사점 2개와 시야·렌즈·높이·현장 근거를 확보한다. 평면 범위 밖·PTZ·산악·가림은 보류한다. 설치 좌표를 발화점으로 자동 사용하지 않는다. 오차·자료 범위·최신 기상을 통과한 연구 실험만 자동 확산을 켠다.

### P2 — 확산 연구

고해상도 DEM의 출처·권한·CRS·NoData·해상도를 검사하고 범위를 넓힌다. 실제 시간별 화재 경계를 확보해 보정 사건과 독립 평가를 분리한다. 원형·타원·CA의 동일 입력 IoU·거리·면적 오차를 비교한다. 실제 시간 보정 전에는 '모델분'을 유지한다.

### P2 — 배포·스케일

Docker·PostgreSQL·S3 실행, secret·TLS·기관 출발지 IP, backup/restore·장애 훈련을 검증한다. 수천 대는 수집 worker→최신 프레임 queue→GPU batch→분산 게이트·알람으로 별도 설계한다. 1,000대/10초의 약 100이미지/초는 요구 처리량 산술이지 현재 서버 성능이 아니다.

## 금지·주의사항

- 원본 ZIP·라벨·학습 결과를 임의 덮어쓰거나 실패 기록을 지우지 않는다.
- 비밀번호·키·DB·서명 URL·공공 CCTV 원본 사진은 공개하지 않는다.
- test로 규칙을 반복 선택하고 같은 test를 독립 평가로 보고하지 않는다.
- TLS·IP·host·인증 검사를 해제해 403을 우회하지 않는다.
- 카메라 위치를 발화점으로, CA 반복 비율을 화재 확률로, 모델분을 실제 도달시간으로 부르지 않는다.
- replica·Uvicorn worker만 늘려 메모리 상태가 분산 가능하다고 가정하지 않는다.
- 개발 편의 때문에 실제 계정 인증을 해제하지 않는다.

## 새 채팅에 붙일 시작 메시지

```text
Ember 산불 CCTV AI 프로젝트를 이어서 작업해줘.
서비스는 D:\fire-dettection, GitHub 200-Pro/fire-detection이다.
학습 코드는 200-Pro/fire-ai이며 YOLO11n 70epoch + fire_policy_v1을 쓴다.
70epoch 이후 새로운 재학습은 아직 없다.
docs/history/README.md와 07_HANDOFF.md, CCTV_CAMERA_WORKFLOW.md를 먼저 읽고 git status를 확인해줘.
서버 무재생 CCTV 분석·불꽃/연기 후보 알람·Naver 지도·수동 연구용 CA 확산을 구현했다.
4대·2분·48프레임·오류 0은 확인했지만 장시간 403 안정성은 미확정이다.
UTIC·실카메라 자동 위치·실화재 정확도·수천 대 운영·Docker/AWS 배포는 아직이다.
키·비밀번호·원본 자료를 공개하지 말고 실제 인증을 유지해줘.
사용자가 허용한 범위에서 다음 작업의 검증 기준을 먼저 정한 뒤 진행해줘.
```

새 작업자는 서버·감시 수·미커밋 변경을 읽기 전용으로 확인한 뒤 작업한다. 이번 문서화는 프로젝트 이동이나 새 채팅 생성을 수행하지 않았다.
