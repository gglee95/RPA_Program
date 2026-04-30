# BeForward Docker Run

## Structure
- `beforward-upload`: upload-only worker
- `beforward-monitor`: sold-out monitoring-only worker

## Prepare
- Copy `.env.docker.example` to `.env.docker`
- Place `adjustmentdata-51a7199ac3ba.json` in the project root
- Update `.env.docker` if account, sheet, or timing settings need changes

## Start
```powershell
Copy-Item .env.docker.example .env.docker
docker compose up -d --build
```

## Logs
```powershell
docker compose logs -f beforward-upload
docker compose logs -f beforward-monitor
```

## Stop
```powershell
docker compose down
```

## Package
```powershell
powershell -ExecutionPolicy Bypass -File .\build_docker_zip.ps1
```
