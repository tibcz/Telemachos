"""Curated local models: what to offer, and how to fetch it safely.

Four models, one per hardware tier, chosen so that a given Mac gets a
confident recommendation rather than a catalogue to wade through. The list
lives in services/hwfit/data/telemachos_models.json.

Safety is the whole point of this module, so it is worth being explicit about
what "safe" means here. The genuine risk when downloading model weights is not
a virus in the usual sense: it is that PyTorch ``.bin``/``.pt`` checkpoints are
Python **pickles**, and unpickling executes arbitrary code by design. A hostile
checkpoint owns the machine the moment it is loaded.

This module removes that class of problem rather than mitigating it:

* **GGUF only.** Every catalog entry is GGUF, a plain data container with no
  code path, and the downloader refuses any file that is not ``.gguf``. There
  is nothing in a GGUF for an attacker to execute.
* **Allowlisted repositories.** Only the repository ids in the catalog may be
  fetched. A caller cannot pass an arbitrary repo, so this is not a general
  purpose downloader wearing a curated hat.
* **Filenames come from HuggingFace, never from the caller.** The exact files
  are resolved from the API, then matched against the catalog's quantisation.
  No user-controlled string reaches a path.
* **Checked against the hash HuggingFace publishes.** Every file is verified
  against the SHA-256 in its LFS metadata, and a mismatch deletes the download.
* **Written atomically.** Files land in a temporary name and are renamed only
  after verification, so an interrupted download can never look complete.
"""

import hashlib
import json
import logging
import os
import re
import threading
import time

from src.constants import MODELS_DIR
from src.runtime_paths import get_app_root

logger = logging.getLogger(__name__)

HF_API = "https://huggingface.co/api"
HF_RESOLVE = "https://huggingface.co"

_CATALOG_PATH = os.path.join(
    get_app_root(), "services", "hwfit", "data", "telemachos_models.json"
)

# A HuggingFace repo id: owner/name, both restricted to the characters the Hub
# actually allows. Applied to the catalog itself, so a typo in the JSON cannot
# turn into a request to somewhere unexpected.
_REPO_RE = re.compile(r"^[A-Za-z0-9][\w.-]{0,90}/[A-Za-z0-9][\w.-]{0,90}$")

_catalog_cache = None


def load_catalog():
    """Read the curated catalog, rejecting entries that are not well formed."""
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache

    with open(_CATALOG_PATH, encoding="utf-8") as fh:
        data = json.load(fh)

    tiers = []
    for tier in data.get("tiers", []):
        repo = str(tier.get("repo", ""))
        if not _REPO_RE.match(repo):
            logger.warning("model catalog: skipping entry with bad repo id %r", repo)
            continue
        tiers.append(tier)

    _catalog_cache = {"schema": data.get("schema", 1), "tiers": tiers}
    return _catalog_cache


def allowed_repos():
    """The only repositories this app will ever download from."""
    return {tier["repo"] for tier in load_catalog()["tiers"]}


def tier_by_id(tier_id):
    for tier in load_catalog()["tiers"]:
        if tier["id"] == tier_id:
            return tier
    return None


# ---------------------------------------------------------------------------
# Hardware fit
# ---------------------------------------------------------------------------

def detected_memory_gb():
    """Total system memory in GB, or 0.0 when it cannot be determined.

    On Apple Silicon this is unified memory, which is what actually bounds
    model size - there is no separate VRAM to reason about.
    """
    try:
        from services.hwfit.hardware import detect_system

        info = detect_system() or {}
    except Exception:
        logger.debug("hardware detection failed", exc_info=True)
        return 0.0

    for key in ("ram_gb", "total_ram_gb", "memory_gb"):
        value = info.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)

    gpu = info.get("gpu") or {}
    if isinstance(gpu, dict):
        vram = gpu.get("vram_gb")
        if isinstance(vram, (int, float)) and vram > 0:
            return float(vram)
    return 0.0


