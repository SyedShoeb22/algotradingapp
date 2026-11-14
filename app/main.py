
from fastapi import FastAPI

app = FastAPI(
    title="Personal Algo Trading System",
    description="My own algorithmic trading application",
    version="1.0.0"
)

@app.get("/")
def home():
    return {
        "status": "success",
        "message": "Algo Trading Application is running!"
    }

@app.get("/health")
def health():
    return {
        "application": "Algo Trading",
        "status": "healthy"
    }
