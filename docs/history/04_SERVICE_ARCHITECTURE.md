# Ember 서비스 구조·기능·데이터 경계

## 현재 실행 구조

```text
휴대폰/웹캠 JPEG + 카메라별 전송 키
                        ↘
ITS catalog → 허용 HLS → 최신 조각 → FFmpeg → JPEG
                        ↓
FastAPI 인증/입력 제한 → bounded admission → 단일 YOLO11n CPU 추론
                        ↓
모델 후처리 → 카메라 제외구역/점수 → 공간·시간 후보 게이트
                        ↓
알람 DB + JPEG 증거 + 감사/검토 기록 → WebSocket/REST → React
                        ↓
사람의 발화점 또는 검증된 보정 위치
                        ↓
기상 + DEM/숲 격자 → 별도 CPU 확산 worker → GeoJSON/작업 이력
                        ↓
Naver 지도 중첩 / MapLibre 로컬 GIS·PNG 내보내기
```

현재 API는 Uvicorn 1worker이며 추론 실행기·프리뷰·시간 게이트·속도 제한·WebSocket 팬아웃 일부는 메모리 상태다. 추론 admission을 제한하고 오래된 입력을 무제한 누적하지 않는다. 확산은 전용 CPU process 1개, 대기/실행 작업 최대 3개로 분리한다. DB 기록과 계산 결과는 남지만 서버가 꺼진 시간의 영상은 감지하지 못한다.

## 폴더 지도

| 경로 | 역할 |
| --- | --- |
| backend/app/main.py | 인증·카메라·프레임·알람·조회 API 및 연결 |
| detector.py / policy.py | 모델 시작 로드·입력 검사·후처리 |
| alerts.py / monitoring.py | 시간/공간 후보 게이트·무재생 서버 감시 |
| providers.py / stream_reader.py | 공식 API 캐시·안전한 HLS 수집·디코딩 |
| localization.py | 평면 보정·시야 검사·위치 보류 |
| soak.py / research_metrics.py | 시간 제한 시험 집계·평가 |
| security.py / models.py / db.py / storage.py | 세션/키·DB·증거 저장 경계 |
| backend/app/spread/ | 날씨·위험지수·GIS 전처리·엔진·작업 API |
| backend/migrations/versions/ | Alembic schema 이행, 최신 0004 archive |
| frontend/src/App.tsx | 로그인·대시보드·메뉴·알람 상태 |
| CameraViewer.tsx | 선택 HLS 재생·archive/restore |
| MonitoringPanel.tsx | 감시·시험·보정 설정 |
| SpreadPage.tsx 등 | 시나리오·지도·저장 결과·다운로드 |
| infra/ / compose.yaml | Docker/HTTPS/배포 설정 |
| scripts/ | 설치·시작/중지·기기 전송·전처리·시험/평가 |
| models/ | 비공개 pt와 검증 정책 |
| runtime/ | DB·증거·API 캐시/시험·GIS·확산 결과·로컬 백업, Git 제외 |

## 웹 기능

Ember는 반응형 웹이며 현대적인 관제 대시보드 스타일을 구현했다. 'Figma 디자인 참고' 요청이 있었지만 별도 Figma 원본 파일을 제작/가져왔다고 기록하지 않는다.

- 모니터링 개요: 카메라 연결 상태, 최근 후보, 미처리 알람, 최근 처리 정보.
- 카메라 관리: 등록/연결 코드/QR, 활성/중지, 최근 분석 정지 이미지, 선택 ITS HLS 재생, 제거/복원.
- 알람 기록: 증거·카메라 이름·설치 좌표·후보 종류·점수·시각·모델/규칙 해시, 확인/종료 상태.
- 공공 CCTV: 기관 목록/지도 선택, 서버 감시 설정, 자동 종료 시험, JSON 집계, 보정·자동 확산 선택.
- 확산 시뮬레이션: 수동 발화점/주소, 실황/가상 날씨, 시간/모델/seed, 결과 이력·GeoJSON/로컬 PNG.
- 시스템 설정: 실제 로그인/비밀번호 변경·기기 연결·모델/서버 정보.

알람의 '확인됨/종료됨'은 관제 업무 상태다. '실제 불꽃/오탐/보류'라는 정답 리뷰와 다르다. confidence는 모델 후보 점수이지 검증된 화재 확률이 아니다. 소리는 사용자 클릭이 필요하고 시스템 알림은 브라우저 권한/지원에 의존한다.

## 휴대폰 입력과 공공 CCTV 입력의 차이

휴대폰은 getUserMedia로 카메라 프레임을 JPEG로 보내고 카메라별 bearer key를 사용한다. 약 1초 간격, 직전 요청 완료 후 다음 전송 구조다. HTTPS가 필요하고 Android/iPhone CA 신뢰·권한을 사용자가 직접 설정해야 한다.