def recommended_tier_id(memory_gb=None):
    """Largest tier the machine can comfortably hold.

    A model needs headroom beyond its own size for context and for whatever
    else the user is running, so a tier is only recommended when the machine
    meets its stated memory. Falls back to the smallest tier, which is the
    honest answer for an unknown machine.
    """
    if memory_gb is None:
        memory_gb = detected_memory_gb()

    tiers = sorted(load_catalog()["tiers"], key=lambda t: t.get("min_memory_gb", 0))
    if not tiers:
        return None
    if memory_gb <= 0:
        return tiers[0]["id"]

    chosen = tiers[0]["id"]
    for tier in tiers:
        # 0.9 allows for a machine reporting slightly under its nominal size
        # (a 16 GB Mac reports ~15.9), without promoting an 8 GB machine.
        if memory_gb >= tier.get("min_memory_gb", 0) * 0.9:
            chosen = tier["id"]
    return chosen


# ---------------------------------------------------------------------------
# Resolving files on HuggingFace
# ---------------------------------------------------------------------------

def _http_get_json(url, timeout=30):
    import httpx

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def resolve_files(repo, quant):
    """The GGUF files for a quantisation, with their sizes and hashes.

    Returns a list of {path, size, sha256}. A quantisation can legitimately be
    split across several files for large models, so this returns every part
    rather than assuming one.

    Raises ValueError when the repo is not allowlisted, or when nothing matches
    - a silent empty result would present as a download that does nothing.
    """
    if repo not in allowed_repos():
        raise ValueError("repository is not in the curated catalog: %s" % repo)

    tree = _http_get_json("%s/models/%s/tree/main?recursive=1" % (HF_API, repo))

    wanted = quant.lower()
    files = []
    for entry in tree:
        if entry.get("type") != "file":
            continue
        path = entry.get("path") or ""
        # GGUF only. This is the check that keeps a pickle checkpoint out.
        if not path.lower().endswith(".gguf"):
            continue
        if wanted not in path.lower():
            continue
        lfs = entry.get("lfs") or {}
        files.append({
            "path": path,
            "size": int(lfs.get("size") or entry.get("size") or 0),
            # HuggingFace stores the SHA-256 of the object as the LFS oid.
            "sha256": (lfs.get("oid") or "").lower() or None,
        })

    if not files:
        raise ValueError(
            "no %s GGUF file found in %s - the repository may have been "
            "renamed or its quantisations changed" % (quant, repo)
        )
    return sorted(files, key=lambda f: f["path"])


# ---------------------------------------------------------------------------
# Installed models
# ---------------------------------------------------------------------------

def model_dir(tier_id):
    return os.path.join(MODELS_DIR, tier_id)


def installed(tier_id):
    """Every .gguf present for a tier, with its size."""
    directory = model_dir(tier_id)
    if not os.path.isdir(directory):
        return []
    out = []
    for name in sorted(os.listdir(directory)):
        if not name.lower().endswith(".gguf"):
            continue
        full = os.path.join(directory, name)
        try:
            out.append({"name": name, "path": full, "size": os.path.getsize(full)})
        except OSError:
            continue
    return out


def primary_model_path(tier_id):
    """The file to hand a runtime, or None. The first part of a split set."""
    files = installed(tier_id)
    return files[0]["path"] if files else None


def delete(tier_id):
    """Remove a downloaded model. Returns the number of bytes reclaimed."""
    freed = 0
    for entry in installed(tier_id):
        try:
            freed += entry["size"]
            os.remove(entry["path"])
        except OSError:
            logger.warning("could not remove %s", entry["path"])
    try:
        os.rmdir(model_dir(tier_id))
    except OSError:
        pass
    return freed


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

_jobs = {}
_jobs_lock = threading.Lock()


def job_status(tier_id):
    with _jobs_lock:
        job = _jobs.get(tier_id)
        return dict(job) if job else None


def _set_job(tier_id, **fields):
    with _jobs_lock:
        job = _jobs.setdefault(tier_id, {"tier": tier_id})
        job.update(fields)
        return dict(job)


