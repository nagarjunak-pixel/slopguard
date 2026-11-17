"""FastAPI backend serving slopguard code scanner, demo showcase, live Ollama audit & SPA UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from slopguard.analyzers.gate_engine import scan_directory, scan_source
from slopguard.audit.ollama_slop import default_slop_audit_path, run_real_slop_ollama_audit
from slopguard.demo import DemoShowcasePayload, build_demo_showcase
from slopguard.kernels.native_scan import active_backend_name
from slopguard.types import RealSlopAuditReport, SlopReport


class ScanCodeRequest(BaseModel):
    source: str
    file_path: str = "module.py"
    known_modules: list[str] = Field(default_factory=list)


class ScanRepoRequest(BaseModel):
    root_dir: str


def create_app() -> FastAPI:
    app = FastAPI(
        title="slopguard — Sub-Second C++20 & AST Anti-Slop Verifier + MCP Server",
        version="1.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "slopguard",
            "version": "1.0.0",
            "kernel_backend": active_backend_name(),
        }

    @app.get("/api/v1/demo", response_model=DemoShowcasePayload)
    def api_demo() -> DemoShowcasePayload:
        return build_demo_showcase()

    @app.post("/api/v1/scan", response_model=SlopReport)
    def api_scan(req: ScanCodeRequest) -> SlopReport:
        return scan_source(
            req.source,
            file_path=req.file_path,
            known_modules=set(req.known_modules) or None,
        )

    @app.post("/api/v1/scan-repo", response_model=SlopReport)
    def api_scan_repo(req: ScanRepoRequest) -> SlopReport:
        return scan_directory(Path(req.root_dir))

    @app.get("/api/v1/audit/ollama", response_model=RealSlopAuditReport)
    def api_audit_ollama(refresh: bool = False) -> RealSlopAuditReport:
        art = default_slop_audit_path()
        if not refresh and art.exists():
            return RealSlopAuditReport.model_validate_json(art.read_text(encoding="utf-8"))
        return run_real_slop_ollama_audit(allow_offline_replay=True)

    ui_dist = Path(__file__).resolve().parents[3] / "ui" / "dist"
    assets_dir = ui_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/", response_model=None)
    def serve_spa() -> FileResponse | HTMLResponse:
        index_html = ui_dist / "index.html"
        if index_html.exists():
            return FileResponse(str(index_html))
        return HTMLResponse(
            "<h1>slopguard API Online</h1><p>Build UI via <code>cd ui && npm run build</code>.</p>"
        )

    return app
