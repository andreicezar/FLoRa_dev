@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ====== CONFIGURE YOUR PATHS ======
set "SRC_JSON=D:\Doctorat\anul_2\apps\FLoRa_development\flora\simulations\json_exports"
set "DEST_SIM=D:\Doctorat\anul_2\apps\FLoRa_dev\simulations"
REM ===================================

REM --- normalize absolute paths & derive parent 'simulations' ---
for %%I in ("%SRC_JSON%") do set "SRC_JSON=%%~fI"
for %%I in ("%DEST_SIM%") do set "DEST_SIM=%%~fI"
for %%I in ("%SRC_JSON%\..") do set "SRC_SIM_DIR=%%~fI"

echo ==== PATHS ====
echo SRC_JSON   : "%SRC_JSON%"
echo SRC_SIM_DIR: "%SRC_SIM_DIR%"
echo DEST_SIM   : "%DEST_SIM%"
echo.

REM Check if source exists
if not exist "%SRC_JSON%" (
    echo [ERROR] Source folder not found: "%SRC_JSON%"
    pause
    exit /b 2
)

REM Create destination if it doesn't exist
if not exist "%DEST_SIM%" (
    echo Creating destination directory: "%DEST_SIM%"
    md "%DEST_SIM%" 2>nul
    if not exist "%DEST_SIM%" (
        echo [ERROR] Failed to create destination directory
        pause
        exit /b 3
    )
)

REM Check if json_exports folder has content
echo Checking source folder contents...
dir "%SRC_JSON%" /b | findstr /r "." >nul
if errorlevel 1 (
    echo [WARNING] Source folder appears to be empty: "%SRC_JSON%"
)

REM ===== METHOD 1: Try Windows tar.exe =====
where tar >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Found tar.exe, attempting ZIP creation...
    
    REM Remove old zip if exists
    if exist "%SRC_SIM_DIR%\json_exports.zip" (
        echo Removing existing ZIP file...
        del /f /q "%SRC_SIM_DIR%\json_exports.zip"
    )
    
    REM Create ZIP using tar
    echo Creating ZIP: "%SRC_SIM_DIR%\json_exports.zip"
    pushd "%SRC_SIM_DIR%"
    tar -a -c -f "json_exports.zip" "json_exports"
    set "TAR_RC=!ERRORLEVEL!"
    popd
    
    if "!TAR_RC!" EQU "0" (
        if exist "%SRC_SIM_DIR%\json_exports.zip" (
            echo [OK] ZIP created successfully with tar
            goto :COPY_ZIP
        ) else (
            echo [ERROR] tar reported success but ZIP file not found
        )
    ) else (
        echo [ERROR] tar failed with exit code: !TAR_RC!
    )
)

REM ===== METHOD 2: Try PowerShell as fallback =====
echo [INFO] Trying PowerShell compression as fallback...
if exist "%SRC_SIM_DIR%\json_exports.zip" del /f /q "%SRC_SIM_DIR%\json_exports.zip"

powershell -Command "try { Compress-Archive -Path '%SRC_JSON%' -DestinationPath '%SRC_SIM_DIR%\json_exports.zip' -CompressionLevel Optimal -Force; exit 0 } catch { Write-Error $_.Exception.Message; exit 1 }"
set "PS_RC=!ERRORLEVEL!"

if "!PS_RC!" EQU "0" (
    if exist "%SRC_SIM_DIR%\json_exports.zip" (
        echo [OK] ZIP created successfully with PowerShell
        goto :COPY_ZIP
    ) else (
        echo [ERROR] PowerShell reported success but ZIP file not found
    )
) else (
    echo [ERROR] PowerShell compression failed with exit code: !PS_RC!
)

echo [ERROR] Both tar and PowerShell methods failed to create ZIP
pause
exit /b 4

:COPY_ZIP
REM ===== 2) COPY THE ZIP TO DESTINATION =====
echo.
echo Copying ZIP to destination...
echo From: "%SRC_SIM_DIR%\json_exports.zip"
echo To  : "%DEST_SIM%\json_exports.zip"

copy /Y "%SRC_SIM_DIR%\json_exports.zip" "%DEST_SIM%\json_exports.zip"
if errorlevel 1 (
    echo [ERROR] Failed to copy ZIP to destination
    pause
    exit /b 5
)

REM Verify the copy
if exist "%DEST_SIM%\json_exports.zip" (
    echo [OK] ZIP copied successfully
    REM Show file size for verification
    for %%F in ("%DEST_SIM%\json_exports.zip") do echo ZIP size: %%~zF bytes
) else (
    echo [ERROR] ZIP copy verification failed - file not found at destination
    pause
    exit /b 6
)

