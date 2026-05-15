# jinu-asset-streamlit

진우(J7NU)의 자산배분 대시보드. Streamlit Cloud + Supabase + 매직링크 인증.

## 스택
- Streamlit (UI + Cloud 배포)
- Supabase (Postgres + Auth + RLS)
- pandas + plotly (계산·시각화)

## 배포 (Streamlit Cloud)
1. https://share.streamlit.io → New app
2. Repository: `J7NU/jinu-asset-streamlit` / Branch: `main` / Main file: `app.py`
3. Advanced settings > Secrets에 아래 paste (실값으로 교체):
   ```toml
   SUPABASE_URL = "https://<your-ref>.supabase.co"
   SUPABASE_ANON_KEY = "<your-anon-public-key>"
