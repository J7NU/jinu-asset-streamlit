# jinu-asset-streamlit — Phase 4 v1 lean draft

> D-047 (2026-05-16) 자산배분 시스템 정체성 변경 — Streamlit + Supabase + 매직링크.
> 본 디렉토리는 **jinu-co 내 임시 작업본**. 진우 본인이 신규 public repo
> `https://github.com/J7NU/jinu-asset-streamlit` 으로 4 파일을 복사한다.

---

## v1 lean 범위

- ✅ 매직링크 인증 (OTP)
- ✅ Dashboard: 총 평가액·매수원가·수익률 KPI + 카테고리별 평가액 차트 + 종목별 보유 테이블
- ✅ Transactions 입력 form (buy/sell/rebalance + 검증 + 즉시 반영)
- ⏳ v2 후속: Dividends form / Monthly Log / 시계열 가치 추이 차트 / 카테고리 비중 도넛

---

## 진우 본인 액션 — jinu-co → jinu-asset-streamlit 복사 (5분)

신규 repo `J7NU/jinu-asset-streamlit`가 비어 있는 상태 가정. GitHub 웹에서 4 파일 복사.

### Step 1. requirements.txt (1분)
1. https://github.com/J7NU/jinu-asset-streamlit → `Add file > Create new file`
2. 파일명: `requirements.txt`
3. 내용 = 본 디렉토리 `requirements.txt` 내용 전체 복사·붙여넣기
4. "Commit changes" → `init: requirements`

### Step 2. .streamlit/secrets.toml.example (1분)
1. 같은 방식으로 `Add file > Create new file`
2. 파일명: `.streamlit/secrets.toml.example` (앞에 `.streamlit/` 그대로 입력 시 GitHub이 자동으로 하위 폴더 생성)
3. 내용 = 본 디렉토리 `.streamlit/secrets.toml.example` 전체 복사
4. 커밋

### Step 3. .gitignore (1분)
1. `Add file > Create new file`
2. 파일명: `.gitignore`
3. 내용 = 본 디렉토리 `.gitignore` 전체 복사
4. 커밋

### Step 4. app.py (2분)
1. `Add file > Create new file`
2. 파일명: `app.py`
3. 내용 = 본 디렉토리 `app.py` 전체 복사 (긴 파일, 정상)
4. "Commit changes" → `feat: Phase 4 v1 lean (Auth + Dashboard + Transactions)`

---

## Streamlit Cloud 배포 (Phase 5-C, 진우 본인 3분)

1. https://share.streamlit.io → `Sign in with GitHub` (J7NU)
2. `New app` → Repository: `J7NU/jinu-asset-streamlit` / Branch: `main` / Main file: `app.py`
3. **Advanced settings → Secrets** 에 아래 paste (실값으로 교체):

```toml
SUPABASE_URL = "https://<your-ref>.supabase.co"
SUPABASE_ANON_KEY = "<your-anon-key>"
SITE_URL = "https://<your-app>.streamlit.app"
```

- Supabase Dashboard > Settings > API 에서 `Project URL`, `anon public key` 복사
- `SITE_URL` = Streamlit Cloud에서 발급한 본인 앱 도메인 (Supabase Authentication > URL Configuration의 Site URL과 동일 값). PKCE flow에서 매직링크 `email_redirect_to` 목적지로 사용
- Service Role key 절대 paste 금지 (§N 안전 룰 — 파괴적 명령·외부 발송·비밀 commit 금지 + Phase 6 백업 Action GitHub Secrets 전용 분리)

4. `Deploy` → 2분 빌드 후 `*.streamlit.app` 도메인 발급
5. 발급된 도메인 = 매직링크 redirect URL. **이어서 Supabase 설정 1건 필요** ↓

---

## Supabase 매직링크 redirect URL 등록 (진우 본인 1분)

Streamlit Cloud 도메인을 Supabase Auth에 등록해야 매직링크 redirect 후 세션 복원이 작동한다.

1. Supabase Dashboard > **Authentication** > **URL Configuration**
2. **Site URL**: `https://<your-app>.streamlit.app` 입력
3. **Redirect URLs**에도 같은 URL 추가 (`*.streamlit.app/**` 와일드카드도 가능)
4. Save

---

## 첫 사용 흐름 (진우 본인 2분)

