# Enable strict mode and stop on errors
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Format code
Write-Host "Formatting code..." -ForegroundColor Cyan
Push-Location app
& isort .
& isort ../tests
Pop-Location
& black .

# Run tests
Write-Host "Running tests..." -ForegroundColor Cyan
& pytest
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }

# Build and deploy
Write-Host "Building and deploying..." -ForegroundColor Cyan
& docker build --pull --rm -f ".dockerfile" -t tg-ai-blocker:latest "."
if ($LASTEXITCODE -ne 0) { throw "Docker build failed" }

& docker tag tg-ai-blocker:latest cr.yandex/crp8ek2lo6uuvnveblac/tg-ai-blocker
if ($LASTEXITCODE -ne 0) { throw "Docker tag failed" }

& docker push cr.yandex/crp8ek2lo6uuvnveblac/tg-ai-blocker
if ($LASTEXITCODE -ne 0) { throw "Docker push failed" }

& yc serverless container revision deploy `
    --container-name tg-ai-blocker `
    --image cr.yandex/crp8ek2lo6uuvnveblac/tg-ai-blocker `
    --cores 1 --core-fraction 20 --memory 256MB --execution-timeout 300s `
    --concurrency 1 `
    --service-account-id aje5p7k2njcs6pml41ji
if ($LASTEXITCODE -ne 0) { throw "Deployment failed" }

Write-Host "Build and deployment completed successfully" -ForegroundColor Green
