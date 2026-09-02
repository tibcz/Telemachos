#!/usr/bin/env python3
"""Check every curated model against the live HuggingFace API.

Model repositories get renamed, re-quantised and withdrawn. When that happens
the picker would still show the entry and the download would fail at the moment
the user pressed the button - the worst possible time to find out.

CI runs this so a stale catalog fails the build instead. Exits non-zero, naming
the entry and what was wrong, when anything does not resolve.

    python packaging/macos/validate_model_catalog.py
"""

import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CATALOG = os.path.join(ROOT, "services", "models", "catalog.json")
API = "https://huggingface.co/api"


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "telemachos-catalog-check"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def main():
    catalog = json.load(open(CATALOG, encoding="utf-8"))
    tiers = catalog.get("tiers", [])
    if not tiers:
        print("catalog has no tiers", file=sys.stderr)
        return 1

    failures = []
    previous_size = 0.0

    for tier in tiers:
        name = tier.get("id", "?")
        repo = tier.get("repo", "")
        quant = tier.get("quant", "")
        print(f"\n{name}: {repo} [{quant}]")

        try:
            tree = fetch(f"{API}/models/{repo}/tree/main?recursive=1")
        except urllib.error.HTTPError as exc:
            failures.append(f"{name}: {repo} returned HTTP {exc.code}")
            print(f"  FAIL  repository unreachable (HTTP {exc.code})")
            continue
        except Exception as exc:
            failures.append(f"{name}: {repo} could not be queried ({exc})")
            print(f"  FAIL  {exc}")
            continue

        matches = [
            entry for entry in tree
            if entry.get("type") == "file"
            and str(entry.get("path", "")).lower().endswith(".gguf")
            and quant.lower() in str(entry.get("path", "")).lower()
        ]
        if not matches:
            available = sorted({
                str(e.get("path")) for e in tree
                if str(e.get("path", "")).lower().endswith(".gguf")
            })
            failures.append(f"{name}: no {quant} GGUF in {repo}")
            print(f"  FAIL  no {quant} GGUF found. Available: {available[:8] or 'none'}")
            continue

        total = sum(int((e.get("lfs") or {}).get("size") or e.get("size") or 0) for e in matches)
        total_gb = total / 1024 ** 3
        hashed = sum(1 for e in matches if (e.get("lfs") or {}).get("oid"))

        print(f"  ok    {len(matches)} file(s), {total_gb:.1f} GB, {hashed} with a published SHA-256")
        for entry in matches[:3]:
            print(f"        {entry['path']}")

        if hashed != len(matches):
            # Without a published hash there is nothing to verify a download
            # against, which is the guarantee the picker advertises.
            failures.append(f"{name}: {len(matches) - hashed} file(s) have no SHA-256")
            print("  FAIL  some files have no published checksum")

        # The catalog's stated size is what the user decides on; drifting far
        # from reality is its own kind of broken.
        claimed = float(tier.get("approx_size_gb") or 0)
        if claimed and abs(total_gb - claimed) / claimed > 0.25:
            failures.append(f"{name}: catalog says {claimed} GB, actual {total_gb:.1f} GB")
            print(f"  FAIL  size drift: catalog says {claimed} GB, actual {total_gb:.1f} GB")

        if total_gb <= previous_size:
            failures.append(f"{name}: not larger than the tier below it")
            print("  FAIL  tier is not larger than the previous one")
        previous_size = total_gb

    print("\n" + "=" * 60)
    if failures:
        print(f"{len(failures)} problem(s):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"all {len(tiers)} catalog entries resolve on HuggingFace")
    return 0


if __name__ == "__main__":
    sys.exit(main())
