# GitHub 소스 공개 및 팀원 실행 안내

학습 프로젝트 `200-Pro/fire-ai`와 별도로, 서비스 코드는 `200-Pro/fire-detection`에 공개합니다. 로컬 작업 폴더 이름은 기존 `D:\fire-dettection`을 유지합니다. GitHub 업로드는 서비스 배포가 아니며, GitHub 주소에서 관제 서버가 자동 실행되지 않습니다.

## 포함 / 미포함

포함: FastAPI 백엔드, React 프론트, 테스트, 마이그레이션, Docker 구성, 운영 스크립트, 설명 문서, 모델 후처리 정책 JSON.

미포함: 실제 `.env`와 인증키, DB/사용자 계정, CCTV 증거 이미지/원본 영상, 로컬 인증서, runtime 백업, 가상환경, node_modules, GIS 원본, API 참고문서/캡처, 보고서 바이너리, `best.pt`, D-Fire 예제 이미지. 제외는 `.gitignore` 기준이며 기존 파일은 PC에서 삭제하지 않습니다.

모델과 데이터는 공개 재배포 권한을 검토하지 않았으므로 이 저장소로 배포하지 않습니다. 팀에서 허용된 별도 경로로 전달해야 합니다. 의존 패키지/모델/지도/API 제공자의 라이선스와 이용 조건도 별도로 적용됩니다.

## 새 PC에서 실행

1. Git, Python 3.12, Node.js/npm을 준비하고 저장소를 내려받습니다.

```powershell
git clone https://github.com/200-Pro/fire-detection.git D:\fire-dettection
Set-Location D:\fire-dettection
& .\scripts\setup-local.ps1
Copy-Item .env.example .env
```

이미 해당 폴더가 있는 PC에서는 덮어쓰지 말고 다른 빈 경로로 clone 하세요. 스크립트는 프로젝트 경로를 기준으로 실행합니다. 기존 문서의 PC별 IP/경로/시험 시각은 원래 개발 PC 기록이지 새 PC 설정값이 아닙니다.

2. 팀에서 전달받은 학습 모델을 `models/best.pt`에 놓습니다. 현재 `models/fire_policy_v1.json`은 특정 모델 SHA256에 연결됩니다. 다른 모델을 넣으면 정책도 함께 검증·교체해야 하며, 파일 이름만 바꿔서는 호환이 보장되지 않습니다.
3. 예제 테스트가 필요하면 허용된 D-Fire 이미지 사본을 `samples/fire.jpg`, `samples/clear.jpg`로 준비합니다. 준비하지 않았다면 `.env`의 `EMBER_DEMO_ENABLED=false`로 설정합니다.
4. `.env`에 본인 환경의 강한 초기 관리자 비밀번호 및 필요한 API 키를 입력합니다. 최초 계정 생성 후에는 `.env` 변경만으로 기존 비밀번호가 바뀌지 않습니다. 키/비밀번호를 GitHub, 채팅, `VITE_` 변수에 올리지 마세요.
5. `& .\scripts\start-local.ps1` 실행 후 `http://localhost:5173/`에 접속합니다. 휴대폰 카메라 연결은 별도 HTTPS/인증서 설정이 필요합니다: [PHONE_TEST.md](PHONE_TEST.md).
6. 확산 기능에는 별도 GIS 전처리 데이터가 필요합니다: [SPREAD_GUIDE.md](SPREAD_GUIDE.md). 공공 CCTV 상시 분석은 기관 허용 범위와 정확한 호스트를 확인한 후 서버/개별 카메라 설정에서 활성화합니다. `.env.example`은 기본 OFF입니다.

## 현재 검증 경계

- 기존 개발 PC에서 전체 백엔드 83개·프론트 22개 테스트 통과, 프론트 빌드 성공. 모델/데이터를 제외한 새 clone에서 전체 기능을 검증했다는 뜻은 아닙니다.
- ITS 실제 4대 시험은 추론 성공 후 403 오류가 반복되어 장시간 안정성 미해결입니다.
- 카메라 관리 카드는 연속 플레이어가 아니라 최근 분석 이미지이며 12초 만료 동작이 있습니다. 카드 클릭 시 실시간 플레이어 연결은 아직 없습니다.
- 자동 발화점/확산은 실제 카메라 보정 없이 켜지 않으며 연구용 결과를 실제 화재 경로로 확정하지 않습니다.
- 수천 대 분산 분석, AWS 실서비스 배포, UTIC 연결은 완료된 기능이 아닙니다.

## 이후 업로드

```powershell
git status --short
git add <변경한-소스파일>
git diff --cached
git commit -m "Describe the change"
git push
```

공개 저장소에는 모든 사람이 접근할 수 있습니다. `.gitignore`는 이미 추적된 파일에서 비밀을 제거하지 않으므로 매번 diff를 검토하세요. 잘못 올린 키는 파일 삭제만으로 안전해지지 않으며 즉시 제공기관에서 폐기/재발급해야 합니다.
