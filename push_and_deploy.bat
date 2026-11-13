@echo off
echo ========================================================
echo  Deploying AI-Automation-Command-Center to Live VPS
echo ========================================================
git add .
git commit -m "Update and auto-deploy to live VPS"
git push origin main
echo.
echo Triggering live deployment on 66.45.230.232...
curl -s -m 30 "http://66.45.230.232:9000/update"
echo.
echo Deployment triggered successfully!
pause
