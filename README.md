# FruitPriceOptimizer

Docker와 PostgreSQL로 실행하는 상품 가격 수집·비교 시스템입니다. 관리 화면에서 상품과 쇼핑몰을 등록하고, 즉시 또는 cron 일정에 따라 Playwright가 로그인 후 옵션별 가격을 수집합니다.

## 설계 결정

사이트에는 **도메인과 상품 목록 URL을 모두** 등록합니다.

- 도메인: SSRF 방지용 접근 범위, 로그인 URL 검증. 보안을 위해 상품 목록 URL과 **완전히 같은 호스트명**만 허용
- 상품 목록 URL: 최초 상품 페이지 자동 조사 시작점
- 상품 상세 페이지: 반복 수집에 사용하는 안정적인 URL
- CSS 선택자: 옵션 행·옵션명·가격을 사이트별 DOM에 맞게 지정

자동 조사는 목록 페이지의 `<a href>` 중 상품명/검색어가 포함된 링크를 후보로 저장합니다. 링크가 없는 SPA 카드나 모달형 상품은 관리자 화면에서 상품 상세 URL과 선택자를 직접 등록해야 합니다. 사이트 구조가 자주 바뀌면 전용 어댑터를 추가하는 편이 안전합니다.

## 구성

- `web`: FastAPI + Jinja 관리 화면
- `worker`: PostgreSQL 큐에서 작업을 가져와 Playwright로 수집
- `scheduler`: cron 일정이 도래하면 비교 작업을 큐에 등록
- `db`: PostgreSQL 16

Redis 없이 PostgreSQL의 `FOR UPDATE SKIP LOCKED`를 작업 큐로 사용합니다.

## 보안

- 애플리케이션 비밀번호: Argon2 해시
- 외부 사이트 아이디/비밀번호: Fernet 대칭 암호화
- 암호화 키, DB 비밀번호, 초기 관리자 비밀번호: Git 제외 대상 `.env`
- 사이트·자격증명·사용자 관리: `admin` 역할만 접근
- 저장된 외부 사이트 비밀번호는 화면/API에 평문으로 반환하지 않음
- 모든 변경 폼: CSRF 토큰 검증
- 세션 쿠키: `SameSite=Strict`, 운영 HTTPS에서는 `SECURE_COOKIES=true`
- 수집 URL: 등록 도메인 제한 및 localhost/비공개 IP 차단
- 자격증명 로그인: HTTPS만 허용하고 최종 리다이렉트·폼 전송 대상 도메인 재검증
- 크롤러 네트워크: 공인 IPv4에 DNS pinning, exact-host HTTP/WSS allowlist, 서비스 워커·WebRTC·WebTransport·DNS prefetch 차단
- 관리자 변경 행위: `audit_logs` 기록

`.env`와 `CREDENTIAL_KEY`를 잃으면 저장된 사이트 자격증명을 복호화할 수 없습니다. 키는 별도 비밀 저장소에 백업하십시오.

## 실행

이 저장소에는 Git에서 제외된 `.env`가 이미 생성되어 있습니다.

```bash
docker compose up --build -d
docker compose ps
```

관리 화면: <http://127.0.0.1:8000>

초기 관리자 아이디는 `.env`의 `ADMIN_USERNAME`, 비밀번호는 `ADMIN_PASSWORD`입니다. 최초 로그인 후 운영 환경에서는 비밀번호 변경 기능 또는 별도 관리자 계정 생성 정책을 추가하는 것을 권장합니다.

중지:

```bash
docker compose down
```

DB 데이터까지 삭제:

```bash
docker compose down -v
```

## 사용 순서

1. 관리자 로그인
2. **사이트·자격증명**에서 도메인, 목록 URL, 로그인 URL/선택자, 로그인 정보를 등록
3. 대시보드에서 비교 상품과 쉼표 구분 검색어 등록
4. 상품 화면에서 **상품 페이지 자동 조사** 실행
5. 발견된 후보를 열어 DOM을 확인한 뒤 상품 페이지와 CSS 선택자 등록
6. **지금 가격 비교** 또는 cron 스케줄 등록
7. 상품 화면의 가격 이력에서 사이트·옵션별 가격 확인

CSS 선택자 예시:

```text
옵션 행: .option-row
옵션명:  .option-name
가격:    .option-price
```

모달을 먼저 열어야 하면 `추출 전 클릭 선택자`에 상세보기 버튼 선택자를 넣습니다.

## 테스트

호스트:

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

컨테이너:

```bash
docker compose run --rm web pytest -q
```

## 운영 전에 추가로 고려할 사항

- 사이트별 이용약관·robots 정책과 자동 수집 허용 여부
- CAPTCHA/2FA: 자동화 우회 대신 수동 세션 갱신 또는 공식 API 사용
- DOM 변경 감지와 관리자 알림
- 가격 단위·배송비·세금·중량 정규화
- 동일 옵션 매칭 규칙(예: `2kg 3수`와 `2kg 2~4수`)
- 실패 재시도·지수 백오프·사이트별 호출 속도 제한
- 알림 채널(이메일, Slack, Telegram)
- PostgreSQL 백업 및 Fernet 키 외부 보관
- HTTPS 리버스 프록시와 `SECURE_COOKIES=true`
- 다중 인스턴스 운영 시 Alembic 기반 스키마 마이그레이션
- 로그인 시도 제한·계정 잠금 정책
- worker 장애 시 `running` 작업을 회수하는 lease/heartbeat와 재시도·지수 백오프
- 동일 상품·스케줄 작업의 idempotency key 및 중복 실행 방지 제약조건
- worker 컨테이너의 read-only filesystem, capability drop, `no-new-privileges`, CPU/메모리 제한
- CSP, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` 보안 헤더
- web/worker/scheduler 각각의 readiness, 구조화 로그, 큐 지연·실패율 메트릭

현재 구현은 로컬 단일 호스트 MVP에 맞춰져 있습니다. 외부 네트워크에 공개하거나 다중 worker로 확장하기 전에는 위 항목을 운영 필수 작업으로 처리해야 합니다.


## 실행화면
<img width="888" height="267" alt="스크린샷 2026-08-26 오전 2 38 20" src="https://github.com/user-attachments/assets/bec49345-57c8-4203-828f-9392e1b1dd6b" />
<img width="1103" height="914" alt="스크린샷 2026-08-26 오전 2 38 12" src="https://github.com/user-attachments/assets/004e379f-5f78-4121-8769-fb97546d648e" />