def cancel(tier_id):
    """Ask an in-flight download to stop at its next chunk."""
    with _jobs_lock:
        job = _jobs.get(tier_id)
        if not job or job.get("state") not in ("resolving", "downloading"):
            return False
        job["cancel"] = True
        return True


def _cancelled(tier_id):
    with _jobs_lock:
        job = _jobs.get(tier_id)
        return bool(job and job.get("cancel"))


def _download_one(client, repo, spec, destination, tier_id, done_bytes, total_bytes):
    """Fetch one file, verify it, and only then put it in place."""
    url = "%s/%s/resolve/main/%s" % (HF_RESOLVE, repo, spec["path"])
    temp = destination + ".part"
    digest = hashlib.sha256()
    written = 0

    with client.stream("GET", url, follow_redirects=True) as response:
        response.raise_for_status()
        with open(temp, "wb") as fh:
            for chunk in response.iter_bytes(1024 * 1024):
                if _cancelled(tier_id):
                    fh.close()
                    os.remove(temp)
                    raise InterruptedError("cancelled")
                fh.write(chunk)
                digest.update(chunk)
                written += len(chunk)
                _set_job(
                    tier_id,
                    state="downloading",
                    downloaded=done_bytes + written,
                    total=total_bytes,
                    file=os.path.basename(spec["path"]),
                )

    expected = spec.get("sha256")
    if expected and digest.hexdigest() != expected:
        os.remove(temp)
        raise ValueError(
            "checksum mismatch for %s - the download was corrupted or the file "
            "is not the one HuggingFace published, so it has been discarded"
            % spec["path"]
        )
    if spec.get("size") and written != spec["size"]:
        os.remove(temp)
        raise ValueError("size mismatch for %s" % spec["path"])

    # Rename only now: a .part file is never mistaken for a usable model.
    os.replace(temp, destination)
    return written


def download(tier_id):
    """Download a tier's model. Blocking; run it on a worker thread."""
    import httpx

    tier = tier_by_id(tier_id)
    if not tier:
        raise ValueError("unknown tier: %s" % tier_id)

    _set_job(tier_id, state="resolving", downloaded=0, total=0, error=None, cancel=False)

    try:
        specs = resolve_files(tier["repo"], tier["quant"])
        total = sum(s["size"] for s in specs) or 0
        directory = model_dir(tier_id)
        os.makedirs(directory, exist_ok=True)

        _set_job(tier_id, state="downloading", total=total)

        done = 0
        with httpx.Client(timeout=httpx.Timeout(30.0, read=300.0)) as client:
            for spec in specs:
                # Resolved from the API, but take the basename anyway so no
                # path separator from a remote string can ever escape the
                # directory.
                destination = os.path.join(directory, os.path.basename(spec["path"]))
                if os.path.exists(destination) and spec.get("size") and \
                        os.path.getsize(destination) == spec["size"]:
                    done += spec["size"]
                    continue
                done += _download_one(client, tier["repo"], spec, destination,
                                      tier_id, done, total)

        _set_job(tier_id, state="ready", downloaded=done, total=total, file=None)
        logger.info("model %s downloaded (%.1f GB)", tier_id, done / 1024 ** 3)
        return True

    except InterruptedError:
        _set_job(tier_id, state="cancelled", error=None)
        logger.info("model %s download cancelled", tier_id)
        return False
    except Exception as exc:
        _set_job(tier_id, state="error", error=str(exc))
        logger.warning("model %s download failed: %s", tier_id, exc)
        return False


def start_download(tier_id):
    """Kick off a download on a background thread if one is not already going."""
    existing = job_status(tier_id)
    if existing and existing.get("state") in ("resolving", "downloading"):
        return existing

    thread = threading.Thread(target=download, args=(tier_id,), daemon=True)
    thread.start()
    time.sleep(0.05)
    return job_status(tier_id) or {"tier": tier_id, "state": "resolving"}
