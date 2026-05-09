"""CodingAgent 服务入口。"""

import logging
import sys
from pathlib import Path

# 将 src 加入路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router as coding_router
from configs.settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

app = FastAPI(
    title="CodingAgent",
    description="论文复现 Coding Agent — Docker 沙箱 + Approve 模式",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(coding_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "coding-agent"}


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        reload_dirs=[str(Path(__file__).parent / "src")],
    )
