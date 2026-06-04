@echo off
REM ========================================================================
REM Suppression des Doublons Archifiltre v4.0 - Lanceur Windows
REM ========================================================================

setlocal enabledelayedexpansion

REM Accès au répertoire du script
cd /d "%~dp0"

REM Titre de la console
title Suppression des Doublons Archifiltre v4.0

echo.
echo =========================================
echo Suppression des Doublons Archifiltre v4.0
echo =========================================
echo.

REM Vérifier si Python est installé
echo Vérification de Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERREUR: Python n'est pas trouvé!
    echo.
    echo Solutions:
    echo 1. Installez Python depuis https://www.python.org/downloads/
    echo 2. Assurez-vous que "Add Python to PATH" est coché lors de l'installation
    echo 3. Redémarrez l'ordinateur après installation
    echo.
    pause
    exit /b 1
)

REM Afficher la version Python
echo.
echo Python trouvé:
python --version
echo.

REM Chercher le fichier application_doublon.py
if not exist "application_doublon.py" (
    echo.
    echo ERREUR: application_doublon.py non trouvé
    echo Assurez-vous de lancer le script depuis le dossier contenant application_doublon.py
    echo.
    pause
    exit /b 1
)

REM Installer la dependance optionnelle pour la corbeille (best effort)
python -c "import send2trash" >nul 2>&1
if errorlevel 1 (
    echo Installation de send2trash ^(corbeille^)...
    python -m pip install --quiet send2trash >nul 2>&1
)

REM Lancer l'application
echo "Lancement de l'application..."
echo.
python application_doublon.py

if errorlevel 1 (
    echo.
    echo ERREUR: L'application a rencontré une erreur
    echo.
    pause
)

endlocal
