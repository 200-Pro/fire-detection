# 근거·산출물 목록과 공개 범위

## 원본 대화와 정리 범위

현재 Codex 대화 제목은 'Find direction for week 2 project', ID는 `01a0806f-d725-7751-a562-09eefe77d39d`다. 2026-09-08 첫 방향 확인부터 10-10 실행 안내까지, 이번 정리 요청 이전의 **사용자 179건·최종 답변 129건·진행 안내 182건, 총 490건**을 시간순으로 정제했다.

비공개 Notion 부록은 보이는 메시지의 정제 텍스트다. 비밀번호·실제 .env 값·서명 URL query·도구 원문·내부 추론은 제외한다. 원래 첨부 이미지는 파일명·대화 설명만 남기고 모든 사진을 재배포하지 않는다. 과거 완료 주장은 당시 기록으로 남기고 최신 검증·한계 문서와 함께 읽는다.

제목이 비슷한 보고서·PBL 대화도 확인했지만 센서·로봇 내용이어서 합치지 않았다. 삭제되거나 접근할 수 없는 다른 대화까지 복구했다고 주장하지 않는다. 원문은 7개 Markdown 첨부로 나눴고 129개 최종 답변 색인을 추가했다.

## 최초 기획·설계 문서

공유 Drive 프로젝트 루트 기준:

- `실행 가이드/산불_CCTV_AI_프로젝트_1-6주차_상세실행계획.pdf`
- `실행 가이드/산불프로젝트_초보자용_핵심추천안.pdf`
- `실행 가이드/산불_CCTV_AI_탐지_확산예측_통합서비스_실행가이드.pdf`: 기준일 09-02, 25쪽. 이번에 전체 텍스트 확인.
- `주차 보고서/3주차/산불 예측 서비스 기획안 및 요구사항 정의서.docx`·PDF.
- `주차 보고서/3주차/산불 예측 서비스 시스템 설계서.docx`·PDF. 이번에 두 DOCX 내용을 대조.
- `지원서/진로 탐색 수행계획서 컴퓨터학부 22학번 백종원.pdf`: 학교 계획의 근거 목록이며 이번에 내용 전체를 새로 검증하지는 않음.

초기 대화의 `백종원` 폴더 문서는 현재 실행 가이드·주차 보고서로 정리돼 있다. 옛 첨부 경로와 현재 존재 경로를 무조건 같다고 보지 않는다.

## 학습 저장소 산출물

