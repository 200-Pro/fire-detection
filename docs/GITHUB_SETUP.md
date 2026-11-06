# GitHub 소스 공개 및 팀원 실행 안내

학습 프로젝트 `200-Pro/fire-ai`와 별도로, 서비스 코드는 `200-Pro/fire-detection`에 공개합니다. 로컬 작업 폴더 이름은 기존 `D:\fire-dettection`을 유지합니다. GitHub 업로드는 서비스 배포가 아니며, GitHub 주소에서 관제 서버가 자동 실행되지 않습니다.

## 포함 / 미포함

포함: FastAPI 백엔드, React 프론트, 테스트, 마이그레이션, Docker 구성, 운영 스크립트, 설명 문서, 모델 후처리 정책 JSON.

미포함: 실제 `.env`와 인증키, DB/사용자 계정, CCTV 증거 이미지/원본 영상, 로컬 인증서, runtime 백업, 가상환경, node_modules, GIS 원본, API 참고문서/캡처, 보고서 바이너리, `best.pt`, D-Fire 예제 이미지. 제외는 `.gitignore` 기준이며 기존 파일은 PC에서 삭제하지 않습니다.

모델과 데이터는 공개 재배포 권한을 검토하지 않았으므로 이 저장소로 배포하지 않습니다. 팀에서 허용된 별도 경로로 전달해야 합니다. 의존 패키지/모델/지도/API 제공자의 라이선스와 이용 조건도 별도로 적용됩니다.

## 새 PC에서 실행

1. Windows 64비트에서 Git, Python 3.12(Windows Python Launcher 포함), Node.js/npm을 준비하고 저장소를 내려받습니다. 기존 개발 PC의 검증 버전은 Python 3.12.10, Node 24.18.0, npm 11.16.0입니다. OS·설치 프로그램·네트워크가 다른 새 PC에서 패키지 전체를 새로 설치한 검증은 아직 하지 않았습니다. Node는 Vite의 실행 조건(^20.19.0 또는 >=22.12.0)을 만족해야 합니다. 가상환경과 node_modules는 복사하지 않고 해당 PC에서 설치합니다.

```powershell
git clone https://github.com/200-Pro/fire-detection.git D:\fire-dettection
Set-Location D:\fire-dettection
& .\scripts\setup-local.ps1
Copy-Item .env.example .env
```

D: 드라이브가 없으면 `C:\Projects\fire-detection` 같은 빈 경로를 사용해도 됩니다. 이후 명령은 내려받은 프로젝트 폴더에서 실행하세요. 실행정책 오류가 있을 때만 `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`를 해당 PowerShell 터미널에서 실행합니다. `.env`가 이미 있으면 Copy-Item으로 덮어쓰지 않습니다.

이미 해당 폴더가 있는 PC에서는 덮어쓰지 말고 다른 빈 경로로 clone 하세요. 스크립트는 프로젝트 경로를 기준으로 실행합니다. 기존 문서의 PC별 IP/경로/시험 시각은 원래 개발 PC 기록이지 새 PC 설정값이 아닙니다.

2. 팀에서 전달받은 학습 모델을 `models/best.pt`에 놓습니다. 현재 기본 정책은 `models/fire_policy_v2.json`이며 v1은 되돌리기용입니다. 두 정책은 동일한 검증 모델 SHA256 `57c133a489976dc2f7341381b12cf160622e0bbaff33aeffdee4926e2093611d`에 연결됩니다. 다른 모델을 넣으면 정책도 함께 검증·교체해야 하며, 파일 이름만 바꿔서는 호환이 보장되지 않습니다.
3. 예제 테스트가 필요하면 허용된 D-Fire 이미지 사본을 `samples/fire.jpg`, `samples/clear.jpg`로 준비합니다. 준비하지 않았다면 `.env`의 `EMBER_DEMO_ENABLED=false`로 설정합니다.
4. `.env`에 본인 환경의 강한 초기 관리자 비밀번호 및 필요한 API 키를 입력합니다. 최초 계정 생성 후에는 `.env` 변경만으로 기존 비밀번호가 바뀌지 않습니다. 키/비밀번호를 GitHub, 채팅, `VITE_` 변수에 올리지 마세요.
5. 다음 사전 점검을 통과한 뒤 `& .\scripts\start-local.ps1`로 시작하고 `http://localhost:5173/`에 접속합니다. 시작 스크립트도 동일한 검사를 수행합니다. `error`는 필수 항목 누락, `optional_missing`은 해당 선택 기능 준비가 필요하다는 뜻입니다. 값이 설정됐다는 검사는 API 키의 유효성이나 등록 IP 승인을 확인하지 않습니다.

```powershell
& .\.venv\Scripts\python.exe .\scripts\check-local.py
# 확산·UTIC까지 준비할 때:
& .\.venv\Scripts\python.exe .\scripts\check-local.py --require-spread --require-utic
```

휴대폰 카메라 연결은 별도 HTTPS/인증서 설정이 필요합니다: [PHONE_TEST.md](PHONE_TEST.md). 기존 PC의 LAN IP·Caddy 인증서를 그대로 재사용하지 마세요.
6. 확산 기능에는 별도 GIS 전처리 데이터가 필요합니다: [SPREAD_GUIDE.md](SPREAD_GUIDE.md). 공공 CCTV 상시 분석은 기관 허용 범위와 정확한 호스트를 확인한 후 서버/개별 카메라 설정에서 활성화합니다. `.env.example`은 기본 OFF입니다.

## 기능별 별도 전달 자료

