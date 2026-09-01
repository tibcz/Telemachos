"""Run a downloaded GGUF locally, using the llama.cpp server in the bundle.

A model picker that downloads several gigabytes and then leaves the user to
find a way to run it is not a feature. Telemachos ships llama.cpp's
``llama-server``, built with Metal, and starts it on demand against a model the
user downloaded.

The server binds loopback on llama.cpp's default port, which is already one of
the ports src/model_discovery.py probes — so once it is up the model appears in
the normal model list with no extra wiring.

Everything here degrades rather than fails: if the bundled binary is absent
(a build where llama.cpp did not compile, or a source checkout), local serving
reports itself unavailable and the rest of the app is unaffected. Ollama and
LM Studio, if the user runs them, are discovered independently of this.
"""

import logging
import os
import shutil
import subprocess
import threading
import time

from src.runtime_paths import get_app_root

logger = logging.getLogger(__name__)

# llama.cpp's own default. model_discovery already probes it.
DEFAULT_PORT = int(os.getenv("TELEMACHOS_LLAMA_PORT", "8080"))

_process = None
_current = None
_lock = threading.Lock()


def server_binary():
    """Path to llama-server, or None when this build has no local runtime.

    The app shell passes the bundled path explicitly; the searched locations
    cover a source checkout and a developer's own build.
    """
    explicit = os.getenv("TELEMACHOS_LLAMA_SERVER")
    if explicit and os.path.isfile(explicit) and os.access(explicit, os.X_OK):
        return explicit

    root = get_app_root()
    candidates = [
        # Inside the app bundle: engine payload sits in Resources/engine, the
        # runtime alongside it in Resources/llama.
        os.path.join(root, "..", "..", "llama", "llama-server"),
        os.path.join(root, "..", "llama", "llama-server"),
        os.path.join(root, "llama", "llama-server"),
    ]
    for candidate in candidates:
        resolved = os.path.normpath(candidate)
        if os.path.isfile(resolved) and os.access(resolved, os.X_OK):
            return resolved

    return shutil.which("llama-server")


def available():
    return server_binary() is not None


def status():
    with _lock:
        running = _process is not None and _process.poll() is None
        return {
            "available": available(),
            "running": running,
            "tier": _current if running else None,
            "port": DEFAULT_PORT if running else None,
            "base_url": "http://127.0.0.1:%d/v1" % DEFAULT_PORT if running else None,
        }


def stop():
    """Stop the running server, escalating only if it ignores SIGTERM."""
    global _process, _current
    with _lock:
        process, _process, _current = _process, None, None

    if process is None or process.poll() is not None:
        return False

    process.terminate()
    deadline = time.time() + 8
    while process.poll() is None and time.time() < deadline:
        time.sleep(0.1)
    if process.poll() is None:
        process.kill()
    return True


def start(tier_id, context=None):
    """Serve a downloaded model. Replaces whatever was running before.

    Returns the status dict once the server answers, and raises with a usable
    reason when it cannot start — a silent failure here would show up much
    later as "the model just isn't in the list".
    """
    global _process, _current

    import src.model_catalog as mc

    binary = server_binary()
    if not binary:
        raise RuntimeError(
            "This build has no bundled local runtime. Install Ollama or LM "
            "Studio and Telemachos will pick it up automatically."
        )

    model_path = mc.primary_model_path(tier_id)
    if not model_path:
        raise RuntimeError("that model has not been downloaded yet")

    # One server at a time: two would fight over the port, and a Mac has one
    # pool of unified memory to spend on weights.
    stop()

    tier = mc.tier_by_id(tier_id) or {}
    command = [
        binary,
        "-m", model_path,
        "--host", "127.0.0.1",
        "--port", str(DEFAULT_PORT),
        "-c", str(context or tier.get("context") or 8192),
        # Offload everything to Metal. On Apple Silicon the GPU shares system
        # memory, so there is no separate budget to stay inside.
        "-ngl", "999",
    ]

    logger.info("starting local runtime: %s", " ".join(command))
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    with _lock:
        _process = process
        _current = tier_id

    # Large models take a while to map; wait for the server to actually answer
    # rather than reporting success on a process that is about to die.
    import httpx

    deadline = time.time() + 180
    health = "http://127.0.0.1:%d/health" % DEFAULT_PORT
    while time.time() < deadline:
        if process.poll() is not None:
            with _lock:
                _process, _current = None, None
            raise RuntimeError("the local runtime exited while starting up")
        try:
            if httpx.get(health, timeout=2).status_code == 200:
                logger.info("local runtime ready on port %d", DEFAULT_PORT)
                return status()
        except Exception:
            pass
        time.sleep(1)

    stop()
    raise RuntimeError("the local runtime did not become ready in time")
