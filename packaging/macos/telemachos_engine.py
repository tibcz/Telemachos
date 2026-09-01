"""Frozen entrypoint for the Odysseus engine inside the standalone Telemachos.app.

This module is the PyInstaller entry script. It does three jobs, strictly in
this order, because each one depends on the previous having finished:

1. **Act as a Python interpreter when asked to.** Odysseus spawns helper
   processes with ``sys.executable`` — the built-in MCP servers
   (src/builtin_mcp.py) and the agent's Python tool
   (src/agent_tools/subprocess_tools.py). In a source checkout that is a real
   interpreter. Inside a frozen bundle it is *this binary*, so an unguarded
   spawn would relaunch the whole application instead of running the script.
   The dispatcher below emulates the handful of ``python ...`` argument shapes
   the app actually uses, which keeps those call sites working untouched.

2. **Point every persistent path at Application Support.** src/constants.py
   resolves all of its paths at import time from ``ODYSSEUS_DATA_DIR``, so the
   environment has to be settled before anything imports the app.

3. **Serve.** Bind uvicorn to loopback on the port the app shell chose.

The engine is never reachable from outside the machine: it binds 127.0.0.1 on
an ephemeral port that the shell picks and passes in.
"""

import os
import sys


def app_root():
    """Directory that holds app.py, src/, static/ and the rest of the engine.

    Frozen, that is PyInstaller's extraction root; from a source checkout it is
    the repository root two levels above this file. Mirrors
    src/runtime_paths.get_app_root(), which cannot be imported here because
    importing it is precisely what needs the path to already be set up.
    """
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# The app root must be importable before anything reaches for `app` or `src.*`.
# This entry script lives in packaging/macos/, so it is not on sys.path by
# default in a source run, and helper processes re-entering through the
# interpreter dispatch below need it just as much as the server does.
_APP_ROOT = app_root()
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)


# ---------------------------------------------------------------------------
# 1. Interpreter dispatch
# ---------------------------------------------------------------------------

# Interpreter flags that take no value. Odysseus passes -I (isolated mode) when
# it runs the agent's Python tool; the rest are here so an added flag upstream
# doesn't silently turn a child process into a second copy of the app.
_VALUELESS_FLAGS = {"-I", "-s", "-S", "-E", "-u", "-B", "-O", "-OO", "-q", "-v"}


def _describes_interpreter_work(argv):
    """True when argv looks like a `python ...` invocation rather than app args.

    Deliberately conservative: anything unrecognised falls through to serving,
    so a stray argument produces a running app rather than a silent no-op.
    """
    for arg in argv:
        if arg in _VALUELESS_FLAGS:
            continue
        return arg in ("-c", "-m") or arg.endswith(".py")
    return False


def _run_as_interpreter(argv):
    """Emulate `python ...` for the argument shapes Odysseus spawns.

    Writes nothing to stdout of its own: the MCP servers speak JSON-RPC over
    stdout, and a single stray byte there corrupts the protocol stream.
    """
    import runpy

    args = list(argv)
    while args and args[0] in _VALUELESS_FLAGS:
        args.pop(0)
    if not args:
        return 0

    head = args[0]

    if head == "-c":
        code = args[1] if len(args) > 1 else ""
        sys.argv = ["-c"] + args[2:]
        globals_dict = {
            "__name__": "__main__",
            "__doc__": None,
            "__package__": None,
            "__builtins__": __builtins__,
        }
        exec(compile(code, "<string>", "exec"), globals_dict)
        return 0

    if head == "-m":
        if len(args) < 2:
            print("Argument expected for the -m option", file=sys.stderr)
            return 2
        module = args[1]

        # pip cannot work here and never will: the bundle ships a fixed,
        # pre-built set of packages with no interpreter to install into. Say
        # that plainly rather than letting it fail as a missing module.
        if module == "pip":
            print(
                "This is a self-contained build of Telemachos: its Python "
                "packages are fixed at build time and cannot be added to at "
                "runtime.",
                file=sys.stderr,
            )
            return 1

        sys.argv = [module] + args[2:]
        try:
            runpy.run_module(module, run_name="__main__", alter_sys=True)
        except ImportError as exc:
            # Only modules collected at build time exist in the bundle. A
            # one-line reason beats a bootloader traceback.
            print("%s: %s" % (module, exc), file=sys.stderr)
            return 1
        return 0

    # A script path: the built-in MCP servers arrive here.
    sys.argv = list(args)
    runpy.run_path(head, run_name="__main__")
    return 0


# ---------------------------------------------------------------------------
# 2. Environment
# ---------------------------------------------------------------------------

