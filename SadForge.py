import subprocess
import os
import sys
import re
import threading
import shutil
from PyQt6.QtGui import QIcon, QFont, QColor, QPixmap, QPainter, QIntValidator
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QProgressBar, QStackedLayout, QWidget, QMessageBox

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)

if sys.platform == "win32":
    CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW
else:
    CREATE_NO_WINDOW = 0

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QLabel, QLineEdit, QMessageBox, QComboBox, QTreeWidget, QTreeWidgetItem,
    QTextEdit, QInputDialog, QSpinBox, QHeaderView
)
from PyQt6.QtCore import Qt, QSize

class ForgeGUI(QWidget):

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
        # Three columns: project folder, selector, and render options
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Project Folder", "File to Render", "Render Frame Range"])
        self.tree.setRootIsDecorated(False)        # Prevent expanding/collapsing items on double-click so users don't
        # unintentionally reveal xstage files.
        self.tree.setExpandsOnDoubleClick(False)        # Note: double-click no longer opens Explorer to avoid accidental opens.
        # If you want an explicit way to open a folder, I can add a context menu.
        self.layout.addWidget(self.tree)

        # Prioritize showing the "Select XStage" column (index 1) fully by
        # making it stretch, make the Project Folder column adjustable, and
        # keep the Render column narrow and fixed-width.
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        # sensible default widths
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(2, 300)

        self.setLayout(self.layout)

    def select_folder(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Folder", os.path.expanduser("~"))
        if dir_path:
            self.folder_edit.setText(dir_path)

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
                item = QTreeWidgetItem([rel, "", ""])
                self.tree.addTopLevelItem(item)

                # Add child rows listing the matching files (filename in column 0)
                for f in matched_files:
                    child = QTreeWidgetItem([f, "", ""])
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

    def _on_combo_changed(self, item, combo):
        idx = combo.currentIndex()
        if idx < 0:
            item.setData(0, Qt.ItemDataRole.UserRole, None)
            item.setToolTip(0, "")
            return
        path = combo.itemData(idx, Qt.ItemDataRole.UserRole)
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setToolTip(0, path)

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

    def open_in_explorer(self, item, column):
        base = self.folder_edit.text().strip()
        if not base:
            return
        # Determine whether a top-level or child item was clicked and construct
        # the actual path accordingly.
        if item.parent() is None:
            rel = item.text(0)
            # If rel is just a folder name, try to join with base. If it is
            # already relative path, os.path.join will still work.
            path = os.path.normpath(os.path.join(base, rel))
        else:
            parent_rel = item.parent().text(0)
            path = os.path.normpath(os.path.join(base, parent_rel, item.text(0)))

        # If the path is a file, open folder containing it instead
        if os.path.isfile(path):
            path = os.path.dirname(path)

        try:
            if sys.platform == "win32":
                subprocess.Popen(['explorer', path], creationflags=CREATE_NO_WINDOW)
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            QMessageBox.warning(self, "Open failed", f"Could not open path:\n{path}\n\n{e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # app.setWindowIcon(QIcon(resource_path("SadAlchemist.ico")))
    window = ForgeGUI()
    window.show()
    sys.exit(app.exec())

    # HarmonyPremium.exe -scene "C:\Users\Will.LDS01135\Desktop\Will's Library\00 - RENDER QUEUE\JP_OG_SC04_StairsBurger\JP_OG_SC04_StairsBurger_tk08_COMP.xstage" -overwrite -batch -verbose -writenode all
