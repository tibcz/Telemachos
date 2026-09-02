"""The identity of the person using this copy of Telemachos.

Telemachos is a single-user desktop application. It has no accounts to sign
into and nobody else to authenticate against, so the old server notion of a
"user" left the interface showing a hardcoded "User" in the sidebar and
"Unknown" in settings, with an account panel that could not do anything. That
reads as broken software even though nothing is wrong.

What a desktop app actually needs is a profile: a name and an avatar for
display, and a stable owner id for the data. That is all this module provides.

The name is seeded from the macOS account's full name on first run, so the app
already knows who you are before you open settings. It is editable, because
the machine's account name is not always what someone wants to be called.
"""

import json
import logging
import os
import re

from core.atomic_io import atomic_write_text
from src.constants import PROFILE_FILE

logger = logging.getLogger(__name__)

# A stable, non-guessable-free owner key for local single-user data. Kept
# constant so a rename never orphans the data written under the old name.
LOCAL_OWNER = "local"

MAX_NAME_LENGTH = 60

# Avatar tints, chosen to sit correctly on both the light and dark palettes.
AVATAR_COLORS = [
    "#007aff", "#34c759", "#ff9500", "#ff375f",
    "#af52de", "#5ac8fa", "#ffcc00", "#64d2ff",
]


def _os_full_name():
    """The human name on the operating system account, when it has one.

    On macOS the GECOS field holds the full name a person typed when they set
    the Mac up, which is exactly the name to greet them with.
    """
    try:
        import pwd

        entry = pwd.getpwuid(os.getuid())
        gecos = (entry.pw_gecos or "").split(",")[0].strip()
        if gecos:
            return gecos
        if entry.pw_name:
            return entry.pw_name
    except Exception:
        logger.debug("could not read the OS account name", exc_info=True)

    for key in ("USER", "USERNAME", "LOGNAME"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    return "You"


def initials_for(name):
    """One or two letters for the avatar."""
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _avatar_color(name):
    """A stable colour per name, so it does not change on every launch."""
    if not name:
        return AVATAR_COLORS[0]
    return AVATAR_COLORS[sum(ord(c) for c in name) % len(AVATAR_COLORS)]


def _default_profile():
    name = _os_full_name()[:MAX_NAME_LENGTH]
    return {
        "display_name": name,
        "initials": initials_for(name),
        "color": _avatar_color(name),
        "owner": LOCAL_OWNER,
    }


def load():
    """The current profile, seeding one from the OS account if none exists."""
    try:
        with open(PROFILE_FILE, encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict) and stored.get("display_name"):
            name = str(stored["display_name"])[:MAX_NAME_LENGTH]
            return {
                "display_name": name,
                "initials": stored.get("initials") or initials_for(name),
                "color": stored.get("color") or _avatar_color(name),
                "owner": LOCAL_OWNER,
            }
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        logger.warning("profile is unreadable; falling back to the OS account name")

    profile = _default_profile()
    save(profile["display_name"], color=profile["color"])
    return profile


def save(display_name, color=None):
    """Write the profile. Returns the stored form."""
    name = (display_name or "").strip()[:MAX_NAME_LENGTH]
    if not name:
        raise ValueError("a display name cannot be empty")

    profile = {
        "display_name": name,
        "initials": initials_for(name),
        "color": color if color in AVATAR_COLORS else _avatar_color(name),
        "owner": LOCAL_OWNER,
    }
    os.makedirs(os.path.dirname(PROFILE_FILE), exist_ok=True)
    atomic_write_text(PROFILE_FILE, json.dumps(profile, indent=2))
    return profile
