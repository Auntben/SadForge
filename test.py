import subprocess
import os
import sys
import re
import threading
import shutil
import time
import tempfile
import traceback
from PyQt6.QtGui import QIcon, QFont, QColor, QPixmap, QPainter, QIntValidator, QBrush
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QProgressBar, QStackedLayout, QWidget, QMessageBox

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QLabel, QLineEdit, QMessageBox, QComboBox, QTreeWidget, QTreeWidgetItem,
    QTextEdit, QInputDialog, QSpinBox, QHeaderView, QCheckBox
)
from PyQt6.QtCore import Qt, QSize

class ForgeGUI(QWidget):

    # Where we build out the UI elements
    def __init__(self):
        super().__init__()
        # self.setWindowIcon(QIcon(resource_path("SadForge.ico")))
        self.resize(1200, 800)
        self.setWindowTitle("SadForge v26.0")
        self.layout = QVBoxLayout()

        # --- Add large title at the very top ---
        self.title_label = QLabel("Sadforge v26.0")
        font = QFont()
        font.setPointSize(20)
        font.setBold(True)
        self.title_label.setFont(font)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.layout.addWidget(self.title_label)
        # --- End title addition ---

        # --- Add subtitle under the title ---
        self.subtitle_label = QLabel("Toon Boom Harmony Render Queue")
        subtitle_font = QFont()
        subtitle_font.setPointSize(12)
        subtitle_font.setItalic(True)
        self.subtitle_label.setFont(subtitle_font)
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.layout.addWidget(self.subtitle_label)
        # --- End subtitle addition ---
        
        # Add vertical space
        self.layout.addWidget(QLabel(""))  # Blank label for space

        # --- Folder selection row ---
        path_layout = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText("Select a folder to scan for Harmony projects...")
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.select_folder)
        path_layout.addWidget(self.folder_edit)
        path_layout.addWidget(browse_btn)
        self.layout.addLayout(path_layout)

        # --- Scan button and status ---
        scan_layout = QHBoxLayout()
        self.scan_btn = QPushButton("Scan Folder")
        self.scan_btn.clicked.connect(self.scan_folder)
        self.status_label = QLabel("")
        scan_layout.addWidget(self.scan_btn)
        scan_layout.addWidget(self.status_label)
        self.layout.addLayout(scan_layout)

        # Add vertical space
        self.layout.addWidget(QLabel(""))  # Blank label for space

        # --- Results tree ---
        self.tree = QTreeWidget()
        # Four columns: project folder, selector, render options, and status
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Project Folder", "File to Render", "Render Frame Range", "Status"])
        self.tree.setRootIsDecorated(False)        # Prevent expanding/collapsing items on double-click so users don't
        # unintentionally reveal xstage files.
        self.tree.setExpandsOnDoubleClick(False)        # Note: double-click no longer opens Explorer to avoid accidental opens.

        self.layout.addWidget(self.tree)

        # Prioritize showing the "Select XStage" column (index 1) fully by
        # making it stretch, make the Project Folder column adjustable, and
        # keep the Render and Status columns narrow and fixed-width.
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        # sensible default widths
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(2, 300)
        self.tree.setColumnWidth(3, 120)

        # --- Bottom action buttons ---
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Render Queue")
        self.start_btn.clicked.connect(self.start_render_queue)
        self.clear_btn = QPushButton("Clear Render Queue")
        self.clear_btn.clicked.connect(self.clear_render_queue)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addWidget(self.start_btn)
        self.layout.addLayout(btn_layout)

        # --- Collapsible output log and command controls ---
        log_control_layout = QHBoxLayout()
        self.log_toggle = QPushButton("Show Log")
        self.log_toggle.setCheckable(True)
        self.log_toggle.clicked.connect(self._toggle_log_visibility)
        # Toggle to show exact commands that will be executed
        self.show_cmds_toggle = QPushButton("Show Commands")
        self.show_cmds_toggle.setCheckable(True)
        self.show_cmds_toggle.clicked.connect(self._toggle_cmds_visibility)

        log_control_layout.addWidget(self.show_cmds_toggle)
        log_control_layout.addWidget(self.log_toggle)
        log_control_layout.addStretch(1)
        self.layout.addLayout(log_control_layout)

        self.commands_text = QTextEdit()
        self.commands_text.setReadOnly(True)
        self.commands_text.setVisible(False)
        self.commands_text.setFixedHeight(120)
        self.layout.addWidget(self.commands_text)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setVisible(False)
        self.layout.addWidget(self.log_text)

        # Internal state for rendering control
        self._rendering = False
        self._stop_render_event = threading.Event()
        self._current_proc = None
        self._render_thread = None
        # used to ignore immediate double-click stop requests
        self._render_start_timestamp = 0.0
        # keep path to last temp per-job log if preserved
        self._last_temp_log = None
        # store the last built commands for display
        self._last_built_commands = []

        # Auto-refresh timer for displaying the preserved temp log in GUI
        self._auto_refresh_timer = QTimer()
        self._auto_refresh_timer.setInterval(1000)  # 1 second
        self._auto_refresh_timer.timeout.connect(self._refresh_preserved_log)

        self.setLayout(self.layout)

    # The function that selects the render queue folder
    def select_folder(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Folder", os.path.expanduser("~"))
        
        if dir_path:
            self.folder_edit.setText(dir_path)
    
    # This scans the folder looking for xStage Files and adds them to the list
    def scan_folder(self):
        base = self.folder_edit.text().strip()
        if not base:
            QMessageBox.warning(self, "No folder selected", "Please select a folder to scan.")
            return

        self.tree.clear()
        self.status_label.setText("Scanning...")
        QApplication.processEvents()

        # Patterns that commonly appear in Toon Boom Harmony projects. We use a
        # permissive list so users find projects even if their file types vary.
        patterns = ('.xstage')  # Other options:'.xstage2', '.xstage3', '.scene', '.tbproj', '.hproj', '.tbxml', '.xml'

        matches_found = 0
        for root, dirs, files in os.walk(base):
            matched_files = [f for f in files if f.lower().endswith(patterns)]
            if matched_files:
                # Show path relative to base for readability
                rel = os.path.relpath(root, base)
                if rel == '.':
                    rel = os.path.basename(root)

                # Create top-level item; the second column will host the
                # combo box widget and the third column will host the render widget
                # and the fourth column will show status (Pending/Rendering/Done/Failed)
                item = QTreeWidgetItem([rel, "", "", "Pending"])
                self.tree.addTopLevelItem(item)

                # Add child rows listing the matching files (filename in column 0)
                for f in matched_files:
                    child = QTreeWidgetItem([f, "", "", ""])
                    item.addChild(child)

                # Find xstage files (specific extensions) and populate a
                # combo box in the second column for quick selection
                xstage_files = [f for f in matched_files if f.lower().endswith(('.xstage'))]  # Other options:'.xstage2', '.xstage3'
                combo = QComboBox()
                if xstage_files:
                    # Present dropdown in descending order
                    xstage_files_sorted = sorted(xstage_files, reverse=True)
                    for f in xstage_files_sorted:
                        combo.addItem(f)
                        combo.setItemData(combo.count() - 1, os.path.join(root, f), Qt.ItemDataRole.UserRole)

                    # Safely call the picker; if it doesn't exist or fails,
                    # fall back to the most recently modified file in the list.
                    default = None
                    picker = getattr(self, 'pick_default_xstage', None)
                    if callable(picker):
                        try:
                            default = picker(xstage_files_sorted, root)
                        except Exception:
                            default = None

                    if not default:
                        # Fallback: choose most recently modified
                        file_mtimes = [(f, int(os.path.getmtime(os.path.join(root, f)))) for f in xstage_files_sorted]
                        file_mtimes.sort(key=lambda x: x[1], reverse=True)
                        default = file_mtimes[0][0]

                    if default in xstage_files_sorted:
                        idx = xstage_files_sorted.index(default)
                        combo.setCurrentIndex(idx)
                        item.setData(0, Qt.ItemDataRole.UserRole, os.path.join(root, default))

                    # Update the item's stored selected path when the combo changes
                    combo.currentIndexChanged.connect(lambda i, it=item, cb=combo: self._on_combo_changed(it, cb))
                else:
                    combo.addItem("No xstage files")
                    combo.setEnabled(False)

                # Place the combo in the second column (index 1)
                self.tree.setItemWidget(item, 1, combo)

                # Create and place the render widget in column 2
                render_widget = self._create_render_widget(item, root)
                self.tree.setItemWidget(item, 2, render_widget)

                matches_found += 1

        self.status_label.setText(f"Found {matches_found} project folder(s).")
        if matches_found == 0:
            QMessageBox.information(self, "Scan complete", "No Toon Boom Harmony project folders were found.")

    # function that determines which xstage is selected by default
    def pick_default_xstage(self, filenames, dirpath):
        """Choose the default xstage file from a list.

        Rules:
        1. Choose the file with the most recent modification time (seconds resolution).
        2. If multiple files tie on modification time, prefer the file containing
           "tk<NUMBER>" with the highest NUMBER.
        3. If still tied, choose the lexicographically last filename as a fallback.
        """
        if not filenames:
            return None

        # Use integer seconds for tie comparisons
        file_mtimes = [(f, int(os.path.getmtime(os.path.join(dirpath, f)))) for f in filenames]
        max_mtime = max(m for f, m in file_mtimes)
        tied = [f for f, m in file_mtimes if m == max_mtime]
        if len(tied) == 1:
            return tied[0]

        # Tie-breaker: look for 'tk' followed by a number
        tk_candidates = []
        for f in tied:
            m = re.search(r'tk(\d+)', f, re.I)
            if m:
                tk_candidates.append((int(m.group(1)), f))
        if tk_candidates:
            tk_candidates.sort(reverse=True)
            return tk_candidates[0][1]

        # Final fallback
        return sorted(tied)[-1]

    # function that updates the path when another xstage file is selected
    def _on_combo_changed(self, item, combo):
        idx = combo.currentIndex()
        if idx < 0:
            item.setData(0, Qt.ItemDataRole.UserRole, None)
            item.setToolTip(0, "")
            return
        path = combo.itemData(idx, Qt.ItemDataRole.UserRole)
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setToolTip(0, path)

    # function that creates the widgets for choosing render range.
    def _create_render_widget(self, item, dirpath):
        """Create a small widget for choosing render mode and frame range.

        Stores a dict in the item's UserRole+1 containing keys: render_mode, start, end
        """
        w = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        combo = QComboBox()
        combo.addItems(["All Frames", "Custom Range"])

        # Use text fields for typed numeric input with an integer validator
        validator = QIntValidator(0, 1000000)
        start_edit = QLineEdit()
        start_edit.setValidator(validator)
        start_edit.setText("1")
        start_edit.setEnabled(False)
        start_edit.setFixedWidth(80)
        dash = QLabel("-")
        end_edit = QLineEdit()
        end_edit.setValidator(validator)
        end_edit.setText("100")
        end_edit.setEnabled(False)
        end_edit.setFixedWidth(80)

        layout.addWidget(combo)
        layout.addWidget(start_edit)
        layout.addWidget(dash)
        layout.addWidget(end_edit)
        w.setLayout(layout)

        # initial data stored on item
        item.setData(0, Qt.ItemDataRole.UserRole + 1, {"render_mode": "all", "start": None, "end": None})

        combo.currentIndexChanged.connect(lambda i, it=item, cb=combo, s=start_edit, e=end_edit: self._on_render_mode_changed(it, cb, s, e))
        start_edit.textChanged.connect(lambda v, it=item, s=start_edit, e=end_edit: self._on_frame_text_changed(it, s, e))
        end_edit.textChanged.connect(lambda v, it=item, s=start_edit, e=end_edit: self._on_frame_text_changed(it, s, e))

        return w

    # function to handle if All Frame or Custom Range is selected
    def _on_render_mode_changed(self, item, combo, start_edit, end_edit):
        mode = combo.currentText()
        if mode == "All Frames":
            start_edit.setEnabled(False)
            end_edit.setEnabled(False)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, {"render_mode": "all", "start": None, "end": None})
            item.setToolTip(2, "All frames")
        else:
            start_edit.setEnabled(True)
            end_edit.setEnabled(True)
            # Trigger validation/update based on current text values
            self._on_frame_text_changed(item, start_edit, end_edit)

    # function that validates and upodates frame range inputs
    def _on_frame_text_changed(self, item, start_edit, end_edit):
        s_text = start_edit.text().strip()
        e_text = end_edit.text().strip()
        try:
            s = int(s_text) if s_text != '' else None
        except ValueError:
            s = None
        try:
            e = int(e_text) if e_text != '' else None
        except ValueError:
            e = None

        if s is None or e is None:
            # invalid input — store partial data and mark tooltip
            data = item.data(0, Qt.ItemDataRole.UserRole + 1) or {}
            data.update({"render_mode": "range", "start": s, "end": e})
            item.setData(0, Qt.ItemDataRole.UserRole + 1, data)
            item.setToolTip(2, "Invalid frame(s)")
            return

        # Ensure start <= end
        if s > e:
            end_edit.setText(str(s))
            e = s

        data = item.data(0, Qt.ItemDataRole.UserRole + 1) or {}
        data.update({"render_mode": "range", "start": s, "end": e})
        item.setData(0, Qt.ItemDataRole.UserRole + 1, data)
        item.setToolTip(2, f"Frames: {s} - {e}")

    # Function to clear the render queue
    def clear_render_queue(self):
        # Remove all top-level items and clear the selected folder
        self.tree.clear()
        self.folder_edit.clear()
        self.status_label.setText("Queue cleared")

    # Function to make sure Harmonyt is Installed and finding it to use.
    def _find_harmony_exe(self):
       
        # 1) Check PATH
        exe_name = "HarmonyPremium.exe"
        if shutil.which(exe_name):
            return shutil.which(exe_name)

        # 2) Look in known Program Files path for Harmony 25 Premium
        base = r"C:\Program Files (x86)\Toon Boom Animation"
        candidate = os.path.join(base, r"Toon Boom Harmony 25 Premium", r"win64", "bin", exe_name)
        if os.path.isfile(candidate):
            return candidate

        # 3) If base exists, search for highest version folder then win64/bin
        if os.path.isdir(base):
            entries = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)) and 'harmony' in d.lower()]
            if entries:
                # sort by version number found in folder name
                def version_key(name):
                    m = re.search(r"(\d+)", name)
                    return int(m.group(1)) if m else 0
                entries.sort(key=version_key, reverse=True)
                for e in entries:
                    candidate = os.path.join(base, e, r"win64", "bin", exe_name)
                    if os.path.isfile(candidate):
                        return candidate

        # 4) Not found — prompt user to locate it
        dlg = QFileDialog(self, "Locate HarmonyPremium.exe")
        dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
        dlg.setNameFilter("HarmonyPremium.exe")
        if dlg.exec():
            files = dlg.selectedFiles()
            if files:
                return files[0]
        return None

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # app.setWindowIcon(QIcon(resource_path("SadAlchemist.ico")))
    window = ForgeGUI()
    window.show()
    sys.exit(app.exec())

# HarmonyPremium.exe -scene "C:\Users\Will.LDS01135\Desktop\Will's Library\00 - RENDER QUEUE\JP_OG_SC04_StairsBurger\JP_OG_SC04_StairsBurger_tk08_COMP.xstage" -overwrite -batch -verbose -writenode all
