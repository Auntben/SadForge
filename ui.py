"""
Main application window for the Harmony Render Queue.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTableWidget, QTableWidgetItem,
    QComboBox, QProgressBar, QTextEdit, QRadioButton, QSpinBox,
    QGroupBox, QHeaderView, QSplitter, QButtonGroup,
)
from PyQt6.QtCore import Qt, QThread
from PyQt6.QtGui import QColor, QBrush, QFont

from scanner import scan_scenes
from harmony import find_installations
from worker import RenderWorker

# ── Status states ─────────────────────────────────────────────────────────────

PENDING     = 'pending'
IN_PROGRESS = 'in_progress'
SUCCESS     = 'success'
FAILED      = 'failed'

_STATUS = {
    PENDING:     ('○  Pending',   '#9E9E9E'),
    IN_PROGRESS: ('◉  Rendering', '#2196F3'),
    SUCCESS:     ('✓  Done',      '#4CAF50'),
    FAILED:      ('✗  Failed',    '#F44336'),
}

_ROW_HIGHLIGHT   = QBrush(QColor('#E3F2FD'))
_ROW_TRANSPARENT = QBrush(QColor(0, 0, 0, 0))

# ── Table column indices ───────────────────────────────────────────────────────

COL_STATUS  = 0
COL_NAME    = 1
COL_VERSION = 2
COL_FRAMES  = 3


# ── Custom widgets ─────────────────────────────────────────────────────────────

class FrameRangeWidget(QWidget):
    """Inline widget for choosing full-scene or a custom start/end frame."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(5)

        self._group = QButtonGroup(self)
        self._full  = QRadioButton('Full Scene')
        self._range = QRadioButton('Range')
        self._full.setChecked(True)
        self._group.addButton(self._full)
        self._group.addButton(self._range)

        self._start = QSpinBox()
        self._start.setRange(1, 999_999)
        self._start.setValue(1)
        self._start.setFixedWidth(72)
        self._start.setEnabled(False)

        self._end = QSpinBox()
        self._end.setRange(1, 999_999)
        self._end.setValue(100)
        self._end.setFixedWidth(72)
        self._end.setEnabled(False)

        self._full.toggled.connect(self._on_toggle)

        for w in (self._full, self._range,
                  QLabel('Start:'), self._start,
                  QLabel('End:'), self._end):
            lay.addWidget(w)
        lay.addStretch()

    def _on_toggle(self, full_checked: bool):
        self._start.setEnabled(not full_checked)
        self._end.setEnabled(not full_checked)

    @property
    def frame_range(self) -> tuple[int, int] | None:
        """None means render the full scene; otherwise (start, end)."""
        if self._full.isChecked():
            return None
        return (self._start.value(), self._end.value())