[200-Pro/fire-ai](https://github.com/200-Pro/fire-ai):

- 환경·팀: README, TEAM_SETUP, MANUAL_NEXT_STEPS, PROJECT_STATUS, setup_local, verify_environment, requirements·lock, data_registry.
- 데이터: prepare_dfire, audit_training_inputs, label_guide_v1.0, PRETRAINING_CHECKS.
- 학습: MODEL_DECISION, TRAINING_READY, train_yolo11n_v1, prepare_pretrained, training_workflow, requirements-colab.
- 노트북: dfire_colab_pipeline(초기 YOLO26), dfire_team_training(YOLO11 본 학습), dfire_fire_miss_analysis.
- 분석·후처리: FIRE_MISS_ANALYSIS, FIRE_POLICY_USAGE, analyze_fire_misses, review_saved_fire_analysis, fire_policy, infer_fire_frame, infer_media, tune_fire_policy, compare_fire_resolution, audit_policy_changes.
- 결과 텍스트: fire_miss_review_20261005_v1의 REPORT·PHOTO_REVIEW·audit JSON, fire_policy_result_20261005의 REPORT·comparison·box_changes·policy JSON, 프로파일별 tuning JSON.
- 회귀: test_prepare_dfire, test_training_workflow, test_evaluation, test_fire_misses, test_fire_policy·fixture. 실제 데이터 검사는 check_real_validation.

실험 사진은 로컬·Drive에 보존하고 공개 업로드에는 넣지 않는다. 과거 보고서의 사진 상대 링크는 GitHub에서 열리지 않을 수 있다. 공개 범위를 최신 학습 인수인계에 명시한다.

## 비공개 학습 artifact

Drive `Data/DFire/training_results`:

- `yolo26n_smoke_test_3ep`: 3epoch 시험.
- `yolo11n_v1/jongwon_20260930T144603Z_51fb455c`: 69 완료·70 도중 중단.
- `yolo11n_v1/jongwon_to70_20261004T144737Z_9154ce3d`: 70 완료·validated 선정 실행.
- 재개 실행의 `analysis/fire_fn_val_20261004T151828Z_23484307`: 미탐 분석.

실제 pt·results.csv·args/run/environment·split/dataset manifest·라벨 정리 로그·checkpoint 완료 manifest·val/test JSON을 보존한다. 대용량 원본·가중치는 소스 Git에 넣지 않는다.

## 서비스 저장소 산출물

[200-Pro/fire-detection](https://github.com/200-Pro/fire-detection):

- backend(app·migrations·tests), frontend(src·tests), infra, compose, scripts, .env.example, README.
- 기본 문서: ARCHITECTURE, DESIGN_SYSTEM, DEPLOYMENT, GITHUB_SETUP, PHONE_TEST, TEAM_DEMO, VERIFICATION.
- 확산: SPREAD_GUIDE, SPREAD_EXPERIMENTS.
- 지도·감시: MAPS_CCTV, CCTV_MONITORING, MONITOR_VERIFICATION, CCTV_SOAK_TEST, CCTV_CAMERA_WORKFLOW.
- 새 history: 01~08 기술 이력·최신 README·다음 작업 인수인계.

초기 공개 commit은 `84192e163b908c9387965cfe2ee51dd81322820d`(10-09)이다. 이후 카메라·연기·세션·시험 변경과 이번 문서를 새 commit으로 게시한다. 정확한 업로드 SHA는 Notion 최상위 완료 상태에 기록한다.

## 보고서·화면 자료

- `주차 보고서/4주차/YOLO_학습_고도화_중간보고_20261007.docx`, 학습 보고서 PDF, 사진 합본 PDF.
- `주차 보고서/4주차/실제 화재 탐지 사진.png`, `테스트 화재 탐지 사진.png`, `화재_탐지_사진_합본.pdf`: 2사진·2쪽 합본.
- `주차 보고서/5주차/5주차 진로탐색 공원 화재 경로 분석 사진.pdf`.
- `주차 보고서/6주차/CCTV 관제 및 화재 감지 사진.pdf`.
- 서비스 `docs/reports/YOLO_학습_고도화_중간보고_20261007.docx/pdf`: 생성 당시 기록. 현재 배치는 Drive에서 확인.
- 서비스 runtime/public의 demo·map·spread·UI 사진, 10-10 temp의 CCTV 재생 검증 사진.

사진·보고서는 보정된 화재 확률·실시간 위성·실제 확산 정확도를 입증하지 않는다. 지도 타일·원본 공공 영상·개인정보 포함 이미지의 별도 공개 권한 없이 소스 repo에 넣지 않는다.

## 비공개 운영 파일

- `D:\fire-dettection\.env`: 실제 키·환경 설정.
- `runtime/ember.db`: 실제 계정·세션·카메라·알람.
- `runtime/evidence`, `trial_evidence_expiry`: 알람 JPEG·보존 기록.
- `runtime/external-data`, `spread-data`, `spread-jobs`: GIS 원본·전처리·작업 결과.
- `runtime/cctv-check-20261010.json`: 짧은 실제 연결 시험.
- `runtime/cctv-fix-backup-20261010/ember.db` 및 soak·monitor 백업: 인증정보가 있어 공개 금지.

## 이번 공개 업로드 기준

소스·테스트·설정 예시·기술 문서·비밀 없는 실험 집계만 올린다. 실제 키·DB·백업·서명 URL·이미지·영상·ZIP·pt·GIS 원본은 제외한다. 노트북의 출력과 기본 실행 스위치도 검토한다. 사용자 변경사항은 삭제하지 않고 diff로 확인해 보존한다.

Notion은 비공개 draft 루트에 두며 외부 공개·팀 space 이동을 대신 수행하지 않는다. 전체 대화 정제 부록은 공개 Git에 넣지 않는다. 원문은 과거 표현·오류를 보존하므로 최신 결정 이력과 함께 읽는다.
