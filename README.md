## Notes:
The files and folders within FYP scope are:
1. alembic
2. src
3. user_data
4. .env
5. alembic.ini
6. requirements.txt

## Steps to setup the project

## Create Python environment (Windows)
`python -m venv venv`

## Create Python environment (macOS/Linux)
`python3 -m venv venv`

## Start Virtual environment
`.venv\Scripts\Activate.ps1`

If virtual environment folder is venv:
`venv\Scripts\Activate.ps1`

## Install Dependencies
`pip install -r requirements.txt`

## To start backend
`uvicorn src.app.main:app`

## For Alembic Database Migration Refer README file under /alembic

## To download ohlcv data #################
```
$body = @{
    pairs = @("BTCUSDT");
    timeframe = "1h";
    timerange = "20210101-20251031"
}

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/ohlcv/" `
    -Method POST `
    -ContentType "application/json" `
    -Body ($body | ConvertTo-Json)

```