@echo off
cd /d "%~dp0"
echo Starting ForgeAI... your browser will open. Keep this window open (you can minimise it).
python -m streamlit run app.py --server.headless false --server.showEmailPrompt false--browser.gatherUsageStats false
pause
