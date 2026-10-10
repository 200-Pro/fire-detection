# Ember 기술 아카이브·현재 기준

기준일: 2026-10-10. 프로젝트 대화와 두 저장소, 실제 학습·검증 자료를 대조했다. **계획·구현·테스트·실제 환경 검증·미완료를 구분**한다. 대화의 정제 원문은 비공개 Notion 부록에만 보존하고 공개 Git에는 기술 문서를 게시한다.

## 문서 순서

1. [프로젝트 단계별 전체 연혁](01_PROJECT_HISTORY.md)
2. [초기·현재 기술스택과 의사결정 근거](02_DECISIONS_AND_STACK.md)
3. [D-Fire 정리·70epoch 학습·평가·후처리](03_MODEL_AND_DATA.md)
4. [서비스 구조·인증·카메라·알람](04_SERVICE_ARCHITECTURE.md)
5. [API·GIS·지도·확산과 위치 추정](05_APIS_GIS_AND_SPREAD.md)
6. [검증·실패·한계·남은 작업](06_TESTS_AND_FAILURES.md)
7. [새 프로젝트 실행·인수인계](07_HANDOFF.md)
8. [근거·산출물·비공개 보존 목록](08_SOURCES_AND_ARTIFACTS.md)

## 현재 사실

- YOLO26n 3epoch 시험 후 YOLO11n 본 학습 70epoch를 완료했다. 현재 모델 SHA는 `57c133a489976dc2f7341381b12cf160622e0bbaff33aeffdee4926e2093611d`다.
- 후처리 전후 동일 CPU 비교에서 불꽃 FP 870→738, FN 639→638이었다. 재학습은 아니며 불꽃 없는 이미지의 잘못된 후보 34장은 그대로다.
- FastAPI + React/TypeScript/Vite, 로컬 SQLite를 사용한다. PostgreSQL/S3 배포 설정은 있지만 실제 PostGIS·Redis·ONNX·MLflow 운영은 없다.
- Naver 일반·위성 지도와 주소 변환, MapLibre 로컬 GIS, 기상·위험지수, 대구 일부 DEM·임상도, 원형·타원·연구용 CA를 연결했다.
- 화면을 재생하지 않는 서버 CCTV 분석, 불꽃·연기 후보 알람, 선택 HLS 재생, 카메라 제거·복원, 세션 장애 복구를 구현했다.
- 최신 실제 4대·2분 시험은 48프레임·오류 0회다. 이전 1시간 시험에 403 문제가 있어 장시간 안정성은 미확정이다.
- 2026-10-10 업로드 전 재검사: 백엔드 92개·프론트 31개·학습 코드 35개 통과, 프론트 빌드 성공. 라이브 CCTV 수집이나 새 학습은 실행하지 않았다.
- 실카메라 자동 위치·확산은 OFF다. UTIC 연동, 실제 산불 정확도, 대피 경로, 수천 대 운영, Docker/AWS 배포는 미완료다.

이 아카이브가 예전 README·검증 문서의 시점별 상태를 설명하는 최신 진입점이다. 기존 문서는 과거 증거로 보존한다. [현재 카메라 사용법](../CCTV_CAMERA_WORKFLOW.md), [실행·설치](../GITHUB_SETUP.md)를 함께 읽는다.
