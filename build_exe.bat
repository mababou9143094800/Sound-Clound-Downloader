@echo off
title Build SoundCloudDownloader.exe
color 0A

echo.
echo  ================================================
echo    Build SoundCloudDownloader.exe
echo  ================================================
echo.

:: Verifie que Python est disponible
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERREUR] Python introuvable dans le PATH.
    echo  Lance d'abord : python launcher.py
    pause
    exit /b 1
)

:: Installe PyInstaller si absent
echo  [1/3] Verification de PyInstaller...
python -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo  Installation de PyInstaller...
    pip install pyinstaller --quiet
)
echo  [OK] PyInstaller pret.

:: Nettoyage des anciens builds
echo.
echo  [2/3] Nettoyage...
if exist dist\SoundCloudDownloader.exe del /f /q dist\SoundCloudDownloader.exe
if exist build rmdir /s /q build
if exist SoundCloudDownloader.spec del /f /q SoundCloudDownloader.spec

:: Build
echo.
echo  [3/3] Compilation (patiente 30-60 secondes)...
echo.
python -m PyInstaller ^
    --onefile ^
    --console ^
    --name "SoundCloudDownloader" ^
    --hidden-import=curl_cffi ^
    --hidden-import=flask ^
    launcher.py

if %errorlevel% neq 0 (
    echo.
    echo  [ERREUR] La compilation a echoue.
    echo  Verifie que launcher.py est dans ce dossier.
    pause
    exit /b 1
)

:: Copie l'exe a la racine
if exist dist\SoundCloudDownloader.exe (
    copy /y dist\SoundCloudDownloader.exe SoundCloudDownloader.exe >nul
    echo.
    echo  ================================================
    echo   [OK] SoundCloudDownloader.exe cree !
    echo.
    echo   Place ces fichiers ensemble :
    echo     - SoundCloudDownloader.exe
    echo     - app.py
    echo     - downloader.py
    echo.
    echo   Double-clique sur SoundCloudDownloader.exe
    echo   pour lancer le programme.
    echo  ================================================
) else (
    echo  [ERREUR] Le fichier exe n'a pas ete genere.
)

echo.
pause
