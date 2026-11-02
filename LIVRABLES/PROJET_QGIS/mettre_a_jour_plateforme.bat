@echo off
rem Met a jour la plateforme (dossier ..\PLATEFORME\data) a partir de la couche d'assemblage marcory_bingerville.gpkg.
rem Fermer d'abord la session d'edition dans QGIS (enregistrer les modifications des couches).
cd /d "%~dp0"
python mettre_a_jour_plateforme.py
echo.
pause
