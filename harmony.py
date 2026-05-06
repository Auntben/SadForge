"""
Detects installed Toon Boom Harmony versions on Windows and builds
the batch render command.
"""

import os
import re

_SEARCH_ROOTS = [
    r"C:\Program Files (x86)\Toon Boom Animation",
    r"C:\Program Files\Toon Boom Animation",
]

# Checked in priority order; first match wins for each install folder.
_EXE_CANDIDATES = [
    'HarmonyPremium.exe',
    'HarmonyAdvanced.exe',
    'HarmonyEssentials.exe',
    'Harmony.exe',
]


def find_installations() -> list[dict]:
    """
    Return a list of dicts for every detected Harmony installation,
    sorted by version number descending (newest first).

    Each dict:
        name – human-readable folder name, e.g. 'Toon Boom Harmony 22 Premium'
        exe  – absolute path to the Harmony executable
    """
    found = []
    for base in _SEARCH_ROOTS:
        if not os.path.isdir(base):
            continue
        try:
            entries = os.listdir(base)
        except PermissionError:
            continue
        for entry in entries:
            if 'Harmony' not in entry:
                continue
            entry_dir = os.path.join(base, entry)
            if not os.path.isdir(entry_dir):
                continue
            for exe_name in _EXE_CANDIDATES:
                exe = os.path.join(entry_dir, 'win64', 'bin', exe_name)
                if os.path.isfile(exe):
                    found.append({'name': entry, 'exe': exe})
                    break

    def _version_key(inst: dict) -> float:
        m = re.search(r'(\d+(?:\.\d+)?)', inst['name'])
        return float(m.group(1)) if m else 0.0

    found.sort(key=_version_key, reverse=True)
    return found


def build_command(
    exe: str,
    xstage: str,
    start: int | None = None,
    end: int | None = None,
) -> list[str]:
    """
    Return the Harmony batch render command as a list of arguments.

    -batch is Harmony's headless/bulk rendering flag.
    -frames <start> <end> restricts rendering to a frame range.
    """
    cmd = [exe, '-batch']
    if start is not None and end is not None:
        cmd += ['-frames', str(start), str(end)]
    cmd.append(xstage)
    return cmd
