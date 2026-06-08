"""FastAPI 应用主入口"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from app.database import init_database
from app.auto_updater import smart_update_loop
from app.config import SERVER_HOST, SERVER_PORT, POLL_INTERVAL
from app.logger import logger

app = FastAPI(title="彩票数据系统")

# 挂载静态文件
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")),
    name="static",
)


# ========== 请求日志中间件 ==========
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    method = request.method
    path = request.url.path
    query = str(request.url.query) if request.url.query else ""

    try:
        response = await call_next(request)
        elapsed = round((time.time() - start) * 1000)  # ms

        if response.status_code >= 500:
            logger.error(f"[{method}] {path} → {response.status_code} [{elapsed}ms] (query: {query})")
        elif response.status_code >= 400:
            logger.warning(f"[{method}] {path} → {response.status_code} [{elapsed}ms] (query: {query})")
        else:
            logger.info(f"[{method}] {path} → {response.status_code} [{elapsed}ms]")

        return response

    except Exception as e:
        elapsed = round((time.time() - start) * 1000)
        logger.error(f"[{method}] {path} → EXCEPTION [{elapsed}ms]: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"服务器内部错误: {str(e)}"},
        )


# 注册页面路由
from app.routes_page import router as page_router
app.include_router(page_router)

# 注册 API 路由（统一 /api 前缀）
from app.routes_api import router as api_router
app.include_router(api_router, prefix="/api")


@app.on_event("startup")
async def startup():
    init_database()
    import asyncio
    asyncio.create_task(smart_update_loop(check_interval=POLL_INTERVAL))
    logger.info("数据库初始化完成")
    logger.info(f"后台智能更新已启动（每 {POLL_INTERVAL//60} 分钟检查一次）")
    logger.info(f"访问 http://{SERVER_HOST}:{SERVER_PORT} 查看页面")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)