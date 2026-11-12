@echo off
chcp 65001 >nul
rem Build YTSub-PC.exe -> dist\YTSub-PC\  (can: Python 3.10+, ffmpeg trong PATH hoac bin\ffmpeg.exe)
cd /d "%~dp0"
python -m pip install -q -U pyinstaller || goto :err
if not exist bin mkdir bin
if not exist bin\yt-dlp.exe (
  echo Dang tai yt-dlp.exe ...
  curl -L -o bin\yt-dlp.exe https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe || goto :err
)
if not exist bin\ffmpeg.exe (
  for /f "delims=" %%F in ('"%SystemRoot%\System32\where.exe" ffmpeg 2^>nul') do if not exist bin\ffmpeg.exe copy /y "%%F" bin\ffmpeg.exe >nul
)
if not exist bin\ffmpeg.exe echo [!] Khong tim thay ffmpeg.exe - hay chep vao thu muc bin\ roi build lai.
python -m PyInstaller --noconfirm --clean --name YTSub-PC --console --icon icon.ico ^
  --add-data "ytsub\web;ytsub\web" main.py || goto :err
"%SystemRoot%\System32\xcopy.exe" /e /i /y bin dist\YTSub-PC\bin >nul
"%SystemRoot%\System32\xcopy.exe" /e /i /y extension dist\YTSub-PC\extension >nul
copy /y README.md dist\YTSub-PC\ >nul
echo.
echo Xong: dist\YTSub-PC\YTSub-PC.exe
goto :eof
:err
echo Build loi.
exit /b 1
