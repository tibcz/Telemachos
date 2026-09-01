# routes/model_catalog_routes.py
"""API for the curated local-model picker.

Four models, one per hardware tier, downloaded from HuggingFace. The safety
rules — GGUF only, allowlisted repositories, HuggingFace-published checksums,
atomic writes — live in src/model_catalog.py; this module is the HTTP surface
over them and deliberately adds no way around them. In particular there is no
endpoint that takes a repository or a filename: the only thing a caller can
name is a tier id, which is matched against the catalog.
"""

import logging

from fastapi import APIRouter, HTTPException, Request

from src.auth_helpers import require_user

logger = logging.getLogger(__name__)


def _tier_view(catalog_tier, mc):
    """Everything the UI needs about one tier."""
    tier_id = catalog_tier["id"]
    files = mc.installed(tier_id)
    job = mc.job_status(tier_id) or {}
    return {
        **{k: v for k, v in catalog_tier.items() if not k.startswith("_")},
        "installed": bool(files),
        "installed_bytes": sum(f["size"] for f in files),
        "files": [f["name"] for f in files],
        "state": job.get("state"),
        "downloaded": job.get("downloaded", 0),
        "total": job.get("total", 0),
        "current_file": job.get("file"),
        "error": job.get("error"),
    }


def setup_model_catalog_routes() -> APIRouter:
    router = APIRouter(prefix="/api/local-models", tags=["local-models"])

    @router.get("")
    async def list_models(request: Request):
        """The catalog, what is installed, and which tier suits this machine."""
        require_user(request)
        import src.model_catalog as mc

        memory_gb = mc.detected_memory_gb()
        return {
            "memory_gb": round(memory_gb, 1),
            "recommended": mc.recommended_tier_id(memory_gb),
            "models_dir": mc.MODELS_DIR,
            "tiers": [_tier_view(t, mc) for t in mc.load_catalog()["tiers"]],
        }

    # Declared before the /{tier_id}/... routes below. FastAPI matches in
    # declaration order, so with these last the parameterised route would
    # swallow /runtime/status as tier_id="runtime" and 404.
    @router.get("/runtime/status")
    async def runtime_status(request: Request):
        """Whether a local model is being served, and where."""
        require_user(request)
        import src.local_runtime as rt

        return rt.status()

    @router.post("/{tier_id}/serve")
    async def serve(tier_id: str, request: Request):
        """Start serving a downloaded model on loopback.

        Once it is up, the app's normal model discovery finds it on llama.cpp's
        default port, so it appears in the model list like any other endpoint.
        """
        require_user(request)
        import src.local_runtime as rt
        import src.model_catalog as mc

        if not mc.tier_by_id(tier_id):
            raise HTTPException(404, "unknown model tier")
        try:
            return rt.start(tier_id)
        except RuntimeError as exc:
            raise HTTPException(400, str(exc))

    @router.post("/runtime/stop")
    async def runtime_stop(request: Request):
        require_user(request)
        import src.local_runtime as rt

        return {"stopped": rt.stop()}

    @router.post("/{tier_id}/download")
    async def start(tier_id: str, request: Request):
        require_user(request)
        import src.model_catalog as mc

        if not mc.tier_by_id(tier_id):
            raise HTTPException(404, "unknown model tier")
        return mc.start_download(tier_id)

    @router.get("/{tier_id}/status")
    async def status(tier_id: str, request: Request):
        require_user(request)
        import src.model_catalog as mc

        if not mc.tier_by_id(tier_id):
            raise HTTPException(404, "unknown model tier")
        return mc.job_status(tier_id) or {"tier": tier_id, "state": None}

    @router.post("/{tier_id}/cancel")
    async def cancel(tier_id: str, request: Request):
        require_user(request)
        import src.model_catalog as mc

        if not mc.tier_by_id(tier_id):
            raise HTTPException(404, "unknown model tier")
        return {"cancelled": mc.cancel(tier_id)}

    @router.delete("/{tier_id}")
    async def remove(tier_id: str, request: Request):
        require_user(request)
        import src.model_catalog as mc

        if not mc.tier_by_id(tier_id):
            raise HTTPException(404, "unknown model tier")
        return {"freed_bytes": mc.delete(tier_id)}

    return router