현재 PC에서 아래 파일을 권한 있는 팀원에게 비공개로 전달합니다. 공개 저장소·공개 이슈에 첨부하지 않습니다. 모델과 전처리 GIS만 복사해도 기본 탐지와 연구 확산을 사용할 수 있으며 D-Fire 전체 학습 ZIP은 서비스 실행에 필요하지 않습니다.

| 기능 | 새 PC의 경로 | 추가 설정 |
| --- | --- | --- |
| 실제 탐지 | `models/best.pt` | 모델·정책 SHA 일치 필수 |
| 예제 버튼 | `samples/fire.jpg`, `samples/clear.jpg` | 없으면 `.env`의 `EMBER_DEMO_ENABLED=false` |
| 연구용 확산 | `runtime/spread-data/` 전체 | `manifest.json`, `grid.npz`, `forest.geojson`, `terrain.geojson` 4개를 한 묶음으로 전달. 사전 점검은 grid SHA 확인 |
| GIS 재전처리·원본 7개 무결성 재검사 | `runtime/external-data/`의 기존 DEM·임상도·토양도 | 전처리 결과만으로는 `check-spread.py`의 원본 hash 검사까지 통과하지 않음 |
| UTIC 목록·선택 재생 | `runtime/external-data/cctv/OpenDataCCTV.xlsx` | 서버 `UTIC_API_KEY`, 새 출발지 공인 IP의 승인 조건 확인 |
| 기상·위험·ITS | 새 PC `.env`에 해당 API 키 | 제공기관 등록·허용 조건, 접속 IP 확인 |
| Naver 지도·주소 | 새 PC `.env`의 Client ID/Secret | 새 접속 origin을 Naver Web URL에 등록. Secret은 서버 전용 |

기존 `.env`를 전달할 때 PC별 절대경로, `EMBER_PUBLIC_ORIGIN`, 데이터베이스 URL, 저장소 설정을 새 경로에 맞춥니다. 오래된 v1 `EMBER_POLICY_PATH` override가 있으면 현재 v2 기본값을 쓰도록 제거하거나 명시적으로 v2로 고칩니다. 값을 노출하지 않는 사전 점검으로 확인하세요.

새 PC는 처음 시작할 때 `.env`의 `EMBER_ADMIN_NAME`·`EMBER_ADMIN_PASSWORD`로 새 관리자와 DB를 만듭니다. 기존 PC의 계정·카메라·알람은 자동으로 따라오지 않습니다. 기존 운영 DB의 복사는 이 안내의 범위가 아니며, 서버를 정지한 일관된 DB·증거·작업 백업과 복구 검증이 필요합니다. 새 CCTV 연결은 재등록합니다.

## 설치 후 확인 순서

1. 사전 점검의 필수 항목 성공 → 시작 명령 → `http://127.0.0.1:8000/health/ready`의 ready=true.
2. 웹 로그인 → 허용된 예제/이미지 추론 → 카메라·알람 표시 확인.
3. 기상·위험·Naver 주소 API와 실제 지도 표시를 각각 확인.
4. UTIC 목록 → 한 대 선택 → 최대 60초 재생 또는 서버 1프레임 확인. 이는 상시 AI 분석과 별개입니다.
5. 확산은 수동 발화점·가상 기상부터 확인하고 실제 기상으로 비교합니다. 실제 자동 발화점은 보정 자료 없이 켜지 않습니다.
6. ITS 상시 감시는 등록 IP·이용 조건을 확인한 뒤 1대부터 시간제 시험합니다. 다른 PC로 옮긴 사실만으로 장시간 403이 해결되지는 않습니다.

Docker Compose에도 v2 정책과 UTIC 설정을 맞췄지만, 현재 자료는 로컬 Windows 실행 검증이 중심입니다. Docker/AWS 전체 구동이 검증됐다고 해석하지 마세요.

## 현재 검증 경계

- 2026-11-06 기존 개발 PC에서 백엔드 116개·프론트 35개 테스트 통과, 프론트 빌드 성공. 모델/자료 없는 새 PC에서 모든 기능을 새로 검증했다는 뜻은 아닙니다.
- ITS 실제 4대 시험은 추론 성공 후 403 오류가 반복되어 장시간 안정성 미해결입니다.
- 카메라 카드의 최근 분석 이미지와 선택 HLS 플레이어를 구분합니다. 카메라 제거·복원 기능은 구현돼 있습니다. 네이버 지도 공급자 전환 시 실제 빈 화면 오류의 최종 브라우저 재검증은 남아 있습니다.
- 자동 발화점/확산은 실제 카메라 보정 없이 켜지 않으며 연구용 결과를 실제 화재 경로로 확정하지 않습니다.
- UTIC는 대구 목록·선택 재생·서버 1프레임 수신 단계이며 상시 AI·알람·증거 저장은 OFF입니다. 수천 대 분산 분석·AWS 운영·현장 정확도는 미검증입니다. 상세 최신 기록은 [PERFORMANCE_20261031.md](PERFORMANCE_20261031.md)를 확인하세요.

## 이후 업로드

```powershell
git status --short
git add <변경한-소스파일>
git diff --cached
git commit -m "Describe the change"
git push
```

공개 저장소에는 모든 사람이 접근할 수 있습니다. `.gitignore`는 이미 추적된 파일에서 비밀을 제거하지 않으므로 매번 diff를 검토하세요. 잘못 올린 키는 파일 삭제만으로 안전해지지 않으며 즉시 제공기관에서 폐기/재발급해야 합니다.
