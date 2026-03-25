"""
Qui Tam Case Engine — FastAPI Entry Point.

Ingests public government data, identifies fraud against the United States,
and packages findings into attorney-ready case leads.

Phase 1: Hospice fraud detection via CMS Hospice Compare + OIG LEIE + NPPES.
"""

import asyncio
import json
import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from db.database import init_db
from web.routes import router
from pipeline.orchestrator import run_pipeline

app = FastAPI(title="Qui Tam Case Engine", version="0.1.0")

# Mount static files
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# Include routes
app.include_router(router)

# Global pipeline state
_pipeline_running = False
_pipeline_queue: asyncio.Queue | None = None


@app.on_event("startup")
def on_startup():
    init_db()


@app.post("/analyze")
async def start_analysis():
    """Start the full analysis pipeline. Returns loading page; progress via SSE."""
    global _pipeline_running, _pipeline_queue

    if _pipeline_running:
        return HTMLResponse(
            '<script>window.location.href="/loading";</script>',
            status_code=200,
        )

    _pipeline_running = True
    _pipeline_queue = asyncio.Queue()

    async def _run():
        global _pipeline_running
        try:
            result = await run_pipeline(_pipeline_queue)
            _pipeline_queue.put_nowait({
                "message": f"COMPLETE: {result.get('case_leads_generated', 0)} case leads generated",
                "percent": 1.0,
            })
        except Exception as e:
            _pipeline_queue.put_nowait({
                "message": f"ERROR: {str(e)}",
                "percent": -1,
            })
        finally:
            _pipeline_running = False

    asyncio.create_task(_run())

    return HTMLResponse(
        '<script>window.location.href="/loading";</script>',
        status_code=200,
    )


@app.get("/loading", response_class=HTMLResponse)
async def loading_page():
    """Show the loading/progress page."""
    from fastapi.templating import Jinja2Templates
    from starlette.requests import Request
    templates = Jinja2Templates(directory="web/templates")
    # Create a minimal request object
    from starlette.datastructures import Headers
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/loading",
        "headers": [],
        "query_string": b"",
    }
    request = Request(scope)
    return templates.TemplateResponse("loading.html", {"request": request})


@app.get("/progress")
async def progress_stream():
    """SSE endpoint for pipeline progress updates."""
    async def event_generator():
        while True:
            if _pipeline_queue is None:
                await asyncio.sleep(1)
                yield f"data: {json.dumps({'message': 'Waiting for pipeline...', 'percent': 0})}\n\n"
                continue

            try:
                data = await asyncio.wait_for(_pipeline_queue.get(), timeout=2.0)
                yield f"data: {json.dumps(data)}\n\n"

                if data.get("percent") == 1.0 or data.get("percent") == -1:
                    break
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'message': 'Working...', 'percent': None})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
