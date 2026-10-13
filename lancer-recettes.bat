@echo off
setlocal
rem ============================================================
rem  Lanceur Windows du generateur de recettes
rem  Double-clic : au premier lancement, installe Python (si absent,
rem  apres confirmation) et l'extraction de PDF ; ensuite, lance
rem  directement le serveur. Met a jour a chaque lancement : git pull
rem  si le dossier est un clone git, sinon derniere release GitHub.
rem  Options transmises au serveur, ex. : lancer-recettes.bat --lan
rem ============================================================
cd /d "%~dp0"
title Generateur de recettes

rem --- Mise a jour depuis GitHub (si dossier clone avec git) ---
if exist ".git" (
  git --version >nul 2>&1
  if not errorlevel 1 (
    echo Mise a jour depuis GitHub...
    git pull --ff-only || echo [!] Mise a jour impossible, lancement de la version locale.
    echo.
  )
)

rem --- Python : cherche, sinon propose de l'installer (winget) ---
call :trouver_python
if not defined PY (
  echo Python n'est pas installe sur cet ordinateur.
  winget --version >nul 2>&1
  if errorlevel 1 goto :python_manuel
  echo.
  choice /m "Installer Python maintenant avec winget"
  if errorlevel 2 goto :python_manuel
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  call :trouver_python
  if not defined PY (
    echo.
    echo [!] Python est installe, mais cette fenetre ne le voit pas encore.
    echo     Ferme-la et relance lancer-recettes.bat.
    echo.
    pause
    exit /b 1
  )
)

rem --- Mise a jour (sans git) : derniere release GitHub, tout ou rien, la base n'est pas touchee ---
if not exist ".git" (
  echo Recherche d'une nouvelle version...
  %PY% serveur_recettes.py --maj
  if errorlevel 1 echo [!] Mise a jour impossible, lancement de la version actuelle.
  echo.
)

rem --- Extraction de PDF (pdfplumber) : installee une seule fois ---
if not exist ".dependances-ok" (
  echo Installation de l'extraction de PDF, une seule fois...
  %PY% -m pip install --user --disable-pip-version-check pdfplumber
  if errorlevel 1 (
    echo [!] Installation impossible : l'import de PDF ne sera pas disponible. Nouvel essai au prochain lancement.
  ) else (
    echo ok> ".dependances-ok"
  )
  echo.
)

rem --- Lancement du serveur (Ctrl+C pour arreter) ---
%PY% serveur_recettes.py %*

echo.
echo Serveur arrete.
pause
exit /b 0

:python_manuel
echo.
echo Installe Python depuis https://www.python.org/downloads/
echo en cochant "Add python.exe to PATH", puis relance ce fichier.
echo.
pause
exit /b 1

:trouver_python
set "PY="
python --version >nul 2>&1 && set "PY=python"
if defined PY goto :eof
py -3 --version >nul 2>&1 && set "PY=py -3"
if defined PY goto :eof
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%~D\python.exe" set PY="%%~D\python.exe"
goto :eof
