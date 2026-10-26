@echo off
rem Ejecución diaria de job-agents (Programador de tareas de Windows).
rem Requiere el PC encendido y Chrome abierto con la extensión Claude conectada.
cd /d "%~dp0"
if not exist logs mkdir logs
echo ==== %date% %time% ==== >> logs\diario.log
claude -p "/diario" --chrome --allowedTools "Read,Write,Edit,Glob,Grep,ToolSearch,Agent,Task,WebSearch,WebFetch,mcp__claude-in-chrome,mcp__claude_ai_Gmail,mcp__claude_ai_Composio,Bash(python -m src.cli:*),Bash(mkdir:*)" >> logs\diario.log 2>&1