REM ===== 3) COPY FOLDER STRUCTURE WITHOUT .json FILES =====
echo.
echo Copying folder structure without .json/.anf files...
echo From: "%SRC_JSON%"
echo To  : "%DEST_SIM%\json_exports"

REM Create destination json_exports folder
if not exist "%DEST_SIM%\json_exports" md "%DEST_SIM%\json_exports"

REM Copy structure excluding large files
robocopy "%SRC_JSON%" "%DEST_SIM%\json_exports" /E /XF *.json *.anf /R:2 /W:1
set "ROBO_RC=!ERRORLEVEL!"
REM Robocopy exit codes: 0-7 are success, 8+ are errors
if !ROBO_RC! GEQ 8 (
    echo [ERROR] Robocopy failed with exit code: !ROBO_RC!
    pause
    exit /b !ROBO_RC!
) else (
    echo [OK] Folder structure copied successfully (robocopy exit code: !ROBO_RC!)
)

REM ===== 4) COPY ENTIRE EXAMPLES FOLDER =====
echo.
echo Copying entire examples folder...
set "SRC_EXAMPLES=%SRC_SIM_DIR%\examples"
set "DEST_EXAMPLES=%DEST_SIM%\examples"

if not exist "!SRC_EXAMPLES!" (
    echo [WARNING] Examples folder not found at "!SRC_EXAMPLES!", skipping.
) else (
    echo From: "!SRC_EXAMPLES!"
    echo To  : "!DEST_EXAMPLES!"
    robocopy "!SRC_EXAMPLES!" "!DEST_EXAMPLES!" /E /R:2 /W:1
    set "ROBO_RC_EXAMPLES=!ERRORLEVEL!"
    if !ROBO_RC_EXAMPLES! GEQ 8 (
        echo [ERROR] Robocopy failed to copy examples with exit code: !ROBO_RC_EXAMPLES!
        pause
        exit /b !ROBO_RC_EXAMPLES!
    ) else (
        echo [OK] Examples folder copied successfully (robocopy exit code: !ROBO_RC_EXAMPLES!)
    )
)

REM ======================= NEW SECTION START =======================
REM ===== 5) COPY UTILITY SCRIPTS =====
echo.
echo Copying utility scripts...

set "SRC_SCRIPT1=%SRC_SIM_DIR%\integrated_run_and_export.sh"
if exist "!SRC_SCRIPT1!" (
    copy /Y "!SRC_SCRIPT1!" "%DEST_SIM%\" >nul
    if errorlevel 1 (
        echo [ERROR] Failed to copy integrated_run_and_export.sh
    ) else (
        echo [OK] Copied integrated_run_and_export.sh
    )
) else (
    echo [WARNING] Script not found: integrated_run_and_export.sh, skipping.
)

set "SRC_SCRIPT2=%SRC_SIM_DIR%\complete_export_all_scenarios.sh"
if exist "!SRC_SCRIPT2!" (
    copy /Y "!SRC_SCRIPT2!" "%DEST_SIM%\" >nul
    if errorlevel 1 (
        echo [ERROR] Failed to copy complete_export_all_scenarios.sh
    ) else (
        echo [OK] Copied complete_export_all_scenarios.sh
    )
) else (
    echo [WARNING] Script not found: complete_export_all_scenarios.sh, skipping.
)
REM ======================== NEW SECTION END ========================

REM ===== 6) COPY PYTHON SCRIPTS =====
echo.
echo Copying Python analysis scripts...

set "PYTHON_SCRIPTS=analyze_flora_scenario_01.py analyze_flora_scenario_02.py analyze_flora_scenario_03.py analyze_flora_scenario_05.py analyze_n100_gw1_ADR.py flora_names.py"

for %%s in (%PYTHON_SCRIPTS%) do (
    set "SRC_PY=%SRC_SIM_DIR%\%%s"
    if exist "!SRC_PY!" (
        copy /Y "!SRC_PY!" "%DEST_SIM%\" >nul
        if errorlevel 1 (
            echo [ERROR] Failed to copy %%s
        ) else (
            echo [OK] Copied %%s
        )
    ) else (
        echo [WARNING] Script not found: %%s, skipping.
    )
)

REM Update the summary section
echo.
echo ===== SUMMARY =====
echo ZIP file: "%DEST_SIM%\json_exports.zip"
echo Folder structure: "%DEST_SIM%\json_exports\"
echo Examples folder: "%DEST_SIM%\examples\"
echo Utility scripts: Copied to "%DEST_SIM%\"
echo Python scripts: Copied to "%DEST_SIM%\"
echo [SUCCESS] All operations completed successfully!
echo.
pause
exit /b 0