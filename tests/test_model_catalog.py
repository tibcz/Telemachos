"""Tests for the curated local-model picker.

The picker's whole claim is that it cannot be talked into downloading
something dangerous, so most of these assert the boundaries rather than the
happy path: an arbitrary repository is refused, a non-GGUF file is never
selected, and a checksum mismatch discards the file instead of keeping it.
"""
import hashlib
import json
import os

import pytest

import src.model_catalog as mc


# ── Catalog shape ──────────────────────────────────────────────────────────

def test_catalog_has_one_entry_per_hardware_tier():
    tiers = mc.load_catalog()["tiers"]
    assert [t["id"] for t in tiers] == ["low", "medium", "strong", "high"]


def test_every_entry_is_gguf_quantised_and_sized():
    for tier in mc.load_catalog()["tiers"]:
        assert tier["repo"].count("/") == 1, tier["id"]
        assert tier["quant"], tier["id"]
        assert tier["approx_size_gb"] > 0, tier["id"]
        assert tier["min_memory_gb"] >= 8, tier["id"]


def test_tiers_get_larger_as_the_hardware_does():
    """A 64 GB Mac must not be offered a smaller model than a 32 GB one."""
    tiers = mc.load_catalog()["tiers"]
    sizes = [t["approx_size_gb"] for t in tiers]
    memories = [t["min_memory_gb"] for t in tiers]
    assert sizes == sorted(sizes), sizes
    assert memories == sorted(memories), memories


def test_a_model_fits_the_memory_its_tier_claims():
    """Weights plus context need headroom; half the machine is the ceiling."""
    for tier in mc.load_catalog()["tiers"]:
        assert tier["approx_size_gb"] <= tier["min_memory_gb"] * 0.55, tier["id"]


# ── Hardware fit ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("memory_gb,expected", [
    (0, "low"),        # unknown machine: the smallest, not a guess
    (8, "low"),
    (15.7, "medium"),  # a 16 GB Mac reports slightly under
    (16, "medium"),
    (24, "medium"),
    (32, "strong"),
    (64, "high"),
    (128, "high"),
])
def test_tier_recommendation_tracks_memory(memory_gb, expected):
    assert mc.recommended_tier_id(memory_gb) == expected


# ── Safety ─────────────────────────────────────────────────────────────────

def test_repositories_outside_the_catalog_are_refused():
    """The allowlist is what stops this being a general-purpose downloader."""
    with pytest.raises(ValueError, match="not in the curated catalog"):
        mc.resolve_files("attacker/anything-at-all", "Q4_K_M")


def test_catalog_repo_ids_are_well_formed():
    """A typo in the JSON must not become a request somewhere unexpected."""
    for repo in mc.allowed_repos():
        assert mc._REPO_RE.match(repo), repo
        assert ".." not in repo and "\\" not in repo


def test_only_gguf_files_are_ever_selected(monkeypatch):
    """A pickle checkpoint in the same repo must never be chosen.

    This is the actual attack this design prevents: .bin/.pt are Python
    pickles and execute code when loaded.
    """
    repo = sorted(mc.allowed_repos())[0]
    monkeypatch.setattr(mc, "_http_get_json", lambda url, timeout=30: [
        {"type": "file", "path": "pytorch_model.bin", "size": 10, "lfs": {"oid": "a" * 64, "size": 10}},
        {"type": "file", "path": "model-Q4_K_M.pt", "size": 10, "lfs": {"oid": "b" * 64, "size": 10}},
        {"type": "file", "path": "evil-Q4_K_M.safetensors", "size": 10, "lfs": {"oid": "c" * 64, "size": 10}},
        {"type": "file", "path": "model-Q4_K_M.gguf", "size": 42, "lfs": {"oid": "d" * 64, "size": 42}},
    ])
    files = mc.resolve_files(repo, "Q4_K_M")
    assert [f["path"] for f in files] == ["model-Q4_K_M.gguf"]


def test_a_repo_without_the_wanted_quant_raises(monkeypatch):
    """Better a clear error than a button that silently does nothing."""
    repo = sorted(mc.allowed_repos())[0]
    monkeypatch.setattr(mc, "_http_get_json", lambda url, timeout=30: [
        {"type": "file", "path": "model-Q2_K.gguf", "size": 1, "lfs": {"oid": "e" * 64, "size": 1}},
    ])
    with pytest.raises(ValueError, match="no Q4_K_M GGUF"):
        mc.resolve_files(repo, "Q4_K_M")


def test_checksum_mismatch_discards_the_download(monkeypatch, tmp_path):
    """A corrupted or substituted file must not be left on disk."""
    payload = b"not the real weights"
    wrong_hash = hashlib.sha256(b"something else").hexdigest()

    class _Response:
        def raise_for_status(self): pass
        def iter_bytes(self, _n): yield payload
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Client:
        def stream(self, *a, **k): return _Response()

    destination = tmp_path / "model.gguf"
    spec = {"path": "model.gguf", "size": len(payload), "sha256": wrong_hash}

    monkeypatch.setattr(mc, "_cancelled", lambda _t: False)
    monkeypatch.setattr(mc, "_set_job", lambda *a, **k: {})

    with pytest.raises(ValueError, match="checksum mismatch"):
        mc._download_one(_Client(), "owner/repo", spec, str(destination), "low", 0, len(payload))

    assert not destination.exists()
    assert not (tmp_path / "model.gguf.part").exists()


def test_a_verified_download_is_only_named_once_complete(monkeypatch, tmp_path):
    """Until it verifies it stays a .part, so a partial file is never usable."""
    payload = b"pretend gguf bytes"
    spec = {
        "path": "model.gguf",
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }

    class _Response:
        def raise_for_status(self): pass
        def iter_bytes(self, _n): yield payload
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Client:
        def stream(self, *a, **k): return _Response()

    destination = tmp_path / "model.gguf"
    monkeypatch.setattr(mc, "_cancelled", lambda _t: False)
    monkeypatch.setattr(mc, "_set_job", lambda *a, **k: {})

    written = mc._download_one(_Client(), "owner/repo", spec, str(destination), "low", 0, len(payload))
    assert written == len(payload)
    assert destination.read_bytes() == payload
    assert not (tmp_path / "model.gguf.part").exists()


def test_unknown_tier_has_no_entry():
    assert mc.tier_by_id("../../etc/passwd") is None
    assert mc.tier_by_id("nonsense") is None
