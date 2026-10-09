@echo off
setlocal
rem ============================================================
rem  Lanceur Windows du generateur de recettes
rem  Double-clic : met a jour depuis GitHub puis lance le serveur
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

rem --- Recherche de Python (python, sinon lanceur py) ---
set "PY="
python --version >nul 2>&1 && set "PY=python"
if not defined PY (
  py -3 --version >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  echo [X] Python introuvable.
  echo     Installe-le depuis https://www.python.org/downloads/
  echo     en cochant "Add python.exe to PATH", puis relance ce fichier.
  echo.
  pause
  exit /b 1
)

rem --- Lancement du serveur (Ctrl+C pour arreter) ---
%PY% serveur_recettes.py %*

echo.
echo Serveur arrete.
pause
