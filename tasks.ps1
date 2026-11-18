# Tareas de desarrollo. Uso:  .\tasks.ps1 <tarea>   (sin argumentos: ayuda)
param([Parameter(Position = 0)][string]$Task = "help")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Run {
    & $args[0] @($args | Select-Object -Skip 1)
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

switch ($Task) {
    "setup"     { if (-not (Test-Path .env)) { Copy-Item .env.example .env; "Creado .env" } else { ".env ya existe" } }
    "lock"      { Run docker run --rm -v "${PWD}:/work" -w /work ghcr.io/astral-sh/uv:0.5.9-python3.12-bookworm-slim uv lock }
    "build"     { Run docker compose build }
    "up"        { Run docker compose up -d --build }
    "down"      { Run docker compose down }
    "logs"      { Run docker compose logs -f --tail=100 app }
    "test"      { Run docker compose run --rm app pytest -q }
    "lint"      { Run docker compose run --rm app sh -c "ruff check . && ruff format --check ." }
    "fmt"       { Run docker compose run --rm app sh -c "ruff check --fix . && ruff format ." }
    "shell"     { Run docker compose run --rm app bash }
    "health"    { Invoke-RestMethod http://localhost:8000/health | ConvertTo-Json -Depth 5 }
    "prod-up"   { Run docker compose -f docker-compose.prod.yml up -d --build }
    "prod-down" { Run docker compose -f docker-compose.prod.yml down }
    "prod-logs" { Run docker compose -f docker-compose.prod.yml logs -f --tail=100 app }
    default {
        @"
Tareas: setup lock build up down logs test lint fmt shell health prod-up prod-down prod-logs
"@
    }
}
