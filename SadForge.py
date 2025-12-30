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

# On Windows we previously hid child console windows using CREATE_NO_WINDOW.
# Removed that behavior so PowerShell/Harmony windows are visible while running.

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QLabel, QLineEdit, QMessageBox, QComboBox, QTreeWidget, QTreeWidgetItem,
    QTextEdit, QInputDialog, QSpinBox, QHeaderView, QCheckBox
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
        # Four columns: project folder, selector, render options, and status
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Project Folder", "File to Render", "Render Frame Range", "Status"])
        self.tree.setRootIsDecorated(False)        # Prevent expanding/collapsing items on double-click so users don't
        # unintentionally reveal xstage files.
        self.tree.setExpandsOnDoubleClick(False)        # Note: double-click no longer opens Explorer to avoid accidental opens.
        # If you want an explicit way to open a folder, I can add a context menu.
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
                subprocess.Popen(['explorer', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            QMessageBox.warning(self, "Open failed", f"Could not open path:\n{path}\n\n{e}")

    def clear_render_queue(self):
        # Remove all top-level items and clear the selected folder
        self.tree.clear()
        self.folder_edit.clear()
        self.status_label.setText("Queue cleared")

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

    def stop_render_queue(self):
        """Request a stop of the running render queue and kill the current process."""
        self._append_log("stop_render_queue called")
        # include a stack trace to see who invoked the stop
        try:
            self._append_log(''.join(traceback.format_stack(limit=10)))
        except Exception:
            pass
        if not self._rendering:
            self._append_log("No active render; ignoring stop.")
            return
        self._stop_render_event.set()
        # Stop the auto-refresh immediately so GUI update stops
        try:
            self._stop_auto_refresh()
        except Exception:
            pass

        if self._current_proc and getattr(self._current_proc, 'poll', lambda: 1)() is None:
            proc = self._current_proc
            pid = getattr(proc, 'pid', None)
            try:
                # Try to kill entire process tree using psutil if available
                try:
                    import psutil
                    p = psutil.Process(pid)
                    children = p.children(recursive=True)
                    for c in children:
                        try:
                            c.kill()
                            self._append_log(f"Killed child pid={c.pid}")
                        except Exception:
                            pass
                    try:
                        p.kill()
                        self._append_log(f"Killed process pid={pid}")
                    except Exception:
                        pass
                except Exception:
                    # Fallback: on Windows call taskkill to terminate the tree
                    if sys.platform == 'win32' and pid:
                        try:
                            subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            self._append_log(f"taskkill invoked for pid={pid}")
                        except Exception as e:
                            self._append_log(f"Failed to taskkill pid={pid}: {e}")
                    else:
                        try:
                            proc.kill()
                            self._append_log(f"Killed running process pid={pid}")
                        except Exception as e:
                            self._append_log(f"Failed to kill process pid={pid}: {e}")
            except Exception as e:
                self._append_log(f"Failed to kill process: {e}")
            finally:
                try:
                    self._current_proc = None
                except Exception:
                    pass

        # Ensure auto-refresh is stopped if still running
        try:
            self._stop_auto_refresh()
        except Exception:
            pass

        # if a temp log was preserved, open it for inspection to help debugging
        try:
            if self._last_temp_log and os.path.exists(self._last_temp_log):
                self._append_log(f"Opening preserved temp log: {self._last_temp_log}")
                if sys.platform == 'win32':
                    subprocess.Popen(['notepad.exe', self._last_temp_log])
        except Exception:
            pass
        self._rendering = False
        self.start_btn.setText("Start Render Queue")
        self.start_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        self.scan_btn.setEnabled(True)
        self.status_label.setText("Render queue stopped")

    def _append_log(self, text):
        # Ensure append happens on main thread
        def do_append():
            self.log_text.append(text)
            # Autoscroll
            self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
        QTimer.singleShot(0, do_append)

    def _set_item_status(self, item, status, color=None):
        """Thread-safe update of a top-level item's Status column and color.

        color may be a CSS color name or hex string understood by QColor.
        Runs the GUI updates on the main thread using QTimer.singleShot.
        """
        def do_set():
            try:
                # Set status text in the last column
                if not item:
                    return
                col = 3
                item.setText(col, status)
                # Apply foreground color to all columns for visibility
                try:
                    if color:
                        brush = QBrush(QColor(color))
                    else:
                        brush = QBrush(QColor('black'))
                    for c in range(self.tree.columnCount()):
                        item.setForeground(c, brush)
                except Exception:
                    pass
            except Exception:
                pass
        QTimer.singleShot(0, do_set)

    def _toggle_log_visibility(self):
        if self.log_toggle.isChecked():
            self.log_toggle.setText("Hide Log")
            self.log_text.setVisible(True)
        else:
            self.log_toggle.setText("Show Log")
            self.log_text.setVisible(False)

    def _toggle_cmds_visibility(self):
        if self.show_cmds_toggle.isChecked():
            self.show_cmds_toggle.setText("Hide Commands")
            self.commands_text.setVisible(True)
            self._update_commands_view()
        else:
            self.show_cmds_toggle.setText("Show Commands")
            self.commands_text.setVisible(False)

    def _update_commands_view(self):
        try:
            lines = []
            for i, c in enumerate(self._last_built_commands, start=1):
                lines.append(f"{i}: {c}")
            self.commands_text.setPlainText('\n'.join(lines))
        except Exception:
            pass



    def _start_auto_refresh(self):
        try:
            if self._auto_refresh_timer and not self._auto_refresh_timer.isActive():
                self._append_log("Starting auto-refresh of preserved log (1s)")
                self._auto_refresh_timer.start()
        except Exception:
            pass

    def _stop_auto_refresh(self):
        try:
            if self._auto_refresh_timer and self._auto_refresh_timer.isActive():
                self._auto_refresh_timer.stop()
                self._append_log("Stopped auto-refresh of preserved log")
        except Exception:
            pass

    def _refresh_preserved_log(self):
        """Replace the GUI log with the current contents of the preserved temp log(s).
        This reads both stdout and stderr temp files and shows the combined result.
        """
        try:
            path = getattr(self, '_last_temp_log', None)
            if not path or not os.path.exists(path):
                return
            stderr_path = getattr(self, '_last_temp_err', None)

            # Read whole files but cap the characters to avoid freezing UI
            max_chars = 300_000
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except Exception:
                content = ''
            if stderr_path and os.path.exists(stderr_path):
                try:
                    with open(stderr_path, 'r', encoding='utf-8', errors='replace') as ef:
                        err_content = ef.read()
                    if err_content:
                        content = content + "\n" + "(stderr)\n" + err_content
                except Exception:
                    pass

            if len(content) > max_chars:
                content = "... <truncated> ...\n" + content[-max_chars:]

            # Replace the entire GUI log content
            def do_replace():
                try:
                    self.log_text.clear()
                    self.log_text.setPlainText(content)
                    # Autoscroll to bottom
                    self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
                except Exception:
                    pass
            QTimer.singleShot(0, do_replace)
        except Exception:
            pass

    def start_render_queue(self):
        # Toggle behavior: if already rendering, stop; otherwise start
        if self._rendering:
            # Small debounce: ignore stop requests right after starting to avoid
            # accidental double-clicks.
            if self._render_start_timestamp and (time.time() - self._render_start_timestamp) < 1.5:
                self._append_log("Stop ignored: render just started")
                return

            # Ask for confirmation before stopping a running queue
            reply = QMessageBox.question(
                self,
                "Stop Render Queue",
                "A render is currently in progress. Do you want to stop the render queue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_render_queue()
            return

        # Build a list of selected items (top-level items only)
        jobs = []
        rootcount = self.tree.topLevelItemCount()
        for i in range(rootcount):
            item = self.tree.topLevelItem(i)
            xstage = item.data(0, Qt.ItemDataRole.UserRole)
            render_opts = item.data(0, Qt.ItemDataRole.UserRole + 1) or {}
            if not xstage:
                continue
            jobs.append((xstage, render_opts))

        if not jobs:
            QMessageBox.information(self, "No jobs", "No render jobs are selected.")
            return

        exe = self._find_harmony_exe()
        if not exe:
            QMessageBox.warning(self, "Harmony not found", "HarmonyPremium.exe was not found. Please locate the executable.")
            return

        # Prepare UI and state
        self._stop_render_event.clear()
        self._rendering = True
        self.start_btn.setText("Stop Render Queue")
        self.clear_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        # Ensure log is visible when running
        if not self.log_toggle.isChecked():
            self.log_toggle.setChecked(True)
            self._toggle_log_visibility()
        self.log_text.clear()
        # Clear last commands list for fresh run
        self._last_built_commands = []
        self.commands_text.clear()
        self._append_log("Starting render queue... please wait a few minutes for the render to start...")

        # Build a list of selected items (top-level items only). Store the
        # associated QTreeWidgetItem so we can update its status during work.
        jobs = []
        rootcount = self.tree.topLevelItemCount()
        for i in range(rootcount):
            item = self.tree.topLevelItem(i)
            xstage = item.data(0, Qt.ItemDataRole.UserRole)
            render_opts = item.data(0, Qt.ItemDataRole.UserRole + 1) or {}
            if not xstage:
                continue
            jobs.append((item, xstage, render_opts))

        # Ensure all queued items show 'Pending' before starting
        for job_item, _, _ in jobs:
            try:
                self._set_item_status(job_item, 'Pending', None)
            except Exception:
                pass

        if not jobs:
            QMessageBox.information(self, "No jobs", "No render jobs are selected.")
            return

        exe = self._find_harmony_exe()
        if not exe:
            QMessageBox.warning(self, "Harmony not found", "HarmonyPremium.exe was not found. Please locate the executable.")
            return

        # Prepare a heartbeat file so the background thread can write an early
        # diagnostic even if the GUI log doesn't update.
        try:
            self._heartbeat_file = os.path.join(tempfile.gettempdir(), f"sadforge_heartbeat_{os.getpid()}_{int(time.time())}.log")
            # ensure old file is removed
            try:
                if os.path.exists(self._heartbeat_file):
                    os.remove(self._heartbeat_file)
            except Exception:
                pass
            self._append_log(f"Heartbeat file: {self._heartbeat_file}")
        except Exception:
            self._heartbeat_file = None

        # Run renders in a background thread so UI doesn't freeze
        # Record the timestamp so we can debounce immediate stop requests
        self._render_start_timestamp = time.time()
        self._render_thread = threading.Thread(target=self._run_jobs, args=(exe, jobs), daemon=True)
        self._render_thread.start()
        self._append_log("Render thread launched")
        # Start auto-refreshing preserved temp log into GUI
        try:
            QTimer.singleShot(0, self._start_auto_refresh)
        except Exception:
            pass
        self.status_label.setText("Render queue started...")

    def _run_jobs(self, exe, jobs):
        # Heartbeat so we can tell the thread started correctly
        self._append_log("Render thread running")
        # Also write an immediate heartbeat file entry for out-of-GUI diagnostics
        hb = getattr(self, '_heartbeat_file', None)
        if hb:
            try:
                with open(hb, 'a', encoding='utf-8') as hf:
                    hf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] thread started\n")
                    hf.flush()
            except Exception:
                pass

        try:
            for item, path, opts in jobs:
                if self._stop_render_event.is_set():
                    self._append_log("Render queue stopped by user.")
                    break

                # Update item status to In Progress (orange)
                self._set_item_status(item, "In Progress", "orange")

                cmd = [exe, "-scene", path, "-overwrite", "-batch", "-verbose", "-writenode", "all"]
                # If frame range
                if opts.get("render_mode") in ("range", "range"):
                    s = opts.get("start")
                    e = opts.get("end")
                    if s is not None and e is not None:
                        cmd.extend(["-frames", f"{s}-{e}"])

                # Build a displayable command line string
                try:
                    cmd_display = subprocess.list2cmdline(cmd)
                except Exception:
                    cmd_display = ' '.join(cmd)

                # Store and optionally display the commands
                self._last_built_commands.append(cmd_display)
                if getattr(self, 'show_cmds_toggle', None) and self.show_cmds_toggle.isChecked():
                    # Ensure UI updates happen on the main thread
                    QTimer.singleShot(0, self._update_commands_view)

                self._append_log(f"Starting: {cmd_display}")
                # Log diagnostic info
                try:
                    self._append_log(f"Using exe: {exe}")
                    self._append_log(f"PATH (first 1000 chars): {os.environ.get('PATH','')[:1000]}")
                except Exception:
                    pass

                try:
                    # Robust approach: write process output to a temporary file and
                    # tail that file so we capture output even if buffering differs.
                    fd, tmpname = tempfile.mkstemp(prefix='sadforge_', suffix='.log', text=True)
                    os.close(fd)
                    self._append_log(f"Temp log: {tmpname}")

                    # Also write initial heartbeat to the temp log to help diagnose
                    # whether the child process is launched
                    try:
                        with open(tmpname, 'a', encoding='utf-8') as out_file:
                            out_file.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] launching process\n")
                    except Exception:
                        pass

                    # Ensure the status column reflects that this job is pending/started


                    # Launch process directly and write output to a temporary file
                    with open(tmpname, 'w', encoding='utf-8') as out_file:
                        proc = subprocess.Popen(cmd, stdout=out_file, stderr=subprocess.STDOUT)
                        self._current_proc = proc
                        self._last_temp_log = tmpname
                        self._append_log(f"Launched process pid={getattr(proc,'pid',None)}")
                        # write immediate heartbeat to temp log
                        try:
                            with open(tmpname, 'a', encoding='utf-8') as out_file2:
                                out_file2.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] launched pid={getattr(proc,'pid',None)}\n")
                                out_file2.flush()
                        except Exception:
                            pass

                    # If psutil available, list children for diagnostics
                    try:
                        import psutil
                        p = psutil.Process(proc.pid)
                        children = p.children(recursive=True)
                        if children:
                            for c in children:
                                try:
                                    self._append_log(f"Child process: pid={c.pid} cmd={c.cmdline()}")
                                except Exception:
                                    pass
                    except Exception:
                        # psutil not available or error occurred; ignore
                        pass

                    # Tail the temp files (stdout and optional stderr) while the process runs
                    try:
                        err_path = locals().get('tmpname_err')
                        out_f = open(tmpname, 'r', encoding='utf-8')
                        err_f = None
                        if err_path:
                            try:
                                # ensure file exists before opening; Start-Process will create it quickly
                                open(err_path, 'a', encoding='utf-8').close()
                                err_f = open(err_path, 'r', encoding='utf-8')
                            except Exception:
                                err_f = None

                        # Read any existing stdout/stderr lines that were written before we started tailing
                        try:
                            # Read whole current content from stdout
                            out_f.seek(0)
                            for line in out_f:
                                if line:
                                    stripped = line.rstrip()
                                    self._append_log(stripped)
                            # Move to end for tailing new lines
                            out_f.seek(0, os.SEEK_END)

                            if err_f:
                                err_f.seek(0)
                                for line in err_f:
                                    if line:
                                        self._append_log(f"(stderr) {line.rstrip()}")
                                err_f.seek(0, os.SEEK_END)
                        except Exception:
                            pass

                        hb_counter = 0
                        while proc.poll() is None:
                            if self._stop_render_event.is_set():
                                try:
                                    proc.kill()
                                except Exception:
                                    pass
                                break

                            got_any = False
                            # Read any new stdout lines
                            line = out_f.readline()
                            if line:
                                got_any = True
                                stripped = line.rstrip()
                                self._append_log(stripped)

                            # Read any new stderr lines
                            if err_f:
                                err_line = err_f.readline()
                                if err_line:
                                    got_any = True
                                    self._append_log(f"(stderr) {err_line.rstrip()}")

                            if not got_any:
                                # periodic heartbeat to the separate heartbeat file to show progress
                                hb_counter += 1
                                if hb and (hb_counter % 5) == 0:
                                    try:
                                        with open(hb, 'a', encoding='utf-8') as hf:
                                            hf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] process running pid={getattr(proc,'pid',None)}\n")
                                            hf.flush()
                                    except Exception:
                                        pass
                                time.sleep(0.2)

                        # read remaining lines from both files
                        for line in out_f:
                            if line:
                                self._append_log(line.rstrip())
                        if err_f:
                            for line in err_f:
                                if line:
                                    self._append_log(f"(stderr) {line.rstrip()}")
                    except Exception as e:
                        self._append_log(f"Error tailing temp log(s): {e}")
                    finally:
                        try:
                            out_f.close()
                        except Exception:
                            pass
                        try:
                            if err_f:
                                err_f.close()
                        except Exception:
                            pass

                    # Wait for process to terminate and report exit code
                    try:
                        proc.wait(timeout=1)
                    except Exception:
                        pass
                    rc = getattr(proc, 'returncode', None)
                    self._append_log(f"Process exited with code {rc}")

                    # If return code is non-zero or the user stopped the run, keep
                    # the temp log for inspection and report its path
                    try:
                        if rc not in (0, None) or self._stop_render_event.is_set():
                            self._append_log(f"Preserving temp log for inspection: {tmpname}")
                            # Mark item as failed if non-zero or stopped
                            try:
                                if rc not in (0, None) and not self._stop_render_event.is_set():
                                    self._set_item_status(item, 'Failed', 'red')
                                else:
                                    self._set_item_status(item, 'Stopped', 'red')
                            except Exception:
                                pass

                            # Also load recent portion of the temp log(s) into the GUI
                            try:
                                def load_file_preview(path, label=None, max_lines=2000):
                                    if not path or not os.path.exists(path):
                                        return
                                    try:
                                        with open(path, 'r', encoding='utf-8', errors='replace') as f:
                                            lines = f.readlines()
                                        # Keep only last max_lines to avoid flooding the GUI
                                        if len(lines) > max_lines:
                                            lines = lines[-max_lines:]
                                            self._append_log(f"(preview) Showing last {max_lines} lines of {os.path.basename(path)}")
                                        else:
                                            self._append_log(f"(preview) Showing {len(lines)} lines of {os.path.basename(path)}")
                                        for ln in lines:
                                            self._append_log(ln.rstrip())
                                    except Exception as e:
                                        self._append_log(f"Failed to load preview of {path}: {e}")

                                # stdout preview
                                load_file_preview(tmpname)
                                # stderr preview if it exists
                                err_path = locals().get('tmpname_err')
                                if err_path and os.path.exists(err_path):
                                    load_file_preview(err_path)
                            except Exception:
                                pass

                            # offer to open it automatically (Windows)
                            try:
                                if sys.platform == 'win32' and os.path.exists(tmpname):
                                    subprocess.Popen(['notepad.exe', tmpname])
                            except Exception:
                                pass
                        else:
                            try:
                                os.remove(tmpname)
                            except Exception:
                                pass
                            # also remove stderr if present
                            try:
                                errp = locals().get('tmpname_err')
                                if errp and os.path.exists(errp):
                                    os.remove(errp)
                            except Exception:
                                pass
                    except Exception:
                        pass

                    # If we reached here and the job completed successfully, mark it done
                    try:
                        if rc == 0 and not self._stop_render_event.is_set():
                            self._set_item_status(item, 'Completed', 'green')
                    except Exception:
                        pass
                except Exception as e:
                    self._append_log(f"Job failed: {e}")
                    # log the full traceback for debugging
                    self._append_log(traceback.format_exc())
                    # preserve tmp log for debugging when we hit an exception
                    try:
                        if 'tmpname' in locals():
                            self._append_log(f"Preserved temp log: {tmpname}")
                    except Exception:
                        pass
                    continue
                finally:
                    try:
                        self._current_proc = None
                    except Exception:
                        pass

                if self._stop_render_event.is_set():
                    self._append_log("Stopping further jobs...")
                    break
        except Exception as e:
            # Unexpected error — log traceback for diagnosis
            self._append_log(f"Unhandled exception in render thread: {e}")
            self._append_log(traceback.format_exc())
        finally:
            # Ensure UI state is restored on the main thread
            def finish():
                try:
                    self._stop_auto_refresh()
                except Exception:
                    pass
                self._rendering = False
                self.start_btn.setText("Start Render Queue")
                self.clear_btn.setEnabled(True)
                self.scan_btn.setEnabled(True)
                self.status_label.setText("Render queue finished")
                self._append_log("Render queue finished")
            QTimer.singleShot(0, finish)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # app.setWindowIcon(QIcon(resource_path("SadAlchemist.ico")))
    window = ForgeGUI()
    window.show()
    sys.exit(app.exec())

    # HarmonyPremium.exe -scene "C:\Users\Will.LDS01135\Desktop\Will's Library\00 - RENDER QUEUE\JP_OG_SC04_StairsBurger\JP_OG_SC04_StairsBurger_tk08_COMP.xstage" -overwrite -batch -verbose -writenode all
