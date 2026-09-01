"""
chroma_client.py

Singleton ChromaDB client.

Two modes, chosen by environment:

- **embedded** (``CHROMADB_MODE=embedded``) - an in-process
  ``chromadb.PersistentClient`` writing to ``CHROMA_DIR`` under the data
  directory. No socket, no second process, nothing to start. This is what the
  standalone Telemachos.app uses: vector memory and RAG have to work out of
  the box, and a desktop app cannot ask its user to run `docker compose up
  chromadb` first.
- **http** (default) - ``chromadb.HttpClient`` against a standalone ChromaDB
  service. Unchanged behaviour for server/Docker deployments.

Embedded mode needs the full ``chromadb`` package; the HTTP path is happy with
the much lighter ``chromadb-client``. The two ship the same import name, so the
mode is what decides which one you must have installed, not the import.
"""

import os
import socket
import logging

logger = logging.getLogger(__name__)

_client = None

# A short connect probe so an unreachable ChromaDB fails fast instead of
# blocking on the OS connection timeout (~30-60s, WinError 10060 on Windows),
# which otherwise stalls app startup. Tunable via CHROMADB_CONNECT_TIMEOUT.
_CONNECT_TIMEOUT = float(os.getenv("CHROMADB_CONNECT_TIMEOUT", "2.0"))


def embedded_mode() -> bool:
    """True when the vector store should run in-process.

    Read at call time rather than import time so tests (and the settings UI,
    via reset_client()) can flip modes without reimporting the module.
    """
    return os.getenv("CHROMADB_MODE", "").strip().lower() == "embedded"


def _port_open(host: str, port: int, timeout: float = None) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout or _CONNECT_TIMEOUT):
            return True
    except OSError:
        return False


def _import_chromadb():
    """Import chromadb, or raise a RuntimeError naming the right package.

    The install hint differs by mode: embedded needs the full engine, HTTP only
    needs the thin client, and telling someone to install the wrong one of the
    two is a genuinely confusing dead end.
    """
    try:
        import chromadb
    except ImportError as e:
        package = "chromadb" if embedded_mode() else "chromadb-client"
        raise RuntimeError(
            "ChromaDB integration is not installed. Install the optional "
            f"dependency with: pip install {package}"
        ) from e
    return chromadb


def _build_embedded_client(chromadb):
    """In-process persistent client rooted at CHROMA_DIR."""
    from src.constants import CHROMA_DIR

    # PersistentClient does create the directory itself, but doing it here
    # keeps the failure (a read-only or missing parent) attributable to us
    # rather than surfacing from inside chromadb's migration code.
    os.makedirs(CHROMA_DIR, exist_ok=True)

    try:
        from chromadb.config import Settings

        # Telemetry posts to the network on first use. An offline-capable
        # desktop app has no business doing that, and the failure is noisy.
        settings = Settings(anonymized_telemetry=False, is_persistent=True)
        client = chromadb.PersistentClient(path=CHROMA_DIR, settings=settings)
    except ImportError:
        # chromadb-client (the thin HTTP-only package) has no PersistentClient
        # and no chromadb.config. Say so plainly instead of leaking an
        # AttributeError from deep in the import.
        raise RuntimeError(
            "Embedded ChromaDB requires the full `chromadb` package, but only "
            "the HTTP-only `chromadb-client` is installed. Install it with: "
            "pip install chromadb"
        )
    except AttributeError as e:
        raise RuntimeError(
            "Embedded ChromaDB requires the full `chromadb` package, but only "
            "the HTTP-only `chromadb-client` is installed. Install it with: "
            "pip install chromadb"
        ) from e

    logger.info("ChromaDB embedded (in-process): %s", CHROMA_DIR)
    return client


def _build_http_client(chromadb):
    """HTTP client against a standalone ChromaDB service."""
    host = os.getenv("CHROMADB_HOST", "localhost")
    port = int(os.getenv("CHROMADB_PORT", "8100"))

    if not _port_open(host, port):
        raise RuntimeError(
            f"ChromaDB is not reachable at {host}:{port}. Start the ChromaDB "
            f"service (e.g. `docker compose up chromadb`) or set CHROMADB_HOST / "
            f"CHROMADB_PORT to point at a running instance."
        )

    client = chromadb.HttpClient(host=host, port=port)

    # Health check before caching - if the port is open but the service isn't
    # healthy yet (e.g. still starting), don't poison the singleton with a dead
    # client; leave _client unset so the next call retries.
    client.heartbeat()
    logger.info(f"ChromaDB connected: {host}:{port}")
    return client


def get_chroma_client():
    """Get or create the singleton ChromaDB client.

    Raises RuntimeError with a clear install hint if the `chromadb` package
    is not installed - it's an optional dependency (RAG + memory vectors).
    """
    global _client
    if _client is not None:
        return _client

    chromadb = _import_chromadb()

    # Assign to the singleton only after the client is fully built. Both
    # builders raise on failure, and a half-built client must not be cached -
    # the next call has to be free to retry.
    if embedded_mode():
        _client = _build_embedded_client(chromadb)
    else:
        _client = _build_http_client(chromadb)
    return _client


def reset_client():
    """Reset the singleton (e.g. after config change)."""
    global _client
    _client = None
