# Telemachos

A self-contained AI workspace for Apple Silicon Macs. Chat, agents, deep
research, documents, email, notes, tasks, calendar, and a local vector memory —
in one application you download and open.

There is no server to run, no Python to install, no Docker, no repository to
clone, and no address to type in. Telemachos carries its own engine inside the
app bundle, starts it when you open the app, and stops it when you quit.

---

## Install

1. Download `Telemachos.dmg` from the [Releases page](../../releases), or from
   the artifact of a [Build Telemachos (macOS ARM)](../../actions) run.
2. Open the disk image and drag **Telemachos** to Applications.
3. **Right-click** Telemachos in Applications, choose **Open**, then **Open**
   again in the dialog that appears.

That third step is a one-time thing, and it is worth understanding rather than
just clicking through. This build is signed *ad-hoc* — a real cryptographic
signature, but one made with no Apple Developer certificate behind it. macOS
therefore cannot tie the app to a registered developer and asks you to confirm
you meant to open it. After you confirm once, it opens normally forever.

If you prefer the terminal, this does the same thing:

```
xattr -dr com.apple.quarantine /Applications/Telemachos.app
```

Requires macOS 13 or later on an Apple Silicon Mac (M1 and up).

## First launch

Opening the app shows a start-up screen while the engine initialises its
database and vector store. First launch takes longer than later ones — this is
the only time that setup happens.

Then you need to give it a model to think with. Open **Settings** and add an API
key for whichever provider you use (Anthropic, OpenAI, and the other supported
providers). If you already run **Ollama** or **LM Studio** locally, Telemachos
finds them without any configuration.

## Local models

Telemachos can run a model on your Mac with nothing leaving the machine. Open
**Local Models** in the sidebar: it reads how much memory this Mac has and
recommends one of four, then downloads it and serves it locally.

| Tier | Suits | Model | Size |
|---|---|---|---|
| Light | 8 GB Mac | Gemma 3 4B, Q4_K_M | ~2.6 GB |
| Balanced | 16 GB Mac | Gemma 3 12B, Q4_K_M | ~7.3 GB |
| Strong | 32 GB Mac | Gemma 3 27B, Q4_K_M | ~16 GB |
| Maximum | 64 GB Mac | Gemma 3 27B, Q8_0 | ~29 GB |

The app bundles llama.cpp's server, built with Metal, so a downloaded model
runs without installing anything else. If you already use Ollama or LM Studio,
those are detected separately and keep working.

### Why these downloads are safe

The real risk in downloading model weights is not a virus in the usual sense.
PyTorch `.bin` and `.pt` checkpoints are Python **pickles**, and unpickling
executes arbitrary code by design — a hostile checkpoint owns the machine the
moment it loads. Telemachos removes that possibility rather than warning about
it:

- **GGUF only.** Every model here is GGUF, a plain data container with no code
  path. The downloader refuses any other format, so a pickle cannot be fetched
  even if one sits in the same repository.
- **Allowlisted repositories.** Only the repositories listed on the page can be
  downloaded from. There is no endpoint that accepts an arbitrary repo.
- **Filenames come from HuggingFace, never from the caller,** so no
  user-controlled string reaches a path.
- **Checked against HuggingFace's own SHA-256,** and a mismatch is deleted
  rather than kept.
- **Written atomically,** so an interrupted download is never mistaken for a
  usable model.

CI re-checks every catalog entry against the live HuggingFace API on each
build, so a renamed or withdrawn model fails the build instead of shipping as
a button that dies when you press it.

## Appearance

Telemachos follows your Mac. Set macOS to Light and the app is light; set it to
Dark and it follows. Choosing a theme yourself overrides that, and the picker
carries a range of light and dark themes.

## Where your data lives

Everything is in one folder:

```
~/Library/Application Support/Telemachos
```

Conversations, documents, notes, mail, uploads, the vector index and the logs
all live there. Nothing is written inside the application bundle, so replacing
the app with a newer build never touches your data. **Open Data Folder** in the
app menu takes you straight there, and backing up that one folder backs up
everything.

To start completely fresh, quit the app and delete that folder.

## How it works

Telemachos is two pieces in one bundle:

- **The shell** — a native Swift application. It reserves a loopback port,
  starts the engine, waits for it to report itself genuinely ready, and hosts
  the workspace in a `WKWebView`. It owns the window, the menus, downloads,
  microphone access and shutdown.
- **The engine** — the Telemachos workspace, frozen with PyInstaller into
  `Contents/Resources/engine`. It binds `127.0.0.1` on a port the shell picks,
  and is not reachable from anywhere else on the network.

Two things make it genuinely standalone rather than a wrapper around a local
server you still have to run:

- **The vector store runs in-process.** Upstream Telemachos talks to ChromaDB over
  HTTP as a separate service. `src/chroma_client.py` gained an embedded mode
  that uses an in-process persistent client instead, so RAG and semantic memory
  work with nothing else installed.
- **The engine can act as its own interpreter.** Telemachos starts helper
  processes — the built-in MCP servers, the agent's Python tool — with
  `sys.executable`. Inside a frozen bundle that path *is* the engine, so an
  unguarded spawn would relaunch the whole app. The entry script in
  `packaging/macos/telemachos_engine.py` recognises the `python …` argument
  shapes the app uses and runs them, which keeps those features working without
  changing any of the call sites.

Some optional features still need something else on your Mac. Browser
automation uses the Playwright MCP server and needs Node installed; without it
that one tool is simply absent and everything else works.

## Building it yourself

The build runs on an Apple Silicon Mac with the Xcode command line tools and
Python 3.11+:

```
./packaging/macos/build.sh
```

It produces `dist/Telemachos.app` and `dist/Telemachos.dmg`. The same script is
what CI runs, so a local build and a released build are the same build.

To have GitHub build it instead, run the **Build Telemachos (macOS ARM)**
workflow from the Actions tab. It compiles on a macOS ARM runner, verifies the
signature and architecture, boots the packaged engine and requires it to report
ready, then uploads the disk image. Tick *release* (or push a `v*` tag) to
publish it to Releases.

Layout of the packaging code:

```
packaging/macos/
  build.sh                     assemble, sign ad-hoc, package the .dmg
  telemachos_engine.py         frozen entry point: interpreter dispatch, paths, uvicorn
  TelemachosEngine.spec        PyInstaller spec
  requirements-standalone.txt  runtime dependencies for the bundle
  icon.png                     source art for the app icon
  TelemachosShell/             the native Swift application
```

## Licence and attribution

Telemachos is built on [Odysseus](https://github.com/odysseus-dev/odysseus) and
is a modified version of it. Telemachos is licensed under the GNU Affero General
Public License, version 3 or later, and Telemachos is distributed under the same
licence — see [LICENSE](LICENSE) and [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md).

The licence texts ship inside the application as well, and **About Telemachos**
in the app menu links to them.
