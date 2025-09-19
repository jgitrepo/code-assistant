@echo off
setlocal
if exist .env (
  for /f "usebackq delims=" %%a in (".env") do set %%a
)
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
endlocal
