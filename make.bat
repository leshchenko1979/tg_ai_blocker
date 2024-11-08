setlocal EnableExtensions EnableDelayedExpansion

isort .
black .

pytest
if errorlevel 1 exit /b %errorlevel%

docker build --pull --rm -f ".dockerfile" ^
-t tg-ai-blocker:latest "."
if errorlevel 1 exit /b %errorlevel%

docker tag tg-ai-blocker:latest ^
cr.yandex/crp8ek2lo6uuvnveblac/tg-ai-blocker
if errorlevel 1 exit /b %errorlevel%

docker push cr.yandex/crp8ek2lo6uuvnveblac/tg-ai-blocker
if errorlevel 1 exit /b %errorlevel%

yc serverless container revision deploy ^
--container-name tg-ai-blocker ^
--image cr.yandex/crp8ek2lo6uuvnveblac/tg-ai-blocker ^
--cores 1 --core-fraction 20 --memory 256MB --execution-timeout 300s ^
--concurrency 1 ^
--service-account-id aje5p7k2njcs6pml41ji
if errorlevel 1 exit /b %errorlevel%

exit /b 0