def application_support_dir():
    """Persistent, user-owned home for everything the engine writes.

    The bundle itself is read-only (and is replaced wholesale on update), so no
    state may live inside it. ~/Library/Application Support is the documented
    macOS location for exactly this.
    """
    return os.path.join(
        os.path.expanduser("~"), "Library", "Application Support", "Telemachos"
    )


def configure_environment(port):
    """Settle every environment variable the app reads at import time.

    setdefault throughout, so an operator debugging the bundle can override any
    of it from the outside without editing the app.
    """
    data_dir = os.environ.get("ODYSSEUS_DATA_DIR") or application_support_dir()
    os.makedirs(data_dir, exist_ok=True)
    os.environ["ODYSSEUS_DATA_DIR"] = data_dir

    # Vector store runs in-process. Without this the app would look for a
    # ChromaDB service on localhost:8100 and RAG/semantic memory would be dead
    # on arrival — see src/chroma_client.py.
    os.environ.setdefault("CHROMADB_MODE", "embedded")

    # Single-user desktop app on loopback: there is no second party to
    # authenticate, and a login wall in front of your own laptop is friction
    # with no security value. The engine is not network-reachable.
    os.environ.setdefault("AUTH_ENABLED", "false")

    os.environ.setdefault("APP_BIND", "127.0.0.1")
    os.environ["APP_PORT"] = str(port)

    # Loopback base for the app's own internal API calls (agent tools and
    # background jobs call the running server over HTTP). Without the port it
    # would default to 7000 and talk to nothing.
    os.environ["ODYSSEUS_INTERNAL_BASE"] = "http://127.0.0.1:%d" % port

    # Model weights for local embeddings are downloaded once and cached; keep
    # them with the rest of the user's data rather than in a home-dir dotfile.
    os.environ.setdefault(
        "FASTEMBED_CACHE_PATH", os.path.join(data_dir, "fastembed_cache")
    )
    seed_fastembed_cache(os.environ["FASTEMBED_CACHE_PATH"])

    return data_dir


def seed_fastembed_cache(cache_dir):
    """Copy the embedding model shipped in the bundle into the user's cache.

    Local embeddings power RAG, semantic memory and tool selection. Left to
    itself FastEmbed downloads ~90 MB from HuggingFace the first time any of
    those run, which means a standalone app either stalls on first use or
    silently degrades to keyword matching when the machine is offline. The
    build seeds a copy inside the bundle; this puts it where FastEmbed looks.

    Copied rather than pointed at, because FastEmbed writes locks and temp
    files next to the model and the bundle is read-only. Best-effort: a failure
    here costs a download, not a working app.
    """
    seed = os.path.join(app_root(), "fastembed_seed")
    if not os.path.isdir(seed):
        return False
    try:
        if os.path.isdir(cache_dir) and os.listdir(cache_dir):
            return False
        import shutil

        shutil.copytree(seed, cache_dir, dirs_exist_ok=True)
        return True
    except Exception:
        return False


def configure_logging(data_dir):
    """Send engine logs to a file the app shell can show the user.

    Returns the log path. stderr keeps its stream too, so a build run from a
    terminal still prints normally.
    """
    import logging

    log_dir = os.path.join(data_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "engine.log")

    handlers = [logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.stderr)]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    return log_path


# ---------------------------------------------------------------------------
# 3. Serve
# ---------------------------------------------------------------------------

def _parse_port(argv):
    """Read --port N. Defaults to 0, meaning 'let the OS choose'."""
    for i, arg in enumerate(argv):
        if arg == "--port" and i + 1 < len(argv):
            return int(argv[i + 1])
        if arg.startswith("--port="):
            return int(arg.split("=", 1)[1])
    return int(os.environ.get("TELEMACHOS_PORT", "0"))


def serve(port):
    data_dir = configure_environment(port)
    log_path = configure_logging(data_dir)

    import logging

    log = logging.getLogger("telemachos.engine")
    log.info("Telemachos engine starting")
    log.info("  data dir: %s", data_dir)
    log.info("  log file: %s", log_path)
    log.info("  port:     %d", port)

    import uvicorn
    from app import app

    # The shell always supplies a port it has already reserved, so there is no
    # port-0 path to resolve here.
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info", access_log=False)
    return 0


def main():
    argv = sys.argv[1:]

    if _describes_interpreter_work(argv):
        return _run_as_interpreter(argv)

    port = _parse_port(argv)
    if port <= 0:
        print(
            "telemachos-engine: no port given. The app shell reserves a port "
            "and passes it as --port N.",
            file=sys.stderr,
        )
        return 2
    return serve(port)


if __name__ == "__main__":
    # PyInstaller + multiprocessing: without this, a child process spawned by a
    # dependency re-runs this entry script from the top instead of the worker
    # body. Must come before anything else in __main__.
    import multiprocessing

    multiprocessing.freeze_support()

    sys.exit(main())
