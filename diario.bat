@echo off
rem Ejecución diaria de job-agents (Programador de tareas de Windows).
rem Requiere el PC encendido y Chrome abierto con la extensión Claude conectada.
rem Con la variable de entorno JOB_AGENTS_DIARIO=nuevo usa src.diario (una sesión de Claude por fase);
rem sin ella, la sesión única de siempre. Los argumentos se pasan a src.diario (p. ej. --simular).
cd /d "%~dp0"
if not exist logs mkdir logs
echo ==== %date% %time% ==== >> logs\diario.log
if /i "%JOB_AGENTS_DIARIO%"=="nuevo" goto nuevo
claude -p "/diario" --chrome --allowedTools "Read,Write,Edit,Glob,Grep,ToolSearch,Agent,Task,WebSearch,WebFetch,mcp__claude-in-chrome,mcp__claude_ai_Gmail,mcp__claude_ai_Composio,Bash(python -m src.cli:*),Bash(python -m candidaturas:*),Bash(cd:*),Bash(mkdir:*)" >> logs\diario.log 2>&1
goto :eof
:nuevo
python -m src.diario %* >> logs\diario.log 2>&1