1. `https://<your-app>.streamlit.app` 접속
2. 이메일 입력 → "매직링크 발송"
3. 이메일에서 링크 클릭 → 같은 브라우저로 돌아오면 자동 로그인
4. 사이드바 "Transactions" → 첫 매수 기록 입력 (예: KODEX_200TR_PENSION 100주 × 12,000원)
5. "Dashboard" → 종목별 보유 + 카테고리 비중 차트 확인

---

## 트러블슈팅

| 증상 | 원인 후보 | 대응 |
|---|---|---|
| 매직링크 발송 후 redirect 안 됨 | Supabase URL Configuration 미등록 | Supabase Auth > URL Configuration에 Streamlit 도메인 추가 |
| **매직링크 클릭 후 로그인 화면 다시 표시** (가장 흔함) | implicit flow가 토큰을 URL hash(#)에 박는데 Streamlit이 못 읽음 | app.py가 PKCE flow(`flow_type="pkce"`) 사용 + Streamlit Secrets에 `SITE_URL` 박힘 확인. 본 v1 코드는 PKCE 적용됨 |
| `KeyError: SITE_URL` 또는 redirect 후 빈 화면 | Streamlit Secrets에 `SITE_URL` 미설정 | Cloud 대시보드 Advanced settings > Secrets에 `SITE_URL = "https://<your-app>.streamlit.app"` 추가 |
| Supabase rate limit `email rate limit exceeded` | built-in SMTP 2통/시간/프로젝트 한도 도달 | (1) 1시간 대기 (2) 다른 이메일 시도 시 same project 한도라 막힘 (3) Resend Custom SMTP 도입 = 30통/시간 영구 해소 (Authentication > Settings > SMTP) |
| "table not found" 에러 | schema/seed 미적용 | `migrations/0001_init.sql` + `seeds/0001_seed.sql` 재확인 |
| holdings 조회는 되는데 0행 | RLS owner_id 미충족 (seed 시 본인 UUID 안 박힘) | jinu-co supabase/README Phase 3 옵션 A `set_config` 재실행 |
| transactions insert 시 owner_id null | 세션 만료 또는 set_session 실패 | 로그아웃·재로그인 |
| Streamlit app `KeyError: SUPABASE_URL` | Streamlit Secrets 미설정 | Cloud 대시보드 Advanced settings > Secrets 확인 |

---

## v1 알려진 한계 (v2에서 보강 예정)

- **`rebalance` 거래 부호 처리 단순화**: 현재 `calc_position_table`은 `rebalance` 타입을 `sell`과 동일 부호(-quantity)로 단순화. 실제 리밸런싱은 양방향(매도-leg + 매수-leg = 2 거래) 분리 입력이 정합. v1 lean에서는 `buy`/`sell` 2건으로 분리 입력 권장. v2에서 `rebalance_pair_id` 컬럼 + 한 form에서 2건 동시 insert로 정식 처리.
- **종목 selectbox `" — "` em-dash 구분자 fragile**: 종목명에 ` — ` 포함 시 split 깨짐. 현 13 종목 안전, 향후 종목 추가 시 dict mapping으로 교체 권장.
- **`fetch_latest_prices` limit(500) 임시값**: 6월+ `prices_snapshot` 시계열 누적 시 자산 수 × 일수 > 500 → 최신 1행 보장 불가. v2에서 Postgres view 또는 RPC로 치환.

## v2 후속 (Phase 5 매직링크 완료 후 별도 작업)

- Dividends form + 분배금 누적 (D-045 자산배분 v1 분배금 정책 — KODEX 미국S&P500 분기 + 국고채30년 연1회 + 미국30년(H) 월 + 구리·농산물 연1회 정합)
- Monthly Log form
- 시계열 가치 추이 차트 (`prices_snapshot` 사용)
- 카테고리 비중 도넛 차트 (목표 vs 실제)
- 매수 추천 KPI (목표 비중 - 실제 비중 = gap, 큰 순)
- rebalance 양방향 거래 form (위 v1 한계 1번 해소)

---

## 참조

- jinu-co `lab/decision-log/2026-05-16.md` D-047
- jinu-co `projects/asset-allocation/supabase/README.md` (Phase 1-6 전체 가이드)
- jinu-co `projects/asset-allocation/supabase/migrations/0001_init.sql`
- jinu-co `projects/asset-allocation/supabase/seeds/0001_seed.sql`