# ── Main window ────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('SadForge')
        self.resize(1180, 800)

        self._scenes:   list[dict] = []   # from scanner
        self._row_refs: list[dict] = []   # widget refs per table row
        self._installs: list[dict] = []   # harmony install dicts
        self._thread:   QThread | None = None
        self._worker:   RenderWorker | None = None
        self._folder:   str = ''

        self._build_ui()
        self._detect_harmony()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(8)

        # ── Title ─────────────────────────────────────────────────────────────
        title_bar = QHBoxLayout()
        title_lbl = QLabel('SadForge')
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        ver_lbl = QLabel('v26')
        ver_lbl.setStyleSheet('color:#9E9E9E; font-size:13px;')
        ver_lbl.setAlignment(Qt.AlignmentFlag.AlignBottom)
        title_bar.addWidget(title_lbl)
        title_bar.addWidget(ver_lbl)
        title_bar.addStretch()
        vbox.addLayout(title_bar)

        # ── Step 1: folder selection ──────────────────────────────────────────
        folder_box = QGroupBox('Step 1 — Select Scenes Folder')
        folder_lay = QHBoxLayout(folder_box)
        browse_btn = QPushButton('Browse…')
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_folder)
        self._folder_lbl = QLabel('No folder selected')
        self._folder_lbl.setStyleSheet('color:#888; font-style:italic;')
        folder_lay.addWidget(browse_btn)
        folder_lay.addWidget(self._folder_lbl, 1)
        vbox.addWidget(folder_box)

        # ── Splitter: table on top, controls+log below ────────────────────────
        splitter = QSplitter(Qt.Orientation.Vertical)

        # ── Step 2: scene queue table ─────────────────────────────────────────
        table_grp = QGroupBox('Step 2 — Review Scene Queue')
        tg_lay = QVBoxLayout(table_grp)

        tb_bar = QHBoxLayout()
        self._remove_btn = QPushButton('Remove Selected')
        self._remove_btn.setEnabled(False)
        self._remove_btn.clicked.connect(self._remove_selected)
        refresh_btn = QPushButton('Refresh')
        refresh_btn.clicked.connect(self._refresh)
        self._clear_btn = QPushButton('Clear Queue')
        self._clear_btn.setEnabled(False)
        self._clear_btn.clicked.connect(self._clear_queue)
        self._count_lbl = QLabel('0 scenes')
        tb_bar.addWidget(self._remove_btn)
        tb_bar.addWidget(refresh_btn)
        tb_bar.addWidget(self._clear_btn)
        tb_bar.addStretch()
        tb_bar.addWidget(self._count_lbl)
        tg_lay.addLayout(tb_bar)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ['Status', 'Scene Name', 'Scene File', 'Frame Range']
        )
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(COL_STATUS,  QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(COL_NAME,    QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(COL_VERSION, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(COL_FRAMES,  QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(COL_STATUS,  125)
        self._table.setColumnWidth(COL_VERSION, 220)
        self._table.setColumnWidth(COL_FRAMES,  370)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setDefaultSectionSize(38)
        self._table.setAlternatingRowColors(True)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        tg_lay.addWidget(self._table)
        splitter.addWidget(table_grp)

        # ── Step 3: render controls + log ─────────────────────────────────────
        bot = QWidget()
        bot_lay = QVBoxLayout(bot)
        bot_lay.setContentsMargins(0, 0, 0, 0)
        bot_lay.setSpacing(6)

        ctrl_grp = QGroupBox('Step 3 — Render Queue')
        ctrl_lay = QHBoxLayout(ctrl_grp)

        ctrl_lay.addWidget(QLabel('Harmony:'))
        self._ver_combo = QComboBox()
        self._ver_combo.setMinimumWidth(310)
        ctrl_lay.addWidget(self._ver_combo)
        ctrl_lay.addSpacing(14)

        self._prog_lbl = QLabel()
        self._prog_lbl.setVisible(False)
        ctrl_lay.addWidget(self._prog_lbl)

        self._prog_bar = QProgressBar()
        self._prog_bar.setRange(0, 0)
        self._prog_bar.setTextVisible(True)
        self._prog_bar.setFormat('Idle')
        self._prog_bar.setMinimumWidth(230)
        self._prog_bar.setVisible(False)
        ctrl_lay.addWidget(self._prog_bar)

        ctrl_lay.addStretch()

        self._start_btn = QPushButton('▶  Start Render Queue')
        self._start_btn.setFixedHeight(36)
        self._start_btn.setStyleSheet(
            'QPushButton{background:#4CAF50;color:white;font-weight:bold;'
            'border-radius:4px;padding:0 16px;}'
            'QPushButton:hover{background:#43A047;}'
            'QPushButton:disabled{background:#BDBDBD;}'
        )
        self._start_btn.clicked.connect(self._start_render)
        ctrl_lay.addWidget(self._start_btn)

        self._stop_btn = QPushButton('■  Stop')
        self._stop_btn.setFixedHeight(36)
        self._stop_btn.setEnabled(False)
        self._stop_btn.setStyleSheet(
            'QPushButton{background:#F44336;color:white;font-weight:bold;'
            'border-radius:4px;padding:0 16px;}'
            'QPushButton:hover{background:#E53935;}'
            'QPushButton:disabled{background:#BDBDBD;}'
        )
        self._stop_btn.clicked.connect(self._stop_render)
        ctrl_lay.addWidget(self._stop_btn)

        bot_lay.addWidget(ctrl_grp)

        # Log
        log_grp = QGroupBox('Render Log')
        log_lay = QVBoxLayout(log_grp)
        log_bar = QHBoxLayout()
        log_bar.addStretch()
        clear_btn = QPushButton('Clear Log')
        clear_btn.setFixedWidth(75)
        clear_btn.clicked.connect(lambda: self._log.clear())
        log_bar.addWidget(clear_btn)
        log_lay.addLayout(log_bar)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont('Consolas', 9))
        log_lay.addWidget(self._log)
        bot_lay.addWidget(log_grp)

        splitter.addWidget(bot)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        vbox.addWidget(splitter)

    # ── Harmony detection ──────────────────────────────────────────────────────

    def _detect_harmony(self):
        self._installs = find_installations()
        self._ver_combo.clear()
        if self._installs:
            for inst in self._installs:
                self._ver_combo.addItem(inst['name'], inst['exe'])
            self._append_log(
                f'Found {len(self._installs)} Harmony installation(s). '
                f'Latest: <b>{self._installs[0]["name"]}</b>'
            )
        else:
            self._ver_combo.addItem('No Harmony installations found', None)
            self._append_log(
                '<span style="color:#F44336">No Toon Boom Harmony installations found. '
                'Check that Harmony is installed in Program Files.</span>'
            )

    # ── Folder / scene loading ─────────────────────────────────────────────────

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Select Scenes Folder')
        if folder:
            self._folder = folder
            self._folder_lbl.setText(folder)
            self._folder_lbl.setStyleSheet('')
            self._load_scenes()

    def _refresh(self):
        if self._folder:
            self._load_scenes()

    def _load_scenes(self):
        self._scenes = scan_scenes(self._folder)
        self._row_refs = []
        self._table.setRowCount(0)
        for scene in self._scenes:
            self._append_row(scene)
        self._update_count()
        n = len(self._scenes)
        if n == 0:
            self._append_log(
                f'<span style="color:#FF9800">No .xstage files found in {self._folder}</span>'
            )
        else:
            self._append_log(f'Loaded <b>{n}</b> scene(s) from {self._folder}')

    def _append_row(self, scene: dict):
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setRowHeight(row, 38)

        # Status label
        status_lbl = QLabel(_STATUS[PENDING][0])
        status_lbl.setStyleSheet(
            f'color:{_STATUS[PENDING][1]};font-weight:bold;padding-left:8px;'
        )
        status_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._table.setCellWidget(row, COL_STATUS, status_lbl)

        # Scene name (non-editable item so we can highlight the row)
        name_item = QTableWidgetItem(scene['name'])
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, COL_NAME, name_item)

        # Version dropdown — first item is the latest (scanner sorts newest-first)
        ver_combo = QComboBox()
        for v in scene['versions']:
            ver_combo.addItem(v['label'], v['path'])
        self._table.setCellWidget(row, COL_VERSION, ver_combo)

        # Frame range widget
        fr_widget = FrameRangeWidget()
        self._table.setCellWidget(row, COL_FRAMES, fr_widget)

        self._row_refs.append({
            'status_lbl': status_lbl,
            'ver_combo':  ver_combo,
            'fr_widget':  fr_widget,
        })

    # ── Table actions ──────────────────────────────────────────────────────────

    def _on_selection_changed(self):
        has_sel = len(self._table.selectedItems()) > 0
        self._remove_btn.setEnabled(has_sel and not self._is_rendering())

    def _remove_selected(self):
        rows = sorted(
            {idx.row() for idx in self._table.selectedIndexes()},
            reverse=True,
        )
        for r in rows:
            self._table.removeRow(r)
            self._scenes.pop(r)
            self._row_refs.pop(r)
        self._update_count()

    def _clear_queue(self):
        self._table.setRowCount(0)
        self._scenes.clear()
        self._row_refs.clear()
        self._update_count()

    def _update_count(self):
        n = len(self._scenes)
        self._count_lbl.setText(f'{n} scene{"s" if n != 1 else ""} found')
        self._clear_btn.setEnabled(n > 0 and not self._is_rendering())

    # ── Render control ─────────────────────────────────────────────────────────

    def _is_rendering(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def _start_render(self):
        exe = self._ver_combo.currentData()
        if not exe:
            self._append_log(
                '<span style="color:#F44336">No valid Harmony installation selected.</span>'
            )
            return
        if not self._row_refs:
            self._append_log(
                '<span style="color:#F44336">No scenes in the queue.</span>'
            )
            return

        # Reset all rows to pending
        queue = []
        for row, refs in enumerate(self._row_refs):
            self._set_row_status(row, PENDING)
            queue.append({
                'row':         row,
                'xstage':      refs['ver_combo'].currentData(),
                'frame_range': refs['fr_widget'].frame_range,
            })

        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._remove_btn.setEnabled(False)
        self._prog_bar.setVisible(True)
        self._prog_bar.setRange(0, 0)
        self._prog_bar.setFormat('Starting…')
        self._prog_lbl.setVisible(True)
        self._prog_lbl.setText('')

        self._thread = QThread(self)
        self._worker = RenderWorker(queue, exe)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.scene_started.connect(self._on_scene_started)
        self._worker.frame_progress.connect(self._on_frame_progress)
        self._worker.scene_done.connect(self._on_scene_done)
        self._worker.log_line.connect(self._on_log_line)
        self._worker.finished.connect(self._on_queue_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    def _stop_render(self):
        if self._worker:
            self._worker.stop()
        self._stop_btn.setEnabled(False)
        self._append_log('<span style="color:#FF9800">Stop requested — killing current job…</span>')

    # ── Worker signal handlers (main thread) ───────────────────────────────────

    def _on_scene_started(self, row: int):
        self._set_row_status(row, IN_PROGRESS)
        name = self._scenes[row]['name']
        self._prog_lbl.setText(f'Rendering: <b>{name}</b>')
        self._prog_bar.setRange(0, 0)      # indeterminate until frames arrive
        self._prog_bar.setFormat('Rendering…')
        self._table.scrollTo(self._table.model().index(row, COL_NAME))
        self._append_log(f'<span style="color:#2196F3">→ Started: <b>{name}</b></span>')

    def _on_frame_progress(self, row: int, current: int, total: int):
        if total > 0:
            self._prog_bar.setRange(0, total)
            self._prog_bar.setValue(current)
            pct = int(current / total * 100)
            self._prog_bar.setFormat(f'Frame {current} / {total}  ({pct}%)')

    def _on_scene_done(self, row: int, success: bool):
        state = SUCCESS if success else FAILED
        self._set_row_status(row, state)
        name = self._scenes[row]['name']
        color = '#4CAF50' if success else '#F44336'
        word  = 'Completed' if success else 'FAILED'
        self._append_log(f'<span style="color:{color}"><b>{word}:</b> {name}</span>')

    def _on_log_line(self, msg: str):
        # Colour-code WARNING / ERROR lines from Harmony automatically.
        lower = msg.lower()
        if 'error' in lower or 'fatal' in lower:
            msg = f'<span style="color:#F44336">{msg}</span>'
        elif 'warning' in lower or 'warn' in lower:
            msg = f'<span style="color:#FF9800">{msg}</span>'
        self._append_log(msg)

    def _on_queue_finished(self):
        self._thread = None
        self._worker = None
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._remove_btn.setEnabled(len(self._table.selectedItems()) > 0)
        self._prog_bar.setRange(0, 1)
        self._prog_bar.setValue(1)
        self._prog_bar.setFormat('Queue complete')
        self._prog_lbl.setText('<span style="color:#4CAF50"><b>All done!</b></span>')
        self._append_log(
            '<span style="color:#4CAF50"><b>Render queue finished.</b></span>'
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _set_row_status(self, row: int, state: str):
        text, color = _STATUS[state]
        lbl = self._row_refs[row]['status_lbl']
        lbl.setText(text)
        lbl.setStyleSheet(f'color:{color};font-weight:bold;padding-left:8px;')

        # Highlight the name cell to make the active row obvious at a glance.
        name_item = self._table.item(row, COL_NAME)
        if name_item:
            name_item.setBackground(
                _ROW_HIGHLIGHT if state == IN_PROGRESS else _ROW_TRANSPARENT
            )

    def _append_log(self, html: str):
        self._log.append(html)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())
