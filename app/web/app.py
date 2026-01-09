from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Создаем простое приложение без логики запуска бота
app = FastAPI(title="Nexus Wallet API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "ok", "service": "web_api_placeholder"}