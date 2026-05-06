"""
Background render worker.

RenderWorker is a QObject designed to be moved to a QThread.
It processes a queue of render jobs sequentially, driving
subprocess.Popen and emitting Qt signals for UI updates.
"""

import re
import subprocess
import threading

from PyQt6.QtCore import QObject, pyqtSignal

from harmony import build_command

# Try to match frame progress lines from Harmony's stdout.
# Harmony's exact output format varies by version; we try several patterns.
_FRAME_PATTERNS = [
    re.compile(r'(?:frame|frm)[s:\s]+(\d+)\s*(?:of|/)\s*(\d+)', re.I),
    re.compile(r'rendering\s+(\d+)\s*(?:of|/)\s*(\d+)', re.I),
    re.compile(r'\[(\d+)/(\d+)\]'),
    re.compile(r'(\d+)\s*(?:of|/)\s*(\d+)\s+frame', re.I),
]

# Windows flag: suppress the console window for child processes.
_CREATE_NO_WINDOW = 0x08000000


class RenderWorker(QObject):
    """Sequentially renders a list of jobs and emits progress signals."""

    # Emitted when a job begins (table row index).
    scene_started = pyqtSignal(int)

    # Emitted when a frame count is parsed: (row, current_frame, total_frames).
    frame_progress = pyqtSignal(int, int, int)

    # Emitted when a job finishes: (row, success).
    scene_done = pyqtSignal(int, bool)

    # Emitted for every meaningful line of subprocess output.
    log_line = pyqtSignal(str)

    # Emitted once the entire queue has been processed (or stopped).
    finished = pyqtSignal()

    def __init__(self, queue: list[dict], exe: str, parent=None):
        """
        queue – list of job dicts:
            row          – QTableWidget row index
            xstage       – absolute path to the .xstage file
            frame_range  – None for full scene, or (start, end) tuple
        exe   – path to the Harmony executable
        """
        super().__init__(parent)
        self._queue = queue
        self._exe = exe
        self._proc: subprocess.Popen | None = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------ public

    def stop(self):
        """Request cancellation; kills the active subprocess immediately."""
        self._stop_event.set()
        self._kill_proc()

    # ------------------------------------------------------------------ slot

    def run(self):
        """Entry point — connect QThread.started to this slot."""
        for job in self._queue:
            if self._stop_event.is_set():
                break
            self._run_job(job)
        self.finished.emit()

    # ------------------------------------------------------------------ private

    def _run_job(self, job: dict):
        row = job['row']
        fr = job['frame_range']
        cmd = build_command(
            self._exe,
            job['xstage'],
            fr[0] if fr else None,
            fr[1] if fr else None,
        )

        self.scene_started.emit(row)
        self.log_line.emit('> ' + ' '.join(
            f'"{c}"' if ' ' in c else c for c in cmd
        ))

        success = False
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=0,
                creationflags=_CREATE_NO_WINDOW,
            )
            # Read line-by-line; avoids the deadlock that communicate() can cause.
            while True:
                if self._stop_event.is_set():
                    self._kill_proc()
                    break
                line = self._proc.stdout.readline()
                if not line:
                    break
                line = line.rstrip()
                if line:
                    self.log_line.emit(line)
                for pat in _FRAME_PATTERNS:
                    m = pat.search(line)
                    if m:
                        self.frame_progress.emit(row, int(m.group(1)), int(m.group(2)))
                        break

            self._proc.wait()
            success = (self._proc.returncode == 0) and not self._stop_event.is_set()
        except Exception as exc:
            self.log_line.emit(f'[ERROR] {exc}')
        finally:
            self._proc = None

        self.scene_done.emit(row, success)

    def _kill_proc(self):
        if self._proc and self._proc.poll() is None:
            # kill() calls TerminateProcess on Windows, which is reliable.
            self._proc.kill()