ITS 서버 감시는 허용된 HLS 최신 조각에서 프레임을 추출한다. 샘플 간격은 기본값과 실제 시험값이 다르다. 시험은 최소 10초 + 네트워크/디코딩/추론 시간이다. UI의 활성 카메라 수, 등록 수, 감시 enabled 수, 실제 새 프레임 수신 수는 서로 다르다.

초기 휴대폰 fire 게이트는 최근 5프레임 중 3개·최소 1초, 장시간 프레임 공백 초기화 규칙이었다. 공공 서버 감시는 느린 샘플링에 맞춰 최근 5프레임 중 3개·최소 6초·동일 위치 IoU 0.2를 사용한다. 10-10 smoke 후보도 서버 알람에 추가했으며 점수 0.5는 초기 연구 기준이다. 프레임 점수/정적 데이터 precision과 이 시간 게이트의 사건 성능을 섞지 않는다.

## 선택 재생과 무재생 감시

카드에는 최근 분석 이미지가 보인다. 새 프레임이 늦으면 과거 이미지/오류로 표시하고 5분 이후 캐시가 사라진다. 이를 '실시간 영상이 정상'이라고 표시하지 않는다. CameraViewer는 한 카메라를 사용자가 재생할 때만 연결하며 닫기/정지/숨김에서 연결을 정리한다.

알람의 '카메라 화면 보기'는 해당 카메라 창을 열고 ITS 재생 버튼으로 영상을 시작한다. 자동 열기는 이 브라우저의 옵션이며 기본 OFF, 예제 알람은 대상이 아니고 이미 열린 다른 카메라를 강제로 교체하지 않는다. 서버 감시는 플레이어와 독립적이다.

## 카메라 제거/복원

`archived_at` soft archive를 사용한다. 제거는 진행 중 시험/감시를 종료하고 pairing/publisher key를 폐기하며 활성 목록·수용 한도에서 제외한다. 과거 알람/증거는 보존하고 기존 보관 정책은 유지한다. 복원 후 비활성 상태로 새 연결 코드를 발급해야 한다. 동일 ITS 등록이 archive와 충돌할 때 무분별한 중복 생성을 막는다. 최신 DB 이행은 Alembic 0004다.

## API·보안 경계

관리 세션은 랜덤 token의 해시를 DB에 저장하고 HttpOnly cookie로 사용한다. 카메라 연결 코드는 8자리·10분 일회용이며 조건부 SQL 갱신으로 동시 교환 한 건만 성공한다. 카메라 전송 키는 해당 카메라로 한정하고 만료/중지/archive에서 폐기한다. 관리자 소유권 확인 후 증거를 전달하고 evidence 폴더를 public static으로 열지 않는다.

입력 프레임은 최대 2MB, 16M pixels, 한 변 4,096px, 허용 이미지 형식과 처리 수 제한을 둔다. 임의 사용자 영상 URL을 범용 다운로드하지 않는다. HLS 수집은 정확한 호스트 허용 목록·공개 IP/DNS·TLS/SNI 검사·크기/시간 제한을 사용한다. 제약 없는 프록시나 인증 우회는 제공하지 않는다.

알람을 DB에 먼저 기록하고 증거 I/O 실패를 별도 상태로 남겨 '사진 없음=알람 없음'이 되지 않도록 한다. WebSocket은 통지이며 REST 조회가 보완한다. 로그/오류/시험 보고서에는 키·서명 URL query를 포함하지 않는다.

## 데이터베이스와 스토리지

실제 로컬은 SQLite `runtime/ember.db`다. 사용자·세션·카메라·연결 코드/전송 키·알람·감사/정답 검토·감시 설정·trial·증거 만료 등을 저장한다. 새 테이블/열은 Alembic으로 이행한다. 시작 스크립트가 `alembic upgrade head`를 수행한다.

배포 설정은 PostgreSQL을 요구하고 로컬/S3 스토리지 어댑터가 있다. PostGIS를 이미 DB에서 운영하거나 S3 보존 lifecycle·RDS 복구·다중 AZ를 실측한 상태는 아니다. GIS 격자/시뮬레이션 GeoJSON은 version manifest와 파일 기반으로 저장한다.

## 현재 범위와 확장

현재 등록 한도는 기본 8대, 동시 공공 감시 한도는 4대이며 CPU 추론은 단일 프로세스다. 4대 모두 무중단·모든 산불 감지·수천대 처리 보장을 의미하지 않는다. 여러 API replica/GPU worker에 앞서 카메라 lease/sharding, 최신 프레임 queue, 분산 rate limit, durable temporal gate, idempotent event/dedup, broker/pubsub, 부하/복구 시험이 필요하다.

Docker Compose와 향후 AWS ALB/ECS 또는 CPU/GPU EC2, PostgreSQL/RDS, private S3, Secrets Manager, CloudWatch 제안이 존재한다. 현재 실제 AWS 리소스를 만들거나 공개 서비스를 배포하지 않았다.
