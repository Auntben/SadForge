"""
Scans a root folder for Toon Boom Harmony scenes (.xstage files).

Groups .xstage files by their parent folder.  Each folder is one scene entry;
the scene name is the folder name, and the dropdown lists every .xstage file
found in that folder, sorted newest-first by modification time.
"""

from pathlib import Path


def scan_scenes(root_folder: str) -> list[dict]:
    """
    Return a list of scene dicts, alphabetically sorted by folder name.

    Each dict:
        name      – parent folder name
        versions  – list of version dicts, newest first
            label – .xstage filename (e.g. 'SceneName_v002.xstage')
            path  – absolute path to the .xstage file
            mtime – file modification timestamp (float)
    """
    root = Path(root_folder)
    if not root.is_dir():
        return []

    groups: dict[Path, list] = {}

    for xstage in root.rglob('*.xstage'):
        parent = xstage.parent
        mtime = xstage.stat().st_mtime
        groups.setdefault(parent, []).append({
            'label': xstage.name,
            'path':  str(xstage),
            'mtime': mtime,
        })

    scenes = []
    for folder_path, versions in sorted(groups.items(), key=lambda x: x[0].name.lower()):
        versions.sort(key=lambda v: v['mtime'], reverse=True)
        scenes.append({'name': folder_path.name, 'versions': versions})

    return scenes