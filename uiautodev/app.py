#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Created on Sun Feb 18 2024 13:48:55 by codeskyblue
"""

import logging
import os
import platform
import signal
from pathlib import Path
from typing import List

import uvicorn
from fastapi import FastAPI, File, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from uiautodev import __version__
from uiautodev.common import convert_bytes_to_image, get_webpage_url, ocr_image
from uiautodev.model import Node
from uiautodev.provider import AndroidProvider, HarmonyProvider, IOSProvider, MockProvider
from uiautodev.remote.scrcpy import ScrcpyServer
from uiautodev.router.device import make_router
from uiautodev.router.xml import router as xml_router
from uiautodev.utils.envutils import Environment

logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

android_router = make_router(AndroidProvider())
ios_router = make_router(IOSProvider())
harmony_router = make_router(HarmonyProvider())
mock_router = make_router(MockProvider())

app.include_router(mock_router, prefix="/api/mock", tags=["mock"])

if Environment.UIAUTODEV_MOCK:
    app.include_router(mock_router, prefix="/api/android", tags=["mock"])
    app.include_router(mock_router, prefix="/api/ios", tags=["mock"])
    app.include_router(mock_router, prefix="/api/harmony", tags=["mock"])
else:
    app.include_router(android_router, prefix="/api/android", tags=["android"])
    app.include_router(ios_router, prefix="/api/ios", tags=["ios"])
    app.include_router(harmony_router, prefix="/api/harmony", tags=["harmony"])

app.include_router(xml_router, prefix="/api/xml", tags=["xml"])


class InfoResponse(BaseModel):
    version: str
    description: str
    platform: str
    code_language: str
    cwd: str
    drivers: List[str]


@app.get("/api/info")
def info() -> InfoResponse:
    """Information about the application"""
    return InfoResponse(
        version=__version__,
        description="client for https://uiauto.dev",
        platform=platform.system(),  # Linux | Darwin | Windows
        code_language="Python",
        cwd=os.getcwd(),
        drivers=["android", "ios", "harmony"],
    )


@app.post('/api/ocr_image')
async def _ocr_image(file: UploadFile = File(...)) -> List[Node]:
    """OCR an image"""
    image_data = await file.read()
    image = convert_bytes_to_image(image_data)
    return ocr_image(image)


@app.get("/shutdown")
def shutdown() -> str:
    """Shutdown the server"""
    os.kill(os.getpid(), signal.SIGINT)
    return "Server shutting down..."


@app.get("/demo")
def demo():
    """Demo endpoint"""
    static_dir = Path(__file__).parent / "static"
    print(static_dir / "demo.html")
    return FileResponse(static_dir / "demo.html")


@app.get("/")
def index_redirect():
    """ redirect to official homepage """
    url = get_webpage_url()
    logger.debug("redirect to %s", url)
    return RedirectResponse(url)


@app.websocket("/android/scrcpy/{path_type}/{serial}")
async def unified_ws(websocket: WebSocket, path_type: str, serial: str):
    """
    匹配以下WS流，如果有证书，后续ng可以配置后，将ws升级为wss
    视频流（h264流前端展示）：ws://0.0.0.0:4000/android/scrcpy/screen/<serial>
    控制流 (touch操控事件下发):ws://0.0.0.0:4000/android/scrcpy/control/<serial>
    todo: 视频流目前前端还是使用截图来获取展示，待优化接入该WS视频流
    """
    await websocket.accept()
    try:
        logger.info(f"WebSocket path_type: {path_type}, serial: {serial}")

        # 获取 ScrcpyServer 实例
        server = ScrcpyServer()
        server.start_scrcpy_server(serial)
        server.setup_connection(serial)

        # 根据 path_type 处理不同的 WebSocket 类型
        if path_type == "screen":
            await server.handle_video_websocket(websocket, serial)
        elif path_type == "control":
            await server.handle_control_websocket(websocket, serial)
        else:
            await websocket.close(code=1008)
            logger.error(f"Unknown WebSocket type: {path_type}")
    except Exception as e:
        logger.error(f"WebSocket error for path_type={path_type}, serial={serial}: {e}")
    finally:
        logger.info(f"WebSocket closed for path_type={path_type}, serial={serial}")


if __name__ == '__main__':
    uvicorn.run("uiautodev.app:app", port=4000, reload=True, use_colors=True)
