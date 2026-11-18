# Finanzas

Seguimiento personal de inversiones (esqueleto del paso 1). Python 3.12 · FastAPI · SQLite (WAL) · APScheduler · Docker.

## Arrancar en Windows

1. **Comprobar que Docker Desktop usa WSL2**
   - Docker Desktop → Settings → General → debe estar marcado *Use the WSL 2 based engine*.
   - En PowerShell:
     ```powershell
     wsl -l -v            # tu distro (y docker-desktop) deben mostrar VERSION 2
     docker info --format "{{.OSType}} / {{.KernelVersion}}"   # debe contener "WSL2"
     ```
2. **Crear `.env`** (sin secretos reales de momento):
   ```powershell
   .\tasks.ps1 setup
   ```
3. **Arrancar** (la primera vez tarda por la construcción de la imagen):
   ```powershell
   .\tasks.ps1 up
   .\tasks.ps1 health      # o abre http://localhost:8000/health
   ```
4. Otros comandos: `down`, `logs`, `test`, `lint`, `fmt`, `shell`, `build`, `prod-up`, `prod-down`, `prod-logs`.

Si PowerShell bloquea el script: `powershell -ExecutionPolicy Bypass -File .\tasks.ps1 up`.

## Dependencias

Gestionadas con [uv](https://docs.astral.sh/uv/): `pyproject.toml` + `uv.lock` (se versiona). Para añadir o actualizar una dependencia, edita `pyproject.toml` y ejecuta `.\tasks.ps1 lock` (usa uv dentro de Docker; no hace falta instalarlo en Windows), luego `.\tasks.ps1 build`.

## Datos

La base vive en `/data/db/finanzas.sqlite3`, dentro del volumen nombrado `finanzas_dev_data` (desarrollo) o `finanzas_prod_data` (producción). Sobrevive a `down`, a recrear contenedores y a reconstruir la imagen. **`docker compose down -v` borra el volumen**; no lo uses con datos reales. Los backups futuros irán en `/data/backups`.

## Depurar desde VS Code

Con la app arrancada (`up`), usa la configuración *Adjuntar a Docker (debugpy :5678)* de `.vscode/launch.json`.

## Producción / Raspberry Pi 5

```powershell
.\tasks.ps1 prod-up
```

Comprobar que la imagen construye para arm64 (sin ejecutarla):

```powershell
docker buildx build --platform linux/arm64 --target prod -t finanzas:arm64-check .
```

Si falla por falta de emulación, instala los binfmt una vez: `docker run --privileged --rm tonistiigi/binfmt --install arm64`.

## Estructura

`src/finanzas/` → `dominio/` (reglas puras), `ingesta/`, `precios/`, `persistencia/`, `servicios/`, `api/`, `web/`, `tareas/`. Tests en `tests/`.
