# Docker / AWS 배포 안내

현재 AWS 배포나 클라우드 자원 생성은 하지 않았습니다. Docker CLI는 설치되어 있지만 작업 당시 Docker Desktop Linux 엔진이 실행되지 않아 이미지 build/compose 실행은 검증하지 못했습니다.

## 로컬 Docker

1. Docker Desktop에서 Linux 엔진을 켭니다.
2. 프로젝트 `.env.example`을 `.env`로 복사한 후, `POSTGRES_PASSWORD`와 `EMBER_ADMIN_PASSWORD`를 별도로 설정합니다. URL에 사용하는 DB 비밀번호는 URL-safe 문자를 사용하세요.
3. Docker용 Origin은 `EMBER_PUBLIC_ORIGIN=http://localhost:8080`으로 변경합니다. 로컬 8080은 개발 모드/비보안 쿠키이며 휴대폰 HTTPS 주소가 아닙니다.
4. `models/best.pt`와 대응하는 설정을 확인합니다.

```powershell
Set-Location "D:\fire-dettection"
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose logs api
```

8080은 PC loopback에만 공개됩니다. DB와 API 포트는 외부에 공개하지 않습니다. 데이터는 PostgreSQL/evidence 볼륨에 보존됩니다. **`docker compose down -v`는 데이터를 삭제하므로 일반 종료에 사용하지 마세요.** 종료는 `docker compose stop`을 사용하세요.

Alembic 초기 스키마가 API 시작 전에 적용됩니다. 새 코드 배포 때 스키마 마이그레이션은 백업·스테이징 검증 후 수행하세요. 모델 파일은 이미지에 임베딩하지 않고 읽기 전용 mount로 전달합니다. 환경별 CPU wheel/버전 호환성도 실제 이미지 build에서 확인해야 합니다.

## AWS 권장 초기 구성

- ECR: web/API 컨테이너 저장.
- ECS: API desired count 1, workers 1. 초기 CPU 처리량 측정 후 크기 결정.
- ALB + ACM + 소유 도메인: HTTPS, WebSocket 경로 포함. 운영 Origin과 정확하게 일치.
- RDS PostgreSQL: private subnet, 암호 Secrets Manager, 백업/복구 정책.
- S3: private evidence bucket, 암호화·보존 정책, API task role로만 접근.
- CloudWatch: 로그·모델 ready·오프라인 카메라·증거 저장 실패·지연 감시.
- 현재 Nginx는 compose의 `api` DNS에 proxy합니다. ECS 분리 서비스로 배포할 때 실제 서비스 디스커버리 주소로 바꾸거나 같은 task의 localhost 주소를 사용하세요.
- ALB의 최소 health endpoint는 `/health/ready`입니다. Host 검사는 health 경로에만 예외를 두었습니다.

운영 필수 환경 변수:

```text
EMBER_ENVIRONMENT=production
EMBER_ADMIN_PASSWORD=<16자 이상 별도 비밀>
EMBER_DATABASE_URL=postgresql+psycopg://<RDS 연결 정보>
EMBER_PUBLIC_ORIGIN=https://<소유 도메인>
EMBER_SECURE_COOKIE=true
EMBER_DEMO_ENABLED=false
EMBER_STORAGE_BACKEND=s3
EMBER_S3_BUCKET=<private bucket>
EMBER_MODEL_PATH=<검증한 모델 mount 경로>
EMBER_POLICY_PATH=<대응 설정 mount 경로>
```

production 설정은 기본 비밀번호·HTTP·비보안 쿠키·SQLite·예제 활성화를 거부합니다. 그러나 운영 설정 검사가 권한/장애/성능/AI 안전성 검증을 대체하지는 않습니다.

초기 계정 비밀번호는 DB에 해시로 생성됩니다. **환경 변수만 바꿔도 이미 존재하는 계정의 비밀번호가 바뀌지는 않습니다.** 기존 개발 DB를 그대로 외부 공개하지 마세요. 운영 DB는 새로 bootstrap하거나 검토된 계정 관리 절차를 먼저 추가하세요.

고가용성은 현재 구현하지 않았습니다. replica/worker를 증가시키기 전에 공유 temporal state/알람 deduplication/fan-out/속도 제한을 구현해야 합니다. AWS 요금, 리전, 도메인, 인증서, 계정/IAM 선택은 사용자가 이후 승인·설정해야 하며 이번 작업에서 비용을 발생시키지 않았습니다.

참고: [FastAPI lifespan 모델 로드](https://fastapi.tiangolo.com/advanced/events/), [ECS load balancing](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-load-balancing.html).
