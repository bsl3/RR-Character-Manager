"""Retro Rewind Character Manager — PySide6 desktop interface."""
from __future__ import annotations
import sys
import traceback
import re
import subprocess
import tempfile
import hashlib
from pathlib import Path
from collections import OrderedDict
from PySide6.QtCore import Qt, QSettings, QSize, QTimer, Signal, QPointF, QThread, QEvent, QItemSelectionModel, QMimeData, QUrl, QRect
from PySide6.QtGui import QAction, QColor, QFont, QImage, QPixmap, QKeySequence, QIcon, QIntValidator, QPainter, QPolygonF, QDrag, QDesktopServices, QCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QLineEdit, QListWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QVBoxLayout, QHBoxLayout,
    QFormLayout, QGridLayout, QGroupBox, QSplitter, QFileDialog, QMessageBox,
    QDialog, QComboBox, QSpinBox, QPlainTextEdit, QAbstractItemView,
    QInputDialog, QMenu, QFrame, QScrollArea, QStyle, QStyleOptionViewItem, QStyleOptionSpinBox, QSizePolicy, QToolButton, QStyledItemDelegate, QCheckBox, QTabWidget, QTabBar, QProgressBar
)
from . import __version__
from .library import parse_asset, CHARACTER_NAMES, CODE_IDS, DISPLAY_CODES, normalized_import_files, available_import_variants, select_import_entries, preferred_import_code, DEFAULT_RESOURCE_VARIANT
from .operations import CharacterPack, EditPlan
from .profiles import ACTIVE_KEY, load_profiles, make_profile, save_profiles
from .tpl import read_tpl
from .models import source_entries, discover_models, extract_model_bytes, find_installed_models, automatic_driver_candidate
from .preview3d import decode_brres, PreviewDecodeError, list_models, default_model
from concurrent.futures import ThreadPoolExecutor
_MODEL_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rrcm-model")
from .preview_widget import MeshPreviewWidget

# Keep previews alive while BrawlCrate opens them.
_MODEL_PREVIEW_FILES = tempfile.TemporaryDirectory(prefix='rrcm-model-viewer-')

# Change this number to move only the minimap image: negative = up, positive = down.
MAP_ICON_VERTICAL_OFFSET = 0

STYLESHEET = r'''
QWidget { background: #111925; color: #e3eaf6; font-family: "Segoe UI", Arial; font-size: 10pt; }
QMainWindow { background: #101723; }
QMenuBar { background: #182436; padding: 4px 6px; border-bottom: 1px solid #2c3c50; }
QMenuBar::item:selected, QMenu::item:selected { background: #284665; }
QMenu { background: #1b293b; border: 1px solid #36465a; padding: 5px; }
QMenu::item { padding: 6px 26px; }
QFrame#Header { background: #18283d; border-bottom: 1px solid #30455e; }
QLabel#AppTitle { font-size: 18pt; font-weight: 700; color: #f1f5fc; background: transparent; }
QLabel#AppSubtitle { color: #96abc3; font-size: 9pt; background: transparent; }
QLabel#SectionTitle { color: #a0b5d1; font-size: 9pt; font-weight: 700; }
QLabel#Stat { font-weight: 650; color: #d5e5fb; }
QGroupBox { border: 1px solid #34445a; border-radius: 9px; margin-top: 16px; padding: 12px 9px 9px; font-weight: 600; color: #d0e2f7; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 12px; padding: 0 5px; }
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit { background: #182538; border: 1px solid #374a63; border-radius: 6px; padding: 8px; selection-background-color: #327ac7; }
QLineEdit, QSpinBox, QComboBox { padding: 4px 8px; min-height: 1.5em; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus { border: 1px solid #6da9fa; }
QPushButton { background: #263954; color: #e6eef8; border: 1px solid #3a5476; border-radius: 7px; padding: 8px 15px; font-weight: 600; }
QPushButton:hover { background: #315076; }
QPushButton:pressed { background: #23405e; }
QPushButton:disabled { background: #1b2635; border-color: #29384b; color: #64758b; }
QPushButton#Primary { background: #2475d0; border-color: #3386ec; color: white; }
QPushButton#Primary:hover { background: #398be9; }
QListWidget, QTableWidget, QTreeWidget { background: #151f2e; border: 1px solid #344459; border-radius: 7px; outline: none; alternate-background-color: #1b293a; }
QListWidget::item { padding: 10px 8px; border-radius: 5px; margin: 2px 5px; }
QListWidget::item:selected { background: #254d7c; color: #ffffff; }
QTableWidget::item, QTreeWidget::item { padding: 7px 6px; }
QTableWidget::item:selected, QTreeWidget::item:selected { background: #254d7c; color: #ffffff; }
QHeaderView::section { background: #203046; color: #b7cbe2; border: none; border-right: 1px solid #344459; border-bottom: 1px solid #344459; padding: 10px 7px; font-weight: 600; }
QSplitter::handle { background: #2d3d51; width: 1px; }
QScrollBar:vertical { width: 10px; background: #121c2a; }
QScrollBar::handle:vertical { background: #3e5470; border-radius: 4px; min-height: 24px; }
QScrollBar:horizontal { height: 10px; background: #121c2a; }
QScrollBar::handle:horizontal { background: #3e5470; border-radius: 4px; min-width: 24px; }
QStatusBar { background: #182536; color: #9fb3cb; border-top: 1px solid #35465d; }
QToolTip { color: #eaf2ff; background: #253b59; border: 1px solid #5b83af; }
QTabWidget::pane { border: 1px solid #34445a; border-radius: 8px; background: #111925; }
QTabBar::tab { background: #1b2b40; color: #c6d6e9; border: 1px solid #34445a; padding: 9px 17px; margin-right: 3px; border-top-left-radius: 6px; border-top-right-radius: 6px; }
QTabBar::tab:selected { background: #2c4d76; color: white; border-bottom-color: #2c4d76; }
QTabBar::tab:hover:!selected { background: #263e5a; }
QToolButton#CharacterTile { background: #1b2a3d; border: 1px solid #354962; border-radius: 7px; padding: 4px 2px; font-size: 8pt; font-weight: 600; }
QToolButton#CharacterTile:hover { background: #2c4667; border-color: #739ac2; }
QToolButton#CharacterTile:checked { background: #234b75; border: 2px solid #67abff; }
QPushButton#CSSPreview { background: #23344a; border: none; border-radius: 9px; font-size: 9pt; color: #b9cce2; padding: 0; }
QPushButton#CSSPreview:hover { background: #2b4361; border: none; }
'''



def mask_windows_user(path: str) -> str:
    """Hide only a Windows user-profile name, keeping path structure and length."""
    return re.sub(r'(?i)((?:^|[\\/])Users[\\/])([^\\/]+)',
                  lambda match: match.group(1) + '*' * len(match.group(2)), str(path))



def tpl_pixmap(payload: bytes) -> QPixmap:
    """Decode an already-packaged TPL exactly like installed icon previews."""
    image = read_tpl(payload).convert('RGBA')
    raw = image.tobytes('raw', 'RGBA')
    qt_image = QImage(raw, image.width, image.height, image.width * 4,
                      QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(qt_image)


def resource_context_menu(parent, pack, code, slot, asset, global_pos, submit_plan, operation=None):
    """File actions shared by the main resource list and fullscreen resource editor."""
    source = pack.asset_path(asset.relpath)
    # Inherited resources stay read-only; local patch files can be edited.
    if not source.is_file() or source.is_symlink():
        return
    if not pack.developer_mode and not source.resolve().is_relative_to(pack.patches_path):
        return
    if operation is None:
        menu = QMenu(parent)
        rename = menu.addAction('Rename…')
        export = menu.addAction('Export…')
        delete = menu.addAction('Delete…')
        selected = menu.exec(global_pos)
        operation = ('rename' if selected == rename else
                     'export' if selected == export else
                     'delete' if selected == delete else None)
    if operation not in ('rename', 'export', 'delete'):
        return
    if operation == 'export':
        dest, _ = QFileDialog.getSaveFileName(parent, 'Export Resource', source.name,
                                            'All files (*)')
        if not dest:
            return
        target = Path(dest).expanduser().absolute()
        # Export must never edit a live installation through the save dialog.
        resolved = target.resolve()
        if (resolved.is_relative_to(pack.character) or
                resolved.is_relative_to(pack.patches_path) or resolved == pack.archive_path):
            QMessageBox.warning(parent, 'Unsafe export', 'Export outside the active Character/Patches installation.')
            return
        if target.exists() and QMessageBox.question(parent, 'Replace export?',
                f'Overwrite {target.name}?') != QMessageBox.StandardButton.Yes:
            return
        try:
            target.write_bytes(source.read_bytes())
        except OSError as exc:
            QMessageBox.warning(parent, 'Export failed', str(exc))
        return
    try:
        if operation == 'rename':
            new_name, ok = QInputDialog.getText(parent, 'Rename Resource', 'Filename:', text=source.name)
            if not ok or new_name == source.name:
                return
            plan = pack.rename_resources(code, slot, {asset.relpath: new_name})
        else:
            plan = pack.delete_resource(code, slot, asset.relpath)
        if plan.moves or plan.deletes or plan.writes:
            submit_plan(plan)
    except Exception as exc:
        QMessageBox.warning(parent, 'Resource operation failed', str(exc))


class ClickToCopyPath(QLabel):
    """Show a screenshot-safe path; clicking copies the usable original path."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_path = ''
        self.setObjectName('AppSubtitle')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('Click to copy the complete Character folder path')
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setPath(self, path: str):
        self._full_path = str(path)
        self.setText(mask_windows_user(self._full_path))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._full_path:
            QApplication.clipboard().setText(self._full_path)
            window = self.window()
            if isinstance(window, QMainWindow):
                window.statusBar().showMessage('Character folder path copied', 3500)
            event.accept()
            return
        super().mouseReleaseEvent(event)


def note(text: str) -> QLabel:
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setStyleSheet('color: #9badc5; font-size: 9pt;')
    return widget


def button(title: str, action, primary: bool = False) -> QPushButton:
    result = QPushButton(title)
    result.clicked.connect(action)
    if primary:
        result.setObjectName('Primary')
    return result


class EditableImagePreview(QPushButton):
    """Clickable image with a hover-only edit affordance."""
    def __init__(self, placeholder: str, parent=None):
        super().__init__(placeholder, parent)
        self.setObjectName('CSSPreview')
        self._editable = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._edit_badge = QLabel('✎', self)
        self._edit_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._edit_badge.setFixedSize(27, 27)
        self._edit_badge.setStyleSheet(
            'background: #2475d0; border: none; border-radius: 7px; '
            'color: white; font-family: "Segoe UI Symbol"; font-size: 15pt;'
        )
        # Clicking through the badge activates the entire image, not a separate button.
        self._edit_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._edit_badge.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._edit_badge.move(self.width() - self._edit_badge.width() - 7, 7)

    def enterEvent(self, event):
        super().enterEvent(event)
        if self._editable:
            self._edit_badge.show()

    def leaveEvent(self, event):
        self._edit_badge.hide()
        super().leaveEvent(event)

    def setEditable(self, editable: bool):
        # Keep read-only icons in color, without an edit badge.
        self._editable = bool(editable)
        self.setCursor(Qt.CursorShape.PointingHandCursor if editable else Qt.CursorShape.ArrowCursor)
        if not editable:
            self._edit_badge.hide()


class PatchRowDelegate(QStyledItemDelegate):
    """Keep pink and collision-red backgrounds visible when a row is selected."""

    @staticmethod
    def tint_option(option, index):
        opt = QStyleOptionViewItem(option)
        if index.data(Qt.ItemDataRole.UserRole + 1) == 'patch':
            opt.state &= ~QStyle.StateFlag.State_Selected
        return opt

    def paint(self, painter, option, index):
        super().paint(painter, self.tint_option(option, index), index)
        if (option.state & QStyle.StateFlag.State_Selected and
                index.data(Qt.ItemDataRole.UserRole + 1) == 'patch'):
            painter.save()
            painter.setPen(QColor('#df9ebc'))
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
            painter.restore()


class CenteredCSSDelegate(PatchRowDelegate):
    """Draw the CSS icon centered, with the same selection tint as other cells."""

    def paint(self, painter, option, index):
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if not isinstance(icon, QIcon) or icon.isNull():
            super().paint(painter, option, index)
            return
        opt = self.tint_option(option, index)
        self.initStyleOption(opt, index)
        opt.icon = QIcon()
        opt.text = ''
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        bounds = option.rect.adjusted(4, 4, -4, -4)
        size = min(64, bounds.width(), bounds.height())
        if size <= 0:
            return
        pixmap = icon.pixmap(QSize(size, size))
        if pixmap.isNull():
            return
        x = bounds.x() + (bounds.width() - pixmap.width()) // 2
        y = bounds.y() + (bounds.height() - pixmap.height()) // 2
        painter.drawPixmap(x, y, pixmap)
        if (option.state & QStyle.StateFlag.State_Selected and
                index.data(Qt.ItemDataRole.UserRole + 1) == 'patch'):
            painter.save()
            painter.setPen(QColor('#df9ebc'))
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
            painter.restore()


class UpdateWorker(QThread):
    result = Signal(object, str)

    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self.repo = repo

    def run(self):
        from .updates import latest
        try:
            self.result.emit(latest(self.repo, __version__), '')
        except Exception as error:
            self.result.emit(None, str(error))


class PatchSlotTable(QTableWidget):
    """Stage slot drops without letting Qt remove source rows."""
    slotDropped = Signal(int, int)
    rowPressed = Signal(bool)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self._drag_slot = None

    def mousePressEvent(self, event):
        if event.button()==Qt.MouseButton.LeftButton and self.rowAt(int(event.position().y()))>=0:
            self.rowPressed.emit(bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier))
        super().mousePressEvent(event)

    def startDrag(self, actions):
        if len(self.selectionModel().selectedRows()) != 1:
            return
        row = self.currentRow()
        item = self.item(row, 0) if row >= 0 else None
        self._drag_slot = (item.data(Qt.ItemDataRole.UserRole) if item is not None
                           and (item.data(Qt.ItemDataRole.UserRole + 1) == 'patch' or
                                self.property('developerMode')) else None)
        if self._drag_slot is not None:
            # Copy the drag preview; slot changes are handled by our drop handler.
            drag=QDrag(self)
            mime=QMimeData();mime.setData('application/x-rrcm-slot',str(self._drag_slot).encode())
            drag.setMimeData(mime)
            rect = QRect(0, self.rowViewportPosition(row),
                         self.viewport().width(), self.rowHeight(row))
            rect = rect.intersected(self.viewport().rect())
            drag.setPixmap(self.viewport().grab(rect))
            hotspot = self.viewport().mapFromGlobal(QCursor.pos()) - rect.topLeft()
            hotspot.setX(max(0, min(hotspot.x(), rect.width() - 1)))
            hotspot.setY(max(0, min(hotspot.y(), rect.height() - 1)))
            drag.setHotSpot(hotspot)
            drag.exec(Qt.DropAction.CopyAction)
        self._drag_slot = None

    def dragEnterEvent(self,event):
        self.dragMoveEvent(event)

    def dragMoveEvent(self,event):
        if event.source() is self and self._drag_slot is not None and event.mimeData().hasFormat('application/x-rrcm-slot'):
            event.setDropAction(Qt.DropAction.CopyAction);event.accept()
        else:event.ignore()

    def dropEvent(self, event):
        if self._drag_slot is None or event.source() is not self:
            event.ignore()
            return
        target_row = self.rowAt(event.position().toPoint().y())
        target = self.item(target_row, 0) if target_row >= 0 else None
        source_slot = self._drag_slot
        target_slot = target.data(Qt.ItemDataRole.UserRole) if target else -1
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        QTimer.singleShot(0,lambda:self.slotDropped.emit(source_slot,target_slot))


class ConnectionProfileEditor(QWidget):
    """One independent set of connection paths and editing permissions."""
    def __init__(self, profile: dict[str, str], parent=None):
        super().__init__(parent)
        self.profile_id = profile['id']
        self.profile_name = profile['name']
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 9, 8, 7)
        layout.setSpacing(10)

        character_group = QGroupBox('Character folder')
        form = QHBoxLayout(character_group)
        self.folder = QLineEdit(profile['character'])
        self.folder.setPlaceholderText('…/RetroRewind6/Character')
        form.addWidget(self.folder, 1)
        form.addWidget(button('Browse…', self.browse_folder))
        layout.addWidget(character_group)

        archive_group = QGroupBox('ReplacedAssets.szs')
        archive_layout = QHBoxLayout(archive_group)
        self.archive = QLineEdit(profile['archive'])
        self.archive.setPlaceholderText('…/RetroRewind6/Assets/ReplacedAssets.szs')
        archive_layout.addWidget(self.archive, 1)
        archive_layout.addWidget(button('Browse…', self.browse_archive))
        layout.addWidget(archive_group)

        patches_group = QGroupBox('Patches folder · optional (recommended for adding skins)')
        patches_row = QHBoxLayout(patches_group)
        self.patches = QLineEdit(profile['patches'])
        self.patches.setPlaceholderText('…/RetroRewind6/Patches')
        patches_row.addWidget(self.patches, 1)
        patches_row.addWidget(button('Browse…', self.browse_patches))
        layout.addWidget(patches_group)

        developer_group = QGroupBox('Editing permissions')
        dev_layout = QVBoxLayout(developer_group)
        self.developer_checkbox = QCheckBox('Developer Mode — edit distribution characters')
        # Developer Mode must be enabled each time a pack is opened.
        self.developer_checkbox.setChecked(False)
        self.developer_checkbox.setToolTip('For creators maintaining a distribution that uses Retro Rewind character code.')
        dev_layout.addWidget(self.developer_checkbox)
        dev_layout.addWidget(note('For distribution developers using Retro Rewind character code. Enables '
                                  'editing original Character/ assets and ReplacedAssets.szs, '
                                  'changing existing skins, and moving or inserting slots. '
                                  'Leave off if you are simply installing skins for yourself.'))
        layout.addWidget(developer_group)
        self.detail = note('Standard Mode: browse the installed character library and add new skins '
                           'to an empty slot in Patches/. Original distribution assets stay read-only.')
        self.developer_checkbox.toggled.connect(self.update_mode_description)
        layout.addWidget(self.detail)
        layout.addStretch(1)

    def snapshot(self) -> dict[str, str]:
        return {'id': self.profile_id, 'name': self.profile_name,
                'character': self.folder.text().strip(), 'archive': self.archive.text().strip(),
                'patches': self.patches.text().strip()}

    def update_mode_description(self, enabled: bool):
        self.detail.setText(
            'Developer Mode: direct edits to Character/ and ReplacedAssets.szs are enabled. '
            'Keep a backup of your distribution.' if enabled else
            'Standard Mode: browse the installed character library and add new skins '
            'to an empty slot in Patches/. Original distribution assets stay read-only.')

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Choose Character folder', self.folder.text())
        if folder:
            # Only the currently browsed profile is changed.
            if not self.patches.text().strip():
                self.patches.setText(str(Path(folder).parent / 'Patches'))
            self.folder.setText(folder)

    def browse_archive(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose ReplacedAssets.szs', self.archive.text(),
                                              'SZS archives (*.szs);;All files (*)')
        if path:
            self.archive.setText(path)

    def browse_patches(self):
        path = QFileDialog.getExistingDirectory(self, 'Choose Patches folder', self.patches.text())
        if path:
            self.patches.setText(path)


def package_import_plan(pack, source, code, slot, **kwargs):
    """Use the same current-mode dispatch in the package wizard and batch importer."""
    if pack.developer_mode:
        kwargs.setdefault('insert', False)
        return pack.import_skin(source, code, slot, **kwargs)
    kwargs.pop('insert', None)
    return pack.import_patch_skin(source, code, slot, **kwargs)


class MassImportWorker(QThread):
    progress = Signal(int, str)

    def __init__(self, pack, packages, parent=None):
        super().__init__(parent)
        self.pack, self.packages = pack, packages
        self.successes, self.failures = [], []

    def run(self):
        from .mkchara import read_package
        for completed, path in enumerate(self.packages):
            self.progress.emit(completed, f'Reading {path.name}')
            try:
                package = read_package(path)
                code = package.character['base_character']
                chosen = self.pack.next_import_slot(code)
                destination = 'Character' if self.pack.developer_mode else 'Patches'
                self.progress.emit(completed,
                    f"Installing {package.character['name']} ({path.name})\n"
                    f'{destination} / {code.upper()} slot {chosen}')
                plan = package_import_plan(self.pack, path, code, chosen,
                    name=package.character['name'], author=package.character['author'])
                self.pack.commit(plan, imported_character=(code,chosen))
                self.successes.append(f'{path.name} → {code.upper()} slot {chosen}')
            except Exception as exc:
                self.failures.append(f'{path.name}: {exc}')
            self.progress.emit(completed + 1, f'Processed {path.name}')
        # Reconcile external changes and full inventory once after the batch.
        try:
            self.pack.reload()
        except Exception as exc:
            self.failures.append(f'Final library refresh: {exc}')


class MassExportWorker(QThread):
    progress = Signal(int, str)

    def __init__(self, pack, keys, folder, parent=None, *, grouped=True):
        super().__init__(parent)
        self.pack, self.keys, self.folder = pack, keys, Path(folder)
        self.grouped = grouped
        self.successes, self.failures = [], []

    def run(self):
        from .mkchara import build_package, write_package
        root = self.folder.resolve()/'CharacterExport' if self.grouped else self.folder.resolve()
        names = {}
        for completed,key in enumerate(self.keys):
            code,slot = key
            skin = self.pack.inventory.skins.get(key)
            label = skin.name if skin else f'{code.upper()} slot {slot}'
            self.progress.emit(completed, f'Exporting {label} — {CHARACTER_NAMES[CODE_IDS[code]]}')
            try:
                if root.is_symlink():
                    raise ValueError('CharacterExport cannot be a linked folder')
                payload = build_package(self.pack,code,slot)
                base = root/self.pack._safe_folder_name(CHARACTER_NAMES[CODE_IDS[code]]) if self.grouped else root
                if base.is_symlink():
                    raise ValueError('Base character output cannot be a linked folder')
                base.mkdir(parents=True,exist_ok=True)
                used = names.setdefault(code if self.grouped else '*',{p.name.casefold() for p in base.iterdir()})
                stem = self.pack._safe_folder_name(skin.name)
                if not self.grouped:stem += f' ({code.upper()}-{slot})'
                target = base/(stem+'.mkchara');suffix=2
                while target.name.casefold() in used or target.exists():
                    target = base/f'{stem} ({suffix}).mkchara';suffix+=1
                write_package(target,payload,overwrite=False)
                used.add(target.name.casefold())
                self.successes.append(f'{label} → {target.relative_to(self.folder.resolve())}')
            except Exception as exc:
                self.failures.append(f'{label}: {exc}')
            self.progress.emit(completed+1,f'Processed {label}')



class MassImportProgress(QDialog):
    """Block concurrent pack edits while archive work runs off the UI thread."""
    def __init__(self, pack, packages, parent=None, *, worker=None):
        super().__init__(parent)
        self.exporting = worker is not None
        self.setWindowTitle('Mass Export Progress' if self.exporting else 'Mass Import Progress')
        self.setMinimumWidth(560)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        layout = QVBoxLayout(self)
        self.current = QLabel('Preparing import…')
        self.current.setWordWrap(True)
        layout.addWidget(self.current)
        self.bar = QProgressBar()
        self.bar.setRange(0, len(packages))
        self.bar.setValue(0)
        self.bar.setFormat('%v / %m packages (%p%)')
        layout.addWidget(self.bar)
        layout.addWidget(note('Please wait for the export results.' if self.exporting else
            'Each installation creates a backup. Please wait for the results.'))
        self.worker = worker or MassImportWorker(pack, packages, self)
        self.worker.setParent(self)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.import_finished)

    def update_progress(self, completed, text):
        self.current.setText(text)
        self.bar.setValue(completed)

    def import_finished(self):
        self.bar.setValue(self.bar.maximum())
        self.current.setText('Export finished. Opening results…' if self.exporting else 'Import finished. Opening results…')
        self.accept()

    def reject(self):
        # Finish the active transaction before the dialog can close.
        pass

    def exec(self):
        QTimer.singleShot(0, self.worker.start)
        return super().exec()


class LibraryReadWorker(QThread):
    def __init__(self, read, parent=None):
        super().__init__(parent)
        self.read = read
        self.result, self.error = None, None

    def run(self):
        try:
            self.result = self.read()
        except Exception as exc:
            self.error = exc


class LibraryReadDialog(QDialog):
    def __init__(self, read, parent=None, *, title='Loading Character Library', message='Indexing resources and merging character text…'):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(430)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint,False)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel(message))
        progress=QProgressBar();progress.setRange(0,0);layout.addWidget(progress)
        self.worker=LibraryReadWorker(read,self)
        self.worker.finished.connect(self.accept)

    def reject(self):
        pass


def read_library_background(read,parent,**kwargs):
    dialog=LibraryReadDialog(read,parent,**kwargs)
    try:
        QTimer.singleShot(0,dialog.worker.start)
        dialog.exec();dialog.worker.wait()
        if dialog.worker.error is not None:
            raise dialog.worker.error
        return dialog.worker.result
    finally:
        dialog.deleteLater()


class ProfileAddContainer(QWidget):
    def sizeHint(self):
        return QSize(max(38, self.minimumWidth()), 30)


class ConnectionProfileTabBar(QTabBar):
    """Uniform profile tabs with native horizontal scrolling."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        self.add_button = QToolButton(self)
        self.add_button.setObjectName('AddConnectionProfile')
        self.add_button.setText('+')
        self.add_button.setToolTip('Add a separate character pack profile')
        self.add_button.setFixedSize(34, 30)
        self.add_button.setStyleSheet(
            'QToolButton#AddConnectionProfile { background: #263954; color: #e6eef8; '
            'border: 1px solid #3a5476; border-radius: 6px; font-weight: 700; }'
            'QToolButton#AddConnectionProfile:hover { background: #315076; }'
        )

    def attach_add_button(self, tabs):
        self.tabs_widget = tabs
        self.add_container = ProfileAddContainer(tabs)
        row = QHBoxLayout(self.add_container)
        row.setContentsMargins(4, 0, 0, 0)
        row.addWidget(self.add_button)
        row.addStretch()
        tabs.setCornerWidget(self.add_container, Qt.Corner.TopRightCorner)
        tabs.installEventFilter(self)
        self.update_add_spacing()

    def update_add_spacing(self):
        if not hasattr(self, 'add_container'):
            return
        # Absorb unused space after the button, not between it and the last tab.
        width = max(38, self.tabs_widget.width() - self.count() * 160 - 4)
        if self.add_container.width() != width:
            self.add_container.setFixedWidth(width)
            self.add_container.updateGeometry()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            QTimer.singleShot(0, self.update_add_spacing)
        return super().eventFilter(watched, event)

    def tabInserted(self, index):
        super().tabInserted(index)
        QTimer.singleShot(0, self.update_add_spacing)

    def tabRemoved(self, index):
        super().tabRemoved(index)
        QTimer.singleShot(0, self.update_add_spacing)

    def tabSizeHint(self, index):
        return QSize(160, 42)

    def minimumTabSizeHint(self, index):
        return self.tabSizeHint(index)


class OpenPackDialog(QDialog):
    """Switch between saved, isolated library connections without copying files."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Open Retro Rewind Character Library')
        self.setMinimumWidth(690)
        self.settings = QSettings('Retro Rewind', 'Character Manager')
        # Import older saved paths into the default profile.
        legacy = QSettings('WiiLoaded', 'CharacterManager')
        for key in ('characterPath', 'archivePath'):
            if not self.settings.value(key) and legacy.value(key):
                self.settings.setValue(key, legacy.value(key))

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        title = QLabel('Connect your character pack')
        title.setStyleSheet('font-size: 17pt; font-weight: 700; color: #f1f6fc;')
        layout.addWidget(title)
        layout.addWidget(note('Choose the entire Character folder and matching ReplacedAssets.szs. '
                              'Each tab has separate paths; opening a pack does not change its files.'))

        self.tabs = QTabWidget()
        self.profile_tab_bar = ConnectionProfileTabBar(self.tabs)
        self.tabs.setTabBar(self.profile_tab_bar)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.remove_profile)
        self.tabs.tabBarDoubleClicked.connect(self.rename_profile)
        self.add_profile_button = self.profile_tab_bar.add_button
        self.profile_tab_bar.attach_add_button(self.tabs)
        self.profile_tab_bar.setElideMode(Qt.TextElideMode.ElideRight)
        self.add_profile_button.clicked.connect(self.add_profile)
        layout.addWidget(self.tabs, 1)
        self._editors: list[ConnectionProfileEditor] = []
        for profile in load_profiles(self.settings):
            self._append_profile(profile)
        # The original profile must always remain available.
        self.tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
        active = str(self.settings.value(ACTIVE_KEY, 'default') or 'default')
        for i, editor in enumerate(self._editors):
            if editor.profile_id == active:
                self.tabs.setCurrentIndex(i)
                break

        controls = QHBoxLayout()
        controls.addStretch()
        controls.addWidget(button('Cancel', self.reject))
        controls.addWidget(button('Open Library', self.open, True))
        layout.addLayout(controls)
        self.pack = None

    @property
    def active_editor(self) -> ConnectionProfileEditor:
        return self._editors[self.tabs.currentIndex()]

    # Keep existing access to the active profile's fields for compatibility.
    @property
    def folder(self):
        return self.active_editor.folder

    @property
    def archive(self):
        return self.active_editor.archive

    @property
    def patches(self):
        return self.active_editor.patches

    @property
    def developer_checkbox(self):
        return self.active_editor.developer_checkbox

    def _append_profile(self, profile):
        editor = ConnectionProfileEditor(profile, self)
        self._editors.append(editor)
        index=self.tabs.addTab(editor, editor.profile_name)
        self.tabs.setTabToolTip(index,editor.profile_name)
        return editor

    def add_profile(self):
        index = len(self._editors) + 1
        name, ok = QInputDialog.getText(self, 'New Character Pack Profile',
                                         'Profile name:', text=f'Profile {index}')
        if not ok or not name.strip():
            return
        editor = self._append_profile(make_profile(name, {e.profile_id for e in self._editors}))
        self.tabs.setCurrentWidget(editor)
        editor.folder.setFocus()

    def rename_profile(self, index: int):
        if index < 0 or index >= len(self._editors):
            return
        editor = self._editors[index]
        name, ok = QInputDialog.getText(self, 'Rename Profile', 'Profile name:',
                                        text=editor.profile_name)
        if ok and name.strip():
            editor.profile_name = name.strip()
            self.tabs.setTabText(index, editor.profile_name)
            self.tabs.setTabToolTip(index,editor.profile_name)

    def remove_profile(self, index: int):
        if index <= 0 or index >= len(self._editors):
            return  # The original profile cannot be deleted.
        editor = self._editors[index]
        answer = QMessageBox.question(self, 'Remove Profile',
                    f'Remove profile "{editor.profile_name}"? The pack files are not deleted.',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.tabs.removeTab(index)
        self._editors.pop(index)
        editor.deleteLater()

    def open(self):
        editor = self.active_editor
        try:
            patch_path = Path(editor.patches.text()) if editor.patches.text().strip() else None
            character,archive = Path(editor.folder.text()),Path(editor.archive.text())
            developer = editor.developer_checkbox.isChecked()
            pack = read_library_background(lambda: CharacterPack(character,archive,patch_path,
                developer_mode=developer),self)
        except Exception as exc:
            QMessageBox.warning(self, 'Unable to open pack', str(exc))
            return
        # Save profile settings only after the connection succeeds.
        self.pack = pack
        profiles = [tab.snapshot() for tab in self._editors]
        active = editor.profile_id
        # The resolved/suggested Patches path belongs to this profile only.
        profiles[self.tabs.currentIndex()]['patches'] = str(pack.patches_path)
        save_profiles(self.settings, profiles, active)
        self.accept()


class ModelExplorerDialog(QDialog):
    """Shared textured bind-pose inspector; BrawlCrate covers advanced effects."""
    def __init__(self, entries, *, variant=None, allow_driver=False, parent=None, candidates=None):
        super().__init__(parent)
        self.setWindowTitle('Model Explorer · BRRES / SZS')
        self.setWindowFlags(self.windowFlags() |
                            Qt.WindowType.WindowMinMaxButtonsHint)
        self.resize(1160, 720)
        self.entries = entries
        self.candidates = candidates if candidates is not None else discover_models(entries, source_variant=variant)
        self.chosen = None
        self.settings = QSettings('Retro Rewind', 'Character Manager')
        self.preview_temp = _MODEL_PREVIEW_FILES
        layout = QVBoxLayout(self)
        title = QLabel('Explore character models')
        title.setStyleSheet('font-size: 16pt; font-weight: 700;')
        layout.addWidget(title)
        layout.addWidget(note('Select a BRRES and then an MDL0 variant for a textured bind-pose preview. Drag to orbit and scroll to zoom. '
                              'Unsupported effects are listed below. Use BrawlCrate for animation and pose checks.'))
        self.table = QTableWidget(len(self.candidates), 3)
        self.table.setHorizontalHeaderLabels(['Source SZS / BRRES', 'Contents', 'Size'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for index, model in enumerate(self.candidates):
            source_item=QTableWidgetItem(model.label)
            source_item.setToolTip(model.label)
            self.table.setItem(index, 0, source_item)
            self.table.setItem(index, 1, QTableWidgetItem(model.category))
            self.table.setItem(index, 2, QTableWidgetItem(f'{model.size:,} bytes'))
        browser = QSplitter(Qt.Orientation.Horizontal)
        browser.addWidget(self.table)
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(4, 0, 4, 0)
        self.viewport = MeshPreviewWidget()
        preview_layout.addWidget(self.viewport, 1)
        preview_controls = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(170)
        self.model_combo.setToolTip('Choose one MDL0, including LOD and alternate models. Default selection is a heuristic.')
        self.model_combo.currentIndexChanged.connect(self.select_model_variant)
        preview_controls.addWidget(self.model_combo)
        preview_controls.addStretch()
        self.wireframe_box = QCheckBox('Wireframe')
        self.wireframe_box.toggled.connect(self.viewport.set_wireframe)
        preview_controls.addWidget(self.wireframe_box)
        preview_controls.addWidget(button('Reset view', self.viewport.reset_view))
        preview_layout.addLayout(preview_controls)
        browser.addWidget(preview_panel)
        browser.setSizes([560, 580])
        layout.addWidget(browser, 1)
        self.details = note('Select a model to inspect its geometry. Open in BrawlCrate for full materials and animation.')
        layout.addWidget(self.details)
        self._preview_cache = {}
        self._model_future = None
        self._pending_model = None
        self._model_timer = QTimer(self)
        self._model_timer.setInterval(30)
        self._model_timer.timeout.connect(self.poll_model)
        self._model_timer.start()
        self.finished.connect(self.stop_model_worker)
        self.table.itemSelectionChanged.connect(self.update_selection)
        self.table.cellDoubleClicked.connect(lambda row, column: self.update_selection())
        controls = QHBoxLayout()
        controls.addWidget(button('View in BrawlCrate…' if sys.platform == 'win32' else 'External Viewer…', self.view_in_brawlcrate))
        self.use_button = button('Extract standalone Driver BRRES', self.choose_driver, True)
        self.use_button.setVisible(allow_driver)
        self.use_button.setToolTip('Extract the whole selected BRRES, including MDL0 variants, for the standalone/menu Driver resource. Original kart/bike archives and their drivers are preserved unchanged.')
        controls.addWidget(self.use_button)
        controls.addStretch()
        controls.addWidget(button('Close', self.reject))
        layout.addLayout(controls)
        if self.candidates:
            recommended = next((i for i, c in enumerate(self.candidates)
                                if 'Menu model' in c.category), None)
            if recommended is None:
                recommended = next((i for i, c in enumerate(self.candidates)
                                    if not c.archive_member and c.is_driver), None)
            if recommended is None:
                recommended = next((i for i, c in enumerate(self.candidates)
                                    if c.category == 'Race driver · Kart'), 0)
            self.table.selectRow(recommended)
        else:
            self.details.setText('No usable BRRES models found in this source.')
        self.update_selection()

    def stop_model_worker(self):
        self._model_timer.stop()
        self._pending_model = None
        if self._model_future is not None:
            self._model_future.cancel()

    def update_selection(self):
        i = self.table.currentRow()
        valid = 0 <= i < len(self.candidates)
        self.use_button.setEnabled(valid and self.candidates[i].category not in (
            'Vehicle (not driver)', 'Animations (not a driver model)', 'AllKart / other model'))
        self._pending_model = (i, None) if valid else None
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.blockSignals(False)
        self.viewport.set_mesh(None)
        self.details.setText('Reading selected BRRES…' if valid else 'No model selected')

    def select_model_variant(self, index):
        if index >= 0:
            self._pending_model = (self.table.currentRow(), index)
            self.viewport.set_mesh(None)
            self.details.setText('Reading selected MDL0 variant…')

    def poll_model(self):
        if self._model_future is not None and self._model_future.done():
            key, future = self._model_future_key, self._model_future
            self._model_future = None
            try:
                variants, chosen, mesh, error = future.result()
                if key == self._pending_model:
                    self._pending_model = None
                    self.model_combo.blockSignals(True)
                    self.model_combo.clear()
                    for v in variants:
                        self.model_combo.addItem(v.name + (' · LOD' if v.is_lod else '') + f' (v{v.version})')
                    self.model_combo.setCurrentIndex(chosen)
                    self.model_combo.blockSignals(False)
                    self.viewport.set_mesh(mesh)
                    if mesh is not None:
                        self.details.setText(f'{mesh.name} · {len(mesh.vertices):,} vertices · {len(mesh.triangles):,} triangles\n'
                                             + '\n'.join(mesh.warnings))
                    else:
                        self.details.setText(f'{variants[chosen].name}: {error}. Select another variant or try BrawlCrate.')
            except Exception as exc:
                if key == self._pending_model:
                    self._pending_model = None
                    self.viewport.set_mesh(None)
                    self.details.setText(f'Embedded preview unavailable: {exc}. Try BrawlCrate.')
        if self._model_future is None and self._pending_model is not None:
            self._model_future_key = self._pending_model
            row, selected = self._pending_model
            candidate = self.candidates[row]
            def load():
                data = extract_model_bytes(self.entries, candidate)
                variants = list_models(data)
                chosen = default_model(variants) if selected is None else selected
                try:
                    return variants, chosen, decode_brres(data, chosen), ''
                except PreviewDecodeError as exc:
                    return variants, chosen, None, str(exc)
            self._model_future = _MODEL_POOL.submit(load)

    def choose_driver(self):
        i = self.table.currentRow()
        if i < 0 or not self.use_button.isEnabled():
            return
        candidate = self.candidates[i]
        self.chosen = candidate
        self.accept()

    def view_in_brawlcrate(self):
        i = self.table.currentRow()
        if i < 0 or i >= len(self.candidates):
            return
        key = 'brawlcrateExe' if sys.platform == 'win32' else 'externalModelViewer'
        exe = str(self.settings.value(key, '') or '')
        if not exe or not Path(exe).exists():
            title = 'Locate BrawlCrate.exe' if sys.platform == 'win32' else 'Choose a BRRES viewer'
            filter_ = 'BrawlCrate (BrawlCrate.exe);;Executables (*.exe)' if sys.platform == 'win32' else 'Applications (*)'
            exe, _ = QFileDialog.getOpenFileName(self, title, '', filter_)
            if not exe:
                return
            self.settings.setValue(key, exe)
        candidate = self.candidates[i]
        try:
            data = extract_model_bytes(self.entries, candidate)
            # Include a hash and readable source stem in temp filename to avoid collisions.
            stem = Path(candidate.source_path).stem[:34]
            token = hashlib.sha256((candidate.label).encode('utf-8')).hexdigest()[:10]
            target = Path(self.preview_temp.name) / f'{stem}-{token}.brres'
            target.write_bytes(data)
            command = ['open', '-a', exe, str(target)] if sys.platform == 'darwin' and exe.endswith('.app') else [exe, str(target)]
            subprocess.Popen(command)
        except Exception as exc:
            QMessageBox.warning(self, 'Could not view model',
                                f'Unable to launch the viewer with the selected BRRES:\n{exc}')


class SlotSpinBox(QSpinBox):
    """Keep native stepping/hit areas, with visible arrows in the dark theme."""
    def paintEvent(self,event):
        super().paintEvent(event)
        option=QStyleOptionSpinBox();self.initStyleOption(option)
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for control,direction,step in ((QStyle.SubControl.SC_SpinBoxUp,-1,QSpinBox.StepEnabledFlag.StepUpEnabled),
                                       (QStyle.SubControl.SC_SpinBoxDown,1,QSpinBox.StepEnabledFlag.StepDownEnabled)):
            rect=self.style().subControlRect(QStyle.ComplexControl.CC_SpinBox,option,control,self)
            center=rect.center()
            enabled=self.isEnabled() and bool(self.stepEnabled()&step)
            painter.setBrush(QColor('#b7cbe2' if enabled else '#64758b'))
            painter.drawPolygon(QPolygonF([QPointF(center.x()-3,center.y()-direction*2),
                                           QPointF(center.x()+3,center.y()-direction*2),
                                           QPointF(center.x(),center.y()+direction*2)]))


class ImportWizard(QDialog):
    def __init__(self, pack: CharacterPack, default_code: str, parent=None):
        super().__init__(parent)
        self.pack = pack
        self.setWindowTitle('Add Custom Character')
        self.setMinimumSize(720,570)
        self.resize(820,min(820,self.screen().availableGeometry().height()-80))
        outer=QVBoxLayout(self)
        content=QWidget();shell=QVBoxLayout(content)
        scroll=QScrollArea();scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame);scroll.setWidget(content)
        outer.addWidget(scroll,1)
        heading=QLabel('Import a custom skin')
        heading.setStyleSheet('font-size: 16pt; font-weight: 700;')
        shell.addWidget(heading)
        shell.addWidget(note('Import a .mkchara character, mod ZIP, folder, or driver BRRES. The source must match its vanilla character skeleton.'))
        group=QGroupBox('Source assets');group_layout=QVBoxLayout(group)
        source_row=QHBoxLayout()
        self.source=QLineEdit();self.source.setPlaceholderText('Select a .mkchara, ZIP, mod folder or .brres')
        source_row.addWidget(self.source,1)
        source_row.addWidget(button('File…',self.browse_file))
        source_row.addWidget(button('Folder…',self.browse_dir))
        group_layout.addLayout(source_row)
        self.discovery=note('No source selected')
        group_layout.addWidget(self.discovery)
        model_row = QHBoxLayout()
        self.model_button = button('Explore / View Models…', self.explore_models)
        model_row.addWidget(self.model_button)
        self.driver_note = note('Model extraction optional; use when a mod has no standalone Driver BRRES.')
        model_row.addWidget(self.driver_note, 1)
        group_layout.addLayout(model_row)
        variant_row = QHBoxLayout()
        self.variant_label = QLabel('Mod variant:')
        self.variant = QComboBox()
        self.variant.setToolTip('Choose one version when a ZIP contains multiple installation variants.')
        variant_row.addWidget(self.variant_label)
        variant_row.addWidget(self.variant, 1)
        self.variant_box = QWidget()
        self.variant_box.setLayout(variant_row)
        self.variant_box.hide()
        self._probe_names = []
        self.variant.currentIndexChanged.connect(self._update_variant_discovery)
        group_layout.addWidget(self.variant_box)
        self._last_probed_source = None
        self.driver_choice = None
        self.source.editingFinished.connect(self.probe)
        shell.addWidget(group)
        fields=QGroupBox('Install location and metadata');grid=QFormLayout(fields)
        self.base=QComboBox()
        for code in DISPLAY_CODES:
            self.base.addItem(f'{CHARACTER_NAMES[CODE_IDS[code]]} ({code.upper()})',code)
        self.base.setCurrentIndex(self.base.findData(default_code))
        self.base.currentIndexChanged.connect(self.choose_default_slot)
        self.base.currentIndexChanged.connect(self.refresh_component_base)
        grid.addRow('Replaces:',self.base)
        self.target = QComboBox()
        self.target.addItem('Patches/ — install loose overrides (recommended)', 'patches')
        if self.pack.developer_mode:
            self.target.addItem('Character/ + ReplacedAssets.szs — edit distribution', 'library')
        self.target.currentIndexChanged.connect(self.update_install_mode)
        grid.addRow('Destination:', self.target)
        self.slot=SlotSpinBox();self.slot.setRange(1,100)
        self._choosing_slot = False
        self._slot_manually_changed = False
        self.slot.valueChanged.connect(self.mark_manual_slot)
        self.mode=QComboBox();self.mode.addItems(['Insert here (shift existing slots)','Install into empty slot'])
        self.mode.setCurrentIndex(1)  # Never shift distribution slots by default.
        loc=QHBoxLayout();loc.addWidget(self.slot);loc.addWidget(self.mode,1)
        loc_widget=QWidget();loc_widget.setLayout(loc);grid.addRow('New slot:',loc_widget)
        self.name=QLineEdit();self.name.setPlaceholderText('Displayed character name');grid.addRow('Character name:',self.name)
        self.author=QLineEdit();self.author.setPlaceholderText('Optional author credit');grid.addRow('Creator:',self.author)
        shell.addWidget(fields)
        optional=QGroupBox('Optional images · PNG or TPL (automatically detected)')
        optional_layout=QFormLayout(optional)
        self.portrait=QLineEdit();self.portrait.setPlaceholderText('CSS portrait (PNG or TPL) · optional')
        portrait_row=QHBoxLayout();portrait_row.addWidget(self.portrait,1)
        portrait_row.addWidget(button('Browse…',lambda:self.browse_png(self.portrait)))
        portrait_widget=QWidget();portrait_widget.setLayout(portrait_row)
        optional_layout.addRow('CSS portrait:',portrait_widget)
        self.map=QLineEdit();self.map.setPlaceholderText('Minimap icon (PNG or TPL) · optional')
        map_row=QHBoxLayout();map_row.addWidget(self.map,1)
        map_row.addWidget(button('Browse…',lambda:self.browse_png(self.map)))
        map_widget=QWidget();map_widget.setLayout(map_row)
        optional_layout.addRow('Minimap icon:',map_widget)
        preview_row = QHBoxLayout()
        self.package_icon_previews = {}
        for category, title, size in (('Portrait', 'Detected CSS', 72), ('Map', 'Detected minimap', 48)):
            holder = QVBoxLayout()
            holder.addWidget(note(title))
            preview = QLabel('Not included')
            preview.setFixedSize(110, 85)
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview.setStyleSheet('background: #182538; border: 1px solid #374a63; border-radius: 5px;')
            holder.addWidget(preview)
            preview_row.addLayout(holder)
            self.package_icon_previews[category] = (preview, size)
        preview_row.addStretch()
        self.package_preview_widget = QWidget()
        self.package_preview_widget.setLayout(preview_row)
        self.package_preview_widget.hide()
        self._icon_preview_entries = None
        self.portrait.editingFinished.connect(self.refresh_icon_previews)
        self.map.editingFinished.connect(self.refresh_icon_previews)
        optional_layout.insertRow(0, 'Detected icons:', self.package_preview_widget)
        shell.addWidget(optional)
        shell.addWidget(note('Standard Mode installs into empty Patches/ slots only. '
                             'Developer Mode can change distribution slots and BMG data. '
                             'Every installation is previewed and backed up.'))
        controls=QHBoxLayout();controls.addStretch();controls.addWidget(button('Cancel',self.reject))
        controls.addWidget(button('Review Installation',self.validate,True));outer.addLayout(controls)
        self.plan=None
        if self.pack.developer_mode:
            self.target.setCurrentIndex(self.target.findData('library'))
        self.update_install_mode()
        self.choose_default_slot()

    def update_install_mode(self):
        patch = self.target.currentData() == 'patches'
        if patch:
            self.mode.setCurrentIndex(1)
        self.mode.setEnabled(not patch)
        self.mode.setToolTip('Patches cannot safely shift distribution slots.' if patch else
                             'Developer Mode edits Character/ and CharaRR.bmg directly; active name overrides are synchronized.')

    def mark_manual_slot(self):
        if not self._choosing_slot:
            self._slot_manually_changed = True

    def choose_default_slot(self):
        code=self.base.currentData()
        if code is None:return
        self._choosing_slot = True
        try:
            if Path(self.source.text()).suffix.lower() == '.mkchara':
                try:
                    free = self.pack.next_import_slot(code)
                    self.slot.setToolTip('Next slot after all installed resources and text reservations; you may override it.')
                except ValueError as exc:
                    free = 100
                    self.slot.setToolTip(str(exc) + '. Choose a free slot manually if available.')
            else:
                used={s.slot for s in self.pack.inventory.by_character(code)}
                free=next((s for s in range(1,101) if s not in used),100)
            self.slot.setValue(free)
            self._slot_manually_changed = False
        finally:
            self._choosing_slot = False

    def browse_file(self):
        path,_=QFileDialog.getOpenFileName(self,'Choose character assets',self.source.text(),'Character assets (*.mkchara *.zip *.brres *.szs);;Character packages (*.mkchara);;Mod assets (*.zip *.brres *.szs);;All files (*)')
        if path:self.source.setText(path);self.probe()

    def browse_dir(self):
        path=QFileDialog.getExistingDirectory(self,'Choose mod folder',self.source.text())
        if path:self.source.setText(path);self.probe()

    def browse_png(self,target):
        path,_=QFileDialog.getOpenFileName(self,'Choose character icon',target.text(),'Character icons (*.png *.tpl);;PNG (*.png);;TPL (*.tpl)')
        if path:
            target.setText(path)
            self.refresh_icon_previews()

    def probe(self):
        self._icon_preview_entries = None
        self.show_package_icons()
        if not self.source.text().strip():
            self._last_probed_source=None;self._probe_names=[];self.driver_choice=None
            self.variant_box.hide();self.discovery.setText('No source selected')
            self.driver_note.setText('Model extraction optional; use when a mod has no standalone Driver BRRES.')
            return
        try:
            import zipfile
            path=Path(self.source.text())
            self.target.setEnabled(True)
            self.driver_choice = None
            self.driver_note.setText('Model extraction optional; use when a mod has no standalone Driver BRRES.')
            if path.suffix.lower()=='.mkchara':
                from .mkchara import read_package
                package=read_package(path)
                self.target.setCurrentIndex(self.target.findData('library' if self.pack.developer_mode else 'patches'))
                self.target.setEnabled(False)
                self.show_package_icons(package)
                names=[name for name,_ in package.entries()]
                if self._last_probed_source != str(path):
                    self.name.setText(package.character['name'])
                    self.author.setText(package.character['author'])
                    if not self._slot_manually_changed:
                        self.choose_default_slot()
            elif path.is_dir(): names=[p.relative_to(path).as_posix() for p in path.rglob('*') if p.is_file()]
            elif path.suffix.lower()=='.zip':
                with zipfile.ZipFile(path) as z:names=z.namelist()
            else:names=[path.name]
            variants = available_import_variants(names)
            old_variant = self.variant.currentData()
            self.variant.blockSignals(True)
            self.variant.clear()
            for variant_name in variants:
                self.variant.addItem('Default resources' if variant_name == DEFAULT_RESOURCE_VARIANT else variant_name.rsplit('/', 1)[-1], variant_name)
            if variants:
                preferred = old_variant if old_variant in variants else next(
                    (name for name in variants if name.rsplit('/', 1)[-1].casefold() == 'full slot'), variants[0])
                self.variant.setCurrentIndex(self.variant.findData(preferred))
            self.variant_box.setVisible(bool(variants))
            self.variant.blockSignals(False)
            self._last_probed_source = str(path)
            self._probe_names = names
            self._update_variant_discovery()
        except Exception as e:
            self.variant.blockSignals(False)
            self._last_probed_source = None
            self._probe_names = []
            self.variant_box.hide()
            self.discovery.setText(f'Unable to inspect: {e}')

    def refresh_icon_previews(self):
        self.show_package_icons(entries=self._icon_preview_entries)

    def show_package_icons(self, package=None, entries=None):
        available = list(package.assets + package.sources) if package is not None else entries
        self.package_preview_widget.setVisible(available is not None)
        from .tpl import detected_icons
        detected = detected_icons(available) if available is not None else {}
        for category, (label, size) in self.package_icon_previews.items():
            label.clear(); label.setText('Not detected'); label.setToolTip('')
            if available is None:
                continue
            candidates = detected[category]
            match = candidates[0] if candidates else None
            explicit = self.portrait.text() if category == 'Portrait' else self.map.text()
            if explicit and Path(explicit).is_file():
                match = (explicit, Path(explicit).read_bytes())
            if match is None:
                continue
            try:
                if match[0].lower().endswith('.png'):
                    pixmap = QPixmap()
                    import io
                    from PIL import Image
                    with Image.open(io.BytesIO(match[1])) as picture:
                        if max(picture.size) > 4096:
                            raise ValueError('Icon exceeds 4096 pixels')
                    if not pixmap.loadFromData(match[1], 'PNG'):
                        raise ValueError('Invalid PNG image')
                else:
                    pixmap = tpl_pixmap(match[1])
                label.setPixmap(pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
                label.setToolTip('Detected icon: ' + match[0] +
                    (f'\n{len(candidates)} candidates; optional image selection overrides this choice.' if len(candidates) > 1 else ''))
            except (ValueError, OSError) as exc:
                label.setText('Invalid icon'); label.setToolTip(str(exc))

    def explore_models(self):
        source = Path(self.source.text())
        if not source.exists():
            QMessageBox.warning(self, 'Missing source', 'Select a .mkchara, ZIP, folder or BRRES first.')
            return
        try:
            variant = self.variant.currentData() if not self.variant_box.isHidden() else None
            def read_models():
                entries = source_entries(source)
                return entries,discover_models(entries,source_variant=variant)
            entries,candidates = read_library_background(read_models,self,
                title='Loading Models',message='Reading model resources…')
            dialog = ModelExplorerDialog(entries,variant=variant,allow_driver=True,parent=self,candidates=candidates)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.chosen:
                self.driver_choice = dialog.chosen
                self.driver_note.setText('Standalone/menu driver: ' + dialog.chosen.label + '\nKart/bike archives remain unchanged.')
                self.driver_note.setToolTip(dialog.chosen.label)
            dialog.deleteLater()
        except Exception as exc:
            QMessageBox.warning(self, 'Cannot inspect models', str(exc))

    def refresh_component_base(self):
        if getattr(self, '_choosing_component', False) or not self._probe_names:
            return
        codes = {asset.code for _, asset in normalized_import_files(self._probe_names)}
        if len(codes) > 1 and Path(self.source.text()).suffix.lower() != '.mkchara':
            self._update_variant_discovery(keep_base=True)

    def _update_variant_discovery(self, _index=None, *, keep_base=False):
        self.driver_choice = None
        self.driver_note.setToolTip('')
        self.driver_note.setText('Model extraction optional; use when a mod has no standalone Driver BRRES.')
        selected = self.variant.currentData() if not self.variant_box.isHidden() else None
        names = [name for name, _ in select_import_entries([(name,b'') for name in self._probe_names], selected)]
        entries = normalized_import_files(names)
        cats = {}
        for _, asset in entries:
            cats[asset.category] = cats.get(asset.category, 0) + 1
        codes = {asset.code for _, asset in entries}
        if codes and not keep_base:
            code = preferred_import_code(names)
            self._choosing_component = True
            try:
                self.base.setCurrentIndex(self.base.findData(code))
            finally:
                self._choosing_component = False
        detail = f'{len(entries)} recognized files · ' + ', '.join(f'{cat}: {count}' for cat, count in cats.items())
        kart=sum('_kart' in rel.casefold() for rel,a in entries if a.category=='RaceKart')
        bike=sum('_bike' in rel.casefold() for rel,a in entries if a.category=='RaceKart')
        if kart and bike:
            detail += f'\nSeparate race models: {kart} kart / {bike} bike archives; vehicle textures and animations stay inside their original SZS files.'
        if any(a.category=='Driver' and rel.casefold().endswith('_menu.brres') for rel,a in entries):
            self.driver_note.setText('Menu BRRES detected for standalone Driver. Kart/bike drivers remain separate.\nUnmapped Common/menu animation resources are preserved as source data; game-side support may be required.')
        try:
            source=source_entries(Path(self.source.text()))
            if Path(self.source.text()).suffix.lower() != '.mkchara':
                source = select_import_entries(source, selected)
            if len(codes) > 1 and Path(self.source.text()).suffix.lower() != '.mkchara':
                source = [(name,data) for name,data in source
                          if not ((asset := parse_asset(name,source_import=True)) and asset.code != self.base.currentData())]
                if self.base.currentData() != preferred_import_code(names):
                    source = [(name,data) for name,data in source
                              if not (name.lower().endswith(('.png','.tpl')) and not parse_asset(name,source_import=True))]
            self._icon_preview_entries = [entry for entry in source if entry[0].lower().endswith(('.tpl', '.png'))]
            self.refresh_icon_previews()
            self.driver_choice=automatic_driver_candidate(source, code=None if Path(self.source.text()).suffix.lower()=='.mkchara' else self.base.currentData())
            if Path(self.source.text()).suffix.lower()=='.mkchara' and not self.driver_choice:
                driver=next((entry for entry in source if (asset:=parse_asset(entry[0],source_import=True)) and asset.category=='Driver'),None)
                if driver:
                    self.driver_note.setText('Packaged standalone Driver: '+driver[0]+'\nUse Explore / View Models to preview or override. Kart/bike archives remain separate.')
                    self.driver_note.setToolTip(driver[0])
            if self.driver_choice:
                variants=list_models(extract_model_bytes(source,self.driver_choice))
                model=variants[default_model(variants)].name
                self.driver_note.setText('Automatic '+self.driver_choice.category+': '+model+'\n'+self.driver_choice.label+
                                         '\nKart/bike archives remain separate. Use Explore / View Models to override.')
                self.driver_note.setToolTip(self.driver_choice.label)
        except (OSError,ValueError) as exc:
            self.driver_note.setText('Automatic model selection unavailable: '+str(exc)+'\nUse Explore / View Models.')
        if len(codes) == 1:
            detail += f' · Base {next(iter(codes)).upper()}'
        elif len(codes) > 1:
            detail += '\nBundle bases: '+', '.join(sorted(code.upper() for code in codes))+' · Importing '+self.base.currentData().upper()+' only; other components are preserved as source data.'
        if self.variant.count() > 1 and self.variant_box.isVisible():
            detail += f' · {self.variant.count()} variants available'
        self.discovery.setText(detail)

    def validate(self):
        if not self.source.text().strip():
            QMessageBox.warning(self,'Missing source','Choose character mod files to import.');return
        if self._last_probed_source != self.source.text():
            self.probe()
        if not self.name.text().strip():
            QMessageBox.warning(self,'Missing name','Enter the display name for the new character.');return
        extra={}
        if self.portrait.text().strip():extra['Portrait']=Path(self.portrait.text())
        if self.map.text().strip():extra['Map']=Path(self.map.text())
        try:
            kwargs = dict(name=self.name.text().strip(), author=self.author.text().strip(),
                extra_images=extra, source_variant=self.variant.currentData() if not self.variant_box.isHidden() else None,
                driver_candidate=self.driver_choice)
            source = Path(self.source.text())
            if source.suffix.lower() == '.mkchara':
                self.plan = package_import_plan(self.pack, source, self.base.currentData(), self.slot.value(),
                    insert=self.mode.currentIndex()==0, **kwargs)
            elif self.target.currentData() == 'patches':
                self.plan = self.pack.import_patch_skin(source, self.base.currentData(), self.slot.value(), **kwargs)
            else:
                self.plan = self.pack.import_skin(source, self.base.currentData(), self.slot.value(),
                    insert=self.mode.currentIndex()==0, **kwargs)
        except Exception as e:
            QMessageBox.warning(self,'Cannot import',str(e));return
        self.accept()


class PreviewDialog(QDialog):
    def __init__(self,plan:EditPlan,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Review Changes')
        self.resize(760,620)
        layout=QVBoxLayout(self)
        title=QLabel('Review changes before applying')
        title.setStyleSheet('font-size: 16pt; font-weight: 700;')
        layout.addWidget(title)
        layout.addWidget(note('Nothing is written until you confirm. A dated backup is created before files are modified.'))
        self.text=QPlainTextEdit(plan.preview());self.text.setReadOnly(True)
        self.text.setFont(QFont('Consolas',9))
        layout.addWidget(self.text,1)
        controls=QHBoxLayout();controls.addStretch()
        controls.addWidget(button('Cancel',self.reject))
        controls.addWidget(button('Apply Changes',self.accept,True))
        layout.addLayout(controls)


class ResourceEditorDialog(QDialog):
    """Fullscreen view for staged physical resource filename edits."""
    def __init__(self, pack: CharacterPack, code: str, slot: int, parent=None):
        super().__init__(parent)
        self.pack, self.code, self.slot = pack, code, slot
        self.skin = pack.inventory.skins[(code, slot)]
        self.plan = None
        self.editable = pack.can_edit_skin(code, slot)
        self.setWindowTitle(f'Resources — {self.skin.name or code.upper()} · Slot {slot}')
        # Use a separate window for the resource editor.
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowSystemMenuHint
                            | Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowCloseButtonHint)
        self.resize(1120, 760)
        layout = QVBoxLayout(self)
        heading = QLabel('Installed resources')
        heading.setStyleSheet('font-size: 17pt; font-weight: 700;')
        layout.addWidget(heading)
        layout.addWidget(note(f'{self.skin.name or code.upper()} · {code.upper()} slot {slot} · '
                              f'{len(self.skin.files)} files · '
                              + ('Edit filenames below, then Save Changes.' if self.editable else
                                 'Read-only distribution character. Enable Developer Mode to rename files.')))
        self.table = QTableWidget(len(self.skin.files), 4)
        self.table.setToolTip('Select a resource to inspect it, or edit permitted filenames directly.')
        self.table.setHorizontalHeaderLabels(('Type', 'Filename — click to edit', 'Default filename', 'Folder'))
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # The filename column uses actual QLineEdit widgets for reliable one-click editing.
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.assets = list(self.skin.files)
        self.editable_rows: set[int] = set()
        self.filename_inputs: dict[int, QLineEdit] = {}
        for i, asset in enumerate(self.assets):
            physical = pack.asset_path(asset.relpath)
            default = Path(asset.destination(slot)).name
            is_patch_asset = physical.resolve().is_relative_to(pack.patches_path)
            row_editable = pack.developer_mode or is_patch_asset
            if row_editable:
                self.editable_rows.add(i)
            try:
                folder = physical.parent.relative_to(pack.patches_path if is_patch_asset else pack.character).as_posix()
            except ValueError:
                folder = physical.parent.name
            for j, value in enumerate((asset.category, physical.name, default, folder)):
                if j == 1 and row_editable:
                    # Item flags + double-click editing were unreliable and hard to discover.
                    # Keep a visible text field in every filename cell that is actually editable.
                    editor = QLineEdit(physical.name, self.table)
                    editor.setClearButtonEnabled(False)
                    editor.setToolTip('Click here and type a new filename, then Save Changes.')
                    editor.setAccessibleName(f'Filename for {asset.category}, row {i + 1}')
                    self.filename_inputs[i] = editor
                    self.table.setCellWidget(i, j, editor)
                else:
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if j == 1:
                        item.setToolTip('Read-only RR distribution resource. Reopen with Developer Mode to rename.')
                        item.setForeground(QColor('#95a5bd'))
                    self.table.setItem(i, j, item)
            self.table.setRowHeight(i, 45)
        # Character-level right-click operations are intentionally disabled for now.
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.table.viewport().setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        # Filename editors retain Qt's standard text edit menu (copy/paste/etc.).
        layout.addWidget(self.table, 1)
        status = (f'{len(self.editable_rows)} editable filename(s) · Click a filename box to type.'
                  if self.editable_rows else
                  'All listed resources belong to the RR distribution and are read-only in Standard Mode. '
                  'Reopen this library with Developer Mode enabled to rename them.')
        layout.addWidget(note(status))
        warning = note('Warning: Retro Rewind expects specific filenames. Custom names may stop a model, icon, '
                       'vehicle, or sound from loading. The manager keeps renamed resources visible; '
                       'every Save creates a restorable backup.')
        layout.addWidget(warning)
        controls = QHBoxLayout()
        self.revert_button = button('Revert to Default Filenames', self.revert_defaults)
        self.revert_button.setEnabled(bool(self.editable_rows))
        controls.addWidget(self.revert_button)
        controls.addWidget(button('Discard Unsaved Edits', self.discard_changes))
        controls.addStretch()
        controls.addWidget(button('Close', self.reject))
        self.save_button = button('Save Changes', self.save, True)
        self.save_button.setEnabled(bool(self.editable_rows))
        controls.addWidget(self.save_button)
        layout.addLayout(controls)

    def show_resource_context(self, point):
        row = self.table.rowAt(point.y())
        if row >= 0:
            self.show_resource_context_row(row, self.table.viewport().mapToGlobal(point))

    def show_resource_context_row(self, row, global_pos):
        if not 0 <= row < len(self.assets):
            return
        resource_context_menu(self, self.pack, self.code, self.slot,
                              self.assets[row], global_pos, self._stage_context_plan)

    def _stage_context_plan(self, plan):
        # MainWindow.open_resource_editor() presents the normal confirmation once.
        self.plan = plan
        self.accept()

    def discard_changes(self):
        for row, asset in enumerate(self.assets):
            editor = self.filename_inputs.get(row)
            if editor is not None:
                editor.setText(self.pack.asset_path(asset.relpath).name)

    def revert_defaults(self):
        for row, asset in enumerate(self.assets):
            editor = self.filename_inputs.get(row)
            if editor is not None:
                editor.setText(Path(asset.destination(self.slot)).name)

    def save(self):
        if not self.editable_rows:
            return
        # Include original names for inherited read-only files: the backend will
        # validate and protect those resources as well, rather than silently dropping them.
        names = {asset.relpath: (self.filename_inputs[row].text()
                                  if row in self.filename_inputs
                                  else self.pack.asset_path(asset.relpath).name)
                 for row, asset in enumerate(self.assets)}
        try:
            self.plan = self.pack.rename_resources(self.code, self.slot, names)
        except Exception as exc:
            QMessageBox.warning(self, 'Cannot rename resource', str(exc))
            return
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self,pack:CharacterPack):
        super().__init__()
        self.pack=pack
        profile=QSettings("Retro Rewind","Character Manager").value("deployment/profile",pack.deployment_profile)
        self.pack.deployment_profile=profile if profile in ('rr','wiiloaded','direct') else 'rr' 
        self.setWindowTitle(f'Retro Rewind Character Manager · v{__version__}')
        self.resize(1510,940)
        self.setMinimumSize(1130,690)
        self.current_code='bmr'
        self.current_slot=None
        self.selected_characters = set()
        self._restoring_selection = False
        self._icon_cache = OrderedDict()
        self._icon_cache_bytes = 0
        self._detail_key = None
        self._selection_started = False
        self._thumbnail_queue = []
        self._thumbnail_timer = QTimer(self)
        self._thumbnail_timer.setInterval(0)
        self._thumbnail_timer.timeout.connect(self.load_thumbnail_chunk)
        # Keys are original slots still on disk; values are staged destinations.
        self.pending_patch_slots = {}
        self.staging_patches = False
        self.independent_normalize_codes = set()
        self.pending_organization = False
        self.setup_menu()
        self.setup_content()
        self.reload_view(initial=True)
        self._update_worker=None
        QTimer.singleShot(3000,lambda:self.check_updates(False))

    def action(self,menu,text,callback,shortcut=None):
        a=QAction(text,self)
        a.triggered.connect(callback)
        if shortcut:a.setShortcut(QKeySequence(shortcut))
        menu.addAction(a)
        return a

    def setup_menu(self):
        bar=self.menuBar()
        file=bar.addMenu('&File')
        self.action(file,'Open Character Pack…',self.open_pack,'Ctrl+O')
        self.action(file,'Refresh',self.refresh,'F5')
        self.action(file,'Set revo_kart.brsar…',self.set_voice_baseline)
        file.addSeparator()
        self.action(file,'Exit',self.close,'Alt+F4')
        actions=bar.addMenu('&Characters')
        self.action(actions,'Import Character…',self.import_character,'Ctrl+I')
        self.action(actions,'Mass Import (.mkchara folder)…',self.mass_import)
        self.mass_export_action = self.action(actions,'Mass Export (.mkchara)…',self.mass_export)
        self.export_action = self.action(actions,'Export Character (.mkchara)…',self.export_character)
        self.export_action.setToolTip('Export the selected character’s saved metadata and installed resources')
        self.action(actions,'Sync Menu / Race Names…',self.synchronize_character_names)
        self.rename_base_action=self.action(actions,'Rename Vanilla Character…',self.rename_vanilla_character)
        self.move_action = self.action(actions,'Move Character to Slot…',self.move_character)
        about=bar.addMenu('&Help')
        self.action(about,'About / Supported Formats',self.about)
        self.action(about,'Check for Updates…',lambda:self.check_updates(True))
        self.action(about,'Deployment Profile…',self.configure_deployment)
        self.action(about,'Export Compatibility Report…',self.export_compatibility_report)

    def export_compatibility_report(self):
        path,_=QFileDialog.getSaveFileName(self,'Export compatibility report','CharacterCompatibility.json','JSON (*.json)')
        if not path:return
        try:
            output=Path(path).resolve()
            if any(output.is_relative_to(root) for root in (self.pack.character,self.pack.patches_path,self.pack.archive_path.parent)):
                raise ValueError('Choose a report folder outside the game assets, Character and Patches folders.')
            output.write_text(json.dumps(self.pack.compatibility_report(),ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception as error:QMessageBox.warning(self,'Cannot export report',str(error))

    def configure_deployment(self):
        choices={'Retro Rewind (existing behavior)':'rr','WiiLoaded (stage UI/Race name patches)':'wiiloaded','Direct archives (Patches disabled)':'direct'}
        value,ok=QInputDialog.getItem(self,'Deployment profile','Character text deployment:',list(choices),list(choices.values()).index(self.pack.deployment_profile),False)
        if ok:
            self.pack.deployment_profile=choices[value]
            QSettings('Retro Rewind','Character Manager').setValue('deployment/profile',choices[value])

    def check_updates(self,manual=False):
        from .updates import DEFAULT_REPOSITORY
        if self._update_worker is not None and self._update_worker.isRunning():return
        worker=UpdateWorker(DEFAULT_REPOSITORY,self);self._update_worker=worker
        worker.result.connect(lambda release,error:self.update_result(release,error,manual))
        worker.start()

    def update_result(self,release,error,manual):
        if error:
            if manual:QMessageBox.information(self,'Update check unavailable',error)
            return
        if not release:
            if manual:QMessageBox.information(self,'Updates','You are using the latest published stable version.')
            return
        box=QMessageBox(self);box.setWindowTitle('Character Manager update');box.setText('Version '+release['version']+' is available.')
        download=box.addButton('Download…',QMessageBox.ButtonRole.AcceptRole)
        box.addButton('Later',QMessageBox.ButtonRole.RejectRole);box.exec()
        if box.clickedButton() is download:QDesktopServices.openUrl(QUrl(release['download']))

    def setup_content(self):
        central=QWidget();self.setCentralWidget(central)
        page=QVBoxLayout(central);page.setContentsMargins(0,0,0,0);page.setSpacing(0)
        header=QFrame();header.setObjectName('Header')
        head=QHBoxLayout(header);head.setContentsMargins(26,18,26,18)
        branding=QVBoxLayout();branding.setSpacing(1)
        title=QLabel('Retro Rewind  /  Character Manager');title.setObjectName('AppTitle')
        branding.addWidget(title)
        subline=QHBoxLayout();subline.setContentsMargins(0,0,0,0);subline.setSpacing(7)
        self.mode_label=QLabel();self.mode_label.setObjectName('AppSubtitle')
        subline.addWidget(self.mode_label)
        divider=QLabel('·');divider.setObjectName('AppSubtitle')
        subline.addWidget(divider)
        self.subtitle=ClickToCopyPath()
        subline.addWidget(self.subtitle,1)
        branding.addLayout(subline)
        head.addLayout(branding,1)
        head.addWidget(button('+ Import Character',self.import_character,True))
        head.addWidget(button('Refresh',self.refresh))
        page.addWidget(header)
        workspace=QSplitter(Qt.Orientation.Horizontal)
        workspace.setChildrenCollapsible(False)
        page.addWidget(workspace,1)
        left=QWidget();left_layout=QVBoxLayout(left);left_layout.setContentsMargins(13,17,10,13)
        left_layout.setSpacing(8)
        left_layout.addWidget(self.section('CHARACTER SELECT'))
        left_layout.addWidget(note('Select a base character to manage its custom skins.'))
        scroll=QScrollArea();scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        grid_container=QWidget();tiles_layout=QVBoxLayout(grid_container)
        tiles_layout.setContentsMargins(0,3,6,3);tiles_layout.setSpacing(10)
        self.character_tiles={}
        resource_root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent)) / 'assets' / 'base_icons'
        # Screen order stays independent of native CharacterId/BMG IDs.
        grid=QGridLayout();grid.setSpacing(8)
        for index,code in enumerate(DISPLAY_CODES):
            tile=QToolButton()
            tile.setObjectName('CharacterTile');tile.setCheckable(True)
            tile.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            tile.setText(CHARACTER_NAMES[CODE_IDS[code]])
            tile.setMinimumSize(144,111)
            tile.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
            icon_path=resource_root / (code+'.png')
            if icon_path.exists():
                tile.setIcon(QIcon(str(icon_path)))
                tile.setIconSize(QSize(132,70))
            tile.setToolTip(CHARACTER_NAMES[CODE_IDS[code]])
            tile.clicked.connect(lambda checked=False,c=code:self.change_base(c))
            grid.addWidget(tile,index//2,index%2)
            self.character_tiles[code]=tile
        grid.setColumnStretch(0,1);grid.setColumnStretch(1,1)
        tiles_layout.addLayout(grid)
        tiles_layout.addStretch()
        scroll.setWidget(grid_container)
        left_layout.addWidget(scroll,1)
        self.total=note('')
        left_layout.addWidget(self.total)
        workspace.addWidget(left)
        center=QWidget();center_layout=QVBoxLayout(center);center_layout.setContentsMargins(15,20,12,18);center_layout.setSpacing(12)
        top=QHBoxLayout()
        self.heading=QLabel('Character skins');self.heading.setStyleSheet('font-size: 14pt; font-weight: 700;')
        top.addWidget(self.heading,1)
        self.search=QLineEdit();self.search.setPlaceholderText('Search skins…')
        self.search.setMaximumWidth(230);self.search.textChanged.connect(self.refresh_table)
        top.addWidget(self.search)
        center_layout.addLayout(top)
        self.table=PatchSlotTable(0,8)
        self.table.setToolTip('Select a character to inspect or edit its resources.')
        self.table.setHorizontalHeaderLabels(['Slot','CSS','Character','Driver','Vehicles','Map','CSS file','Sounds'])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        for c in (0,3,4,5,6,7):self.table.horizontalHeader().setSectionResizeMode(c,QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1,82)
        self.table.setItemDelegate(PatchRowDelegate(self.table))
        self.table.setItemDelegateForColumn(1,CenteredCSSDelegate(self.table))
        self.table.verticalHeader().setDefaultSectionSize(76)
        self.table.itemSelectionChanged.connect(self.on_selected)
        self.table.cellClicked.connect(self.on_table_cell_clicked)
        self.table.slotDropped.connect(self.stage_patch_drop)
        self.table.rowPressed.connect(self.prepare_selection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.character_context_menu)
        center_layout.addWidget(self.table,1)
        center_buttons=QHBoxLayout();center_buttons.addWidget(button('Import…',self.import_character,True))
        self.move_button = button('Move to Slot…',self.move_character)
        center_buttons.addWidget(self.move_button)
        self.patch_move_button = button('Move Patch to Slot…', self.move_patch_to_slot)
        center_buttons.addWidget(self.patch_move_button)
        center_buttons.addStretch()
        center_layout.addLayout(center_buttons)
        self.patch_controls = QWidget()
        patch_controls = QHBoxLayout(self.patch_controls)
        patch_controls.setContentsMargins(0, 2, 0, 0)
        patch_controls.setSpacing(7)
        self.slot_save_button = button('Save Slot Changes', self.save_patch_slot_changes, True)
        self.slot_revert_button = button('Revert', self.revert_patch_slot_changes)
        patch_controls.addWidget(self.slot_save_button)
        patch_controls.addWidget(self.slot_revert_button)
        patch_controls.addStretch()
        patch_controls.addWidget(QLabel('Bump by X:'))
        self.bump_amount = QLineEdit('1')
        self.bump_amount.setValidator(QIntValidator(1, 100, self.bump_amount))
        self.bump_amount.setMaximumWidth(62)
        self.bump_amount.setToolTip('Shift editable skins in the selected base character only')
        patch_controls.addWidget(self.bump_amount)
        self.bump_button = button('Bump Slots', self.bump_patch_slots)
        self.bump_button.setToolTip('Stage a slot shift in the currently selected character section')
        patch_controls.addWidget(self.bump_button)
        self.organize_button = button('Organize Characters', self.organize_characters)
        patch_controls.addWidget(self.organize_button)
        center_layout.addWidget(self.patch_controls)
        self.slot_save_button.setEnabled(False)
        self.slot_revert_button.setEnabled(False)
        workspace.addWidget(center)
        right=QWidget();right_layout=QVBoxLayout(right);right_layout.setContentsMargins(12,20,18,18)
        right_layout.addWidget(self.section('SELECTED SKIN'))
        preview_row=QHBoxLayout();preview_row.setSpacing(12)
        preview_row.addStretch()
        css_col=QVBoxLayout();css_col.setSpacing(5)
        css_label=note('CSS PORTRAIT');css_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        css_col.addWidget(css_label)
        self.portrait=EditableImagePreview('Click to add CSS')
        self.portrait.setFixedSize(132,132)
        self.portrait.clicked.connect(self.replace_css_portrait)
        self.portrait.setToolTip('Click anywhere to add or replace the CSS portrait (PNG or TPL)')
        self.portrait.setEditable(False)
        css_col.addWidget(self.portrait)
        preview_row.addLayout(css_col)
        map_col=QVBoxLayout();map_col.setSpacing(5)
        map_label=note('MINIMAP');map_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        map_col.addWidget(map_label)
        # The label stays level with CSS PORTRAIT; position the actual icon inside a 132px canvas.
        map_canvas=QWidget()
        map_canvas.setFixedSize(78,132)
        self.map_preview=EditableImagePreview('Add map',map_canvas)
        self.map_preview.setFixedSize(78,78)
        self.map_preview.move(0, (132 - 78) // 2 + MAP_ICON_VERTICAL_OFFSET)
        self.map_preview.clicked.connect(self.replace_map_icon)
        self.map_preview.setToolTip('Click anywhere to add or replace the minimap icon (PNG or TPL)')
        self.map_preview.setEditable(False)
        map_col.addWidget(map_canvas)
        preview_row.addLayout(map_col)
        preview_row.addStretch()
        right_layout.addLayout(preview_row)
        self.selected_label=QLabel('Choose a skin')
        self.selected_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selected_label.setStyleSheet('font-size: 13pt; font-weight: 700;')
        right_layout.addWidget(self.selected_label)
        model_tools = QHBoxLayout()
        model_tools.addStretch()
        self.view_model_button = button('View Model…', self.view_installed_model)
        self.view_model_button.setToolTip('Browse installed standalone and embedded BRRES files in BrawlCrate')
        self.view_model_button.setEnabled(False)
        model_tools.addWidget(self.view_model_button)
        self.edit_sounds_button = button('Edit Sounds…', self.edit_sounds)
        self.edit_sounds_button.setEnabled(False)
        model_tools.addWidget(self.edit_sounds_button)
        model_tools.addStretch()
        right_layout.addLayout(model_tools)
        metadata=QGroupBox('Character metadata')
        form=QFormLayout(metadata)
        self.name_field=QLineEdit();self.author_field=QLineEdit()
        form.addRow('Name:',self.name_field)
        form.addRow('Creator:',self.author_field)
        self.save_button=button('Save Name and Author',self.save_metadata,True)
        self.save_button.setShortcut(QKeySequence('Ctrl+S'))
        form.addRow(self.save_button)
        right_layout.addWidget(metadata)
        resource_group=QGroupBox('Installed resources')
        resource_layout=QVBoxLayout(resource_group)
        resource_header = QHBoxLayout()
        self.resource_info=QLabel('Select a skin to inspect its resources.')
        self.resource_info.setWordWrap(True)
        self.resource_info.setStyleSheet('color: #b5c8dd;')
        resource_header.addWidget(self.resource_info,1)
        self.expand_resources_button = button('⛶ Full screen', self.open_resource_editor)
        self.expand_resources_button.setToolTip('View every installed resource and rename files')
        self.expand_resources_button.setEnabled(False)
        resource_header.addWidget(self.expand_resources_button)
        resource_layout.addLayout(resource_header)
        self.resource_list=QListWidget()
        self.resource_list.setToolTip('Installed character resources; open the editor for permitted filename changes.')
        self.resource_list.setMinimumHeight(180)
        self.resource_list.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        self.resource_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.resource_list.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.resource_list.viewport().setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        resource_layout.addWidget(self.resource_list,1)
        right_layout.addWidget(resource_group,1)
        self.warning=note('Optional icons and sounds may use native fallback. Moving a skin changes its numbered identity in saved ghosts.')
        right_layout.addWidget(self.warning)
        right_scroll=QScrollArea();right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setMinimumWidth(300);right_scroll.setWidget(right)
        workspace.addWidget(right_scroll)
        workspace.setHandleWidth(5)
        workspace.setSizes([455,715,340])
        self.selection_summary = note('')
        self.statusBar().addPermanentWidget(self.selection_summary)
        self.statusBar().showMessage('Ready')

    def closeEvent(self, event):
        worker=getattr(self,"_update_worker",None)
        if worker is not None and worker.isRunning():
            worker.blockSignals(True)
            if not worker.wait(10000):
                event.ignore();worker.finished.connect(self.close);return
        self._thumbnail_timer.stop()
        self._thumbnail_queue.clear()
        self._icon_cache.clear()
        self._icon_cache_bytes = 0
        super().closeEvent(event)

    def section(self,txt):
        label=QLabel(txt);label.setObjectName('SectionTitle')
        return label

    def reload_view(self,initial=False):
        self.selected_characters.intersection_update(self.pack.inventory.skins)
        for code,tile in self.character_tiles.items():
            tile.setChecked(code==self.current_code)
            tile.setToolTip(f'{CHARACTER_NAMES[CODE_IDS[code]]} · {len(self.pack.inventory.by_character(code))} custom skins')
        self.total.setText(f'{len(self.pack.inventory.skins)} skins · {self.pack.inventory.scanned_file_count} files')
        mode_name = 'Developer Mode' if self.pack.developer_mode else 'Standard Mode · Patches only'
        self.mode_label.setText(mode_name)
        self.subtitle.setPath(str(self.pack.character))
        self.move_action.setVisible(self.pack.developer_mode)
        self.rename_base_action.setVisible(self.pack.developer_mode)
        self.move_button.setVisible(self.pack.developer_mode)
        self.patch_move_button.setVisible(not self.pack.developer_mode)
        self.patch_controls.setVisible(True)
        self.table.setProperty('developerMode', self.pack.developer_mode)
        self.warning.setText('Drag rows to swap, bump or Organize Characters; Save applies changes, Revert discards them. '
                             'Slot changes affect saved ghost and leaderboard identities.'
                             if self.pack.developer_mode else
                             'Pink = Patches characters. Red = overlaps an official RR slot. '
                             'Drag pink rows to swap, or bump Patches in the selected character; save to apply changes.')
        self.refresh_table()
        self.statusBar().showMessage(f'Loaded {len(self.pack.inventory.skins)} skins · {len(self.pack.inventory.orphans)} orphan assets · {len(self.pack.inventory.unknown)} non-skin resources')
        if initial and self.pack.inventory.orphans:
            QMessageBox.information(self,'Unmatched assets',f'{len(self.pack.inventory.orphans)} files have slot IDs without a matching Driver model. They will not be automatically moved with unrelated skins.')

    def change_base(self,code):
        if code not in CODE_IDS or code==self.current_code:return
        self.current_code=code
        self.current_slot=None
        for other,tile in self.character_tiles.items():tile.setChecked(other==code)
        self.refresh_table()

    @property
    def display_inventory(self):
        # Show the Character owners being normalized, rather than their patch shadows.
        return (self.pack.distribution_inventory if self.current_code in self.independent_normalize_codes
                else self.pack.inventory)

    def display_asset_path(self, relative):
        if self.current_code in self.independent_normalize_codes:
            return self.pack.distribution_assets.get(relative.casefold(), self.pack.character / relative)
        return self.pack.asset_path(relative)

    def staged_slot(self, code, original):
        return self.pending_patch_slots.get((code, original), original)

    def editing_patch_slots(self):
        return not self.pack.developer_mode or self.staging_patches

    def editable_slot_set(self, code):
        if code in self.independent_normalize_codes:
            return self.pack.distribution_slots(code)
        return self.pack.patch_slots(code) if self.editing_patch_slots() else self.pack.movable_slots(code)

    def slot_destination_reservations(self, code):
        if code in self.independent_normalize_codes:
            return self.pack.distribution_reserved_slots(code) - self.pack.distribution_slots(code)
        return self.pack.slot_destinations_reserved(code, patches=self.editing_patch_slots())

    def staged_conflicts(self):
        conflicts = {}
        if not self.editing_patch_slots():
            for (code, original), target in self.pending_patch_slots.items():
                reserved = self.slot_destination_reservations(code)
                if target in reserved:
                    conflicts[(code, original)] = target
            return conflicts
        for code in CODE_IDS:
            reserved = self.pack.slot_destinations_reserved(code, patches=True)
            for original in self.pack.patch_slots(code):
                planned = self.staged_slot(code, original)
                if planned in reserved:
                    conflicts[(code, original)] = planned
        return conflicts

    def pending_slot_map(self):
        result = {}
        for (code, original), target in self.pending_patch_slots.items():
            if original != target:
                result.setdefault(code, {})[original] = target
        return result

    def has_staged_changes(self):
        return bool(self.pending_slot_map() or self.pending_organization)

    def organize_characters(self):
        # One action stages the entire active library; files remain untouched.
        if self.pack.developer_mode and self.staging_patches:
            QMessageBox.information(self,'Unsaved Patches slots','Save or Revert Patches changes before organizing the Developer library.');return
        updates={};independent=set()
        try:
            for code in CODE_IDS:
                current=self.pack.patch_slots(code) if self.editing_patch_slots() else self.pack.distribution_slots(code)
                ordered=sorted(current,key=lambda old:(self.staged_slot(code,old),old))
                if self.editing_patch_slots():
                    reserved=self.pack.slot_destinations_reserved(code,patches=True);previous=0
                    for old in ordered:
                        target=max(self.staged_slot(code,old),previous+1)
                        while target in reserved:target+=1
                        if target>100:raise ValueError(f'{code.upper()} has no safe destination below slot 101')
                        updates[code,old]=target;previous=target
                else:
                    reserved=self.pack.distribution_reserved_slots(code)-current
                    for target,old in enumerate(ordered,1):
                        if target in reserved:raise ValueError(f'{code.upper()} slot {target} has orphan resources; relocate those resources before organizing')
                        updates[code,old]=target
                    if ordered:independent.add(code)
            self.pending_patch_slots=updates;self.independent_normalize_codes=independent
            self.pending_organization=True;self.refresh_table()
            self.statusBar().showMessage('Organization staged across all character sections. Save reviews files and text; Revert discards it.')
        except Exception as exc:QMessageBox.warning(self,'Cannot organize characters',str(exc))

    def update_patch_actions(self):
        dirty = self.has_staged_changes()
        conflicts = self.staged_conflicts()
        self.slot_save_button.setEnabled(dirty)
        self.slot_save_button.setToolTip("Resolve the listed conflicts before saving" if conflicts else "Apply staged slot changes")
        self.slot_revert_button.setEnabled(dirty)
        self.patch_move_button.setEnabled(self.editing_patch_slots() and self.current_slot is not None
                                          and self.pack.is_patch_skin(self.current_code, self.current_slot))
        self.bump_button.setEnabled(bool(self.editable_slot_set(self.current_code)))
        self.organize_button.setEnabled(True)
        if conflicts:
            label = ', '.join(f'{code.upper()} #{slot}' for (code, _), slot in sorted(conflicts.items())[:5])
            self.statusBar().showMessage(f'⚠ Reserved slot conflicts: {label}. Choose free slots before saving.'
                                        if self.pack.developer_mode else
                                        f'⚠ Patches overlap official RR slots: {label}. Click a red slot to bump all patches.')
        elif dirty:
            self.statusBar().showMessage('Unsaved slot changes — Save to rename files and update character names, or Revert.')

    def refresh_table(self):
        code = self.current_code
        self.heading.setText(f'{CHARACTER_NAMES[CODE_IDS[code]]} · {code.upper()}')
        skins = self.display_inventory.by_character(code)
        search = self.search.text().lower().strip()
        if search:
            skins = [skin for skin in skins if search in skin.name.lower() or
                     search in skin.author.lower() or search in str(skin.slot) or
                     search in str(self.staged_slot(code, skin.slot))]
        skins.sort(key=lambda skin: (self.staged_slot(code, skin.slot), skin.slot))
        conflicts = self.staged_conflicts()
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(skins))
        self._thumbnail_queue = []
        for row, skin in enumerate(skins):
            counts = skin.counts
            patched = code not in self.independent_normalize_codes and self.pack.is_patch_skin(code, skin.slot)
            proposed_slot = self.staged_slot(code, skin.slot)
            colliding = patched and ((code, skin.slot) in conflicts or
                         proposed_slot in self.pack.distribution_slots(code))
            entries = [('⚠ ' if colliding else '') + str(proposed_slot), '', skin.name or '(unnamed)',
                       str(counts['Driver']), str(counts['RaceKart']),
                       'Yes' if counts['Map'] else '—',
                       'Yes' if counts['Portrait'] else '—', str(counts['Sound'])]
            bg = (QColor('#a33347') if colliding else
                  QColor('#683c57') if row % 2 == 0 else QColor('#563249')) if patched else None
            for col, value in enumerate(entries):
                item = self.table.item(row,col)
                if item is None:
                    item = QTableWidgetItem()
                item.setText(value)
                item.setToolTip('')
                item.setIcon(QIcon())
                item.setData(Qt.ItemDataRole.BackgroundRole, None)
                item.setData(Qt.ItemDataRole.ForegroundRole, None)
                item.setData(Qt.ItemDataRole.UserRole, skin.slot)
                item.setData(Qt.ItemDataRole.UserRole + 1, 'patch' if patched else 'distribution')
                if bg is not None:
                    item.setBackground(bg)
                    item.setForeground(QColor('#fff0f5'))
                if col in (0, 1, 3, 4, 5, 6, 7):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 2:
                    item.setToolTip(skin.author)
                if col == 1:
                    css_pix = self.skin_thumbnail(skin,cached_only=True)
                    if css_pix is not None:
                        item.setIcon(QIcon(css_pix.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation)))
                    else:
                        has_icon = any(a.category in ('Portrait','Map') for a in skin.files)
                        item.setText('…' if has_icon else '+ Add')
                        if has_icon:self._thumbnail_queue.append((row,skin))
                    item.setToolTip('CSS portrait, or minimap fallback. Click to replace CSS portrait (PNG or TPL)')
                if colliding:
                    item.setToolTip('This Patches slot overlaps an official RR slot. Click the red warning to bump patches for this character only.')
                if skin.slot in self.editable_slot_set(code):
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
                self.table.setItem(row, col, item)
            if colliding:
                warning = QPushButton('⚠ ' + str(proposed_slot))
                warning.setObjectName('CollisionWarning')
                warning.setStyleSheet('QPushButton#CollisionWarning { background: #b52e49; border: 1px solid #ff8290; color: white; font-weight: bold; } '
                                      'QPushButton#CollisionWarning:hover { background: #da4058; }')
                warning.setToolTip('Overlapping RR slot — click for recommended fix')
                warning.clicked.connect(lambda checked=False, c=code, s=skin.slot: self.show_patch_collision(c, s))
                self.table.setCellWidget(row, 0, warning)
            else:
                self.table.removeCellWidget(row, 0)
        nextrow = next((r for r, skin in enumerate(skins) if skin.slot == self.current_slot),
                       0 if skins else -1)
        self.table.clearSelection()
        for row,skin in enumerate(skins):
            if (code,skin.slot) in self.selected_characters:
                self.table.selectionModel().select(self.table.model().index(row,0),
                    QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        if not self.selected_characters and not self._selection_started and nextrow>=0:
            self.table.selectRow(nextrow)
        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        if self._thumbnail_queue:self._thumbnail_timer.start()
        else:self._thumbnail_timer.stop()
        self._restoring_selection = True
        try:
            if self.table.selectedItems():
                self.on_selected()
            else:
                self.clear_details()
        finally:
            self._restoring_selection = False
        self.update_selection_status()
        self.update_patch_actions()

    def _stage_patch_destination(self, code, original, target):
        if original not in self.editable_slot_set(code):
            QMessageBox.warning(self, 'Unavailable character',
                                'Relocate the Patches override before moving this Character slot.' if self.pack.developer_mode else
                                'Only Patches-installed skins can move in Standard Mode.')
            return
        if target < 1 or target > 100:
            QMessageBox.warning(self, 'Invalid slot', 'Choose a slot from 1 to 100.')
            return
        if target in self.slot_destination_reservations(code):
            QMessageBox.warning(self, 'Reserved slot',
                                f'{code.upper()} slot {target} contains protected resources or text. Choose a free slot.')
            return
        occupied = next((old for old in self.editable_slot_set(code)
                         if old != original and self.staged_slot(code, old) == target), None)
        old_target = self.staged_slot(code, original)
        if occupied is not None:
            self.pending_patch_slots[(code, occupied)] = old_target
        self.pending_patch_slots[(code, original)] = target
        self.current_slot = original
        self.refresh_table()

    def stage_patch_drop(self, original, target_original):
        code = self.current_code
        if original not in self.editable_slot_set(code):
            return
        if target_original < 0:
            self.current_slot = original
            self.move_patch_to_slot()
            return
        if original == target_original:
            return
        if target_original not in self.editable_slot_set(code):
            QMessageBox.information(self, 'Unavailable character',
                                    'Drop onto another editable Character row to swap. Relocate Patches overrides first.'
                                    if self.pack.developer_mode else
                                    'Original RR slots cannot move. Drop onto another pink row to swap, '
                                    'or use “Move Patch to Slot…” for an empty number.')
            return
        self._stage_patch_destination(code, original, self.staged_slot(code, target_original))

    def move_patch_to_slot(self):
        code, original = self.current_code, self.current_slot
        if original is None or original not in self.editable_slot_set(code):
            return
        target, ok = QInputDialog.getInt(self, 'Move character slot', 'New slot (1–100):',
                                         self.staged_slot(code, original), 1, 100)
        if ok:
            self._stage_patch_destination(code, original, target)

    def bump_patch_slots(self, amount=None):
        # QPushButton.clicked passes checked=False, even to callables that
        # accept an optional argument. False is not a requested bump amount.
        if isinstance(amount, bool):
            amount = None
        if amount is None:
            try:
                amount = int(self.bump_amount.text())
            except (ValueError, TypeError):
                QMessageBox.warning(self, 'Invalid bump', 'Enter a whole number of slots to bump by.')
                return
        if not 1 <= amount <= 100:
            QMessageBox.warning(self, 'Invalid bump', 'Use a positive number between 1 and 100.')
            return
        code = self.current_code
        updates = {}
        for old in self.editable_slot_set(code):
            dest = self.staged_slot(code, old) + amount
            if dest > 100:
                QMessageBox.warning(self, 'Cannot bump',
                                    f'{code.upper()} slot {self.staged_slot(code, old)} would exceed slot 100.')
                return
            updates[(code, old)] = dest
        if not updates:
            return
        self.pending_patch_slots.update(updates)
        self.refresh_table()

    def normalize_slots(self):
        if self.editing_patch_slots():
            return
        code = self.current_code
        ordered = sorted(self.pack.distribution_slots(code), key=lambda old: (self.staged_slot(code, old), old))
        updates = {(code, old): slot for slot, old in enumerate(ordered, 1)}
        if all(old == target for (_, old), target in updates.items()):
            self.pending_patch_slots = {key: value for key, value in self.pending_patch_slots.items() if key[0] != code}
            self.independent_normalize_codes.discard(code)
            self.refresh_table()
            self.statusBar().showMessage(f'{code.upper()} slots already start at 1 with no gaps.')
            return
        reserved = self.pack.distribution_reserved_slots(code) - set(ordered)
        if reserved & set(updates.values()):
            QMessageBox.warning(self, 'Cannot normalize', 'A destination contains Character files without a Driver model. Move or remove those orphan files before normalizing; text-only entries are preserved automatically.')
            return
        self.independent_normalize_codes.add(code)
        self.pending_patch_slots.update(updates)
        self.refresh_table()

    def show_patch_collision(self, code, original):
        actual = self.staged_slot(code, original)
        result = QMessageBox.question(self, 'Overlapping character slot',
            f'{code.upper()} slot {actual} is used by both an official RR character and a Patches character.\n\n'
            'This can happen after a Retro Rewind update. You can bump Patches slots for this base character only.\n\n'
            f'Stage a +1 bump for {code.upper()} Patches skins only? (Changes are not saved yet.)',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes)
        if result == QMessageBox.StandardButton.Yes:
            if self.current_code != code:
                self.change_base(code)
            previous_scope = self.staging_patches
            if self.pack.developer_mode:
                if (self.has_staged_changes() or self.independent_normalize_codes) and not self.staging_patches:
                    QMessageBox.warning(self, 'Unsaved Character slots',
                                        'Save or Revert Character slot changes before relocating Patches skins.')
                    return
                self.staging_patches = True
            self.bump_patch_slots(1)
            if not self.pending_slot_map():
                self.staging_patches = previous_scope
                self.refresh_table()

    def save_patch_slot_changes(self):
        mapping = self.pending_slot_map()
        if not mapping and not self.pending_organization:
            return
        conflicts = self.staged_conflicts()
        if conflicts:
            details = ', '.join(f'{code.upper()} #{slot}' for (code, _), slot in sorted(conflicts.items()))
            QMessageBox.warning(self, 'Overlapping slots',
                                f'Reserved resources or custom text occupy: {details}. Choose free slots or bump again before saving.')
            return
        try:
            plan = read_library_background(lambda: (
                self.pack.organize_characters(mapping, patches=self.editing_patch_slots(), independent_codes=self.independent_normalize_codes) if self.pending_organization else
                self.pack.reassign_developer_slots(mapping, independent_codes=self.independent_normalize_codes) if not self.editing_patch_slots()
                else self.pack.reassign_patch_slots(mapping)),self,title='Preparing Character Changes',message='Checking ownership and synchronizing character text…')
        except Exception as exc:
            QMessageBox.warning(self, 'Cannot save slots', str(exc));return
        if PreviewDialog(plan, self).exec() != QDialog.DialogCode.Accepted:return
        try:
            backup = read_library_background(lambda:self.pack.commit(plan),self,title='Saving Character Changes',message='Backing up and applying character resources and UI/Race text…')
        except Exception as exc:
            QMessageBox.critical(self, 'Slot update failed', str(exc));return
        self.pending_patch_slots.clear()
        self.staging_patches = False
        self.pending_organization = False
        self.independent_normalize_codes.clear()
        self.selected_characters = {(code,mapping.get(code,{}).get(slot,slot)) for code,slot in self.selected_characters}
        self.current_slot = mapping.get(self.current_code, {}).get(self.current_slot, self.current_slot)
        self.reload_view()
        QMessageBox.information(self, 'Slot changes saved', f'Slot changes applied and BMG updated.\n\nBackup: {backup}')

    def revert_patch_slot_changes(self):
        self.pending_patch_slots.clear()
        self.staging_patches = False
        self.pending_organization = False
        self.independent_normalize_codes.clear()
        self.refresh_table()

    def clear_details(self):
        self._detail_key = None
        self.current_slot=None
        self.selected_label.setText('Choose a skin')
        self.name_field.clear();self.author_field.clear()
        self.name_field.setReadOnly(True);self.author_field.setReadOnly(True)
        self.resource_info.setText('No character selected.')
        self.expand_resources_button.setEnabled(False)
        self.view_model_button.setEnabled(False)
        self.edit_sounds_button.setEnabled(False)
        self.resource_list.clear();self.portrait.setText('Click to add CSS');self.portrait.setIcon(QIcon())
        self.portrait.setEditable(False)
        self.map_preview.setText('Add map');self.map_preview.setIcon(QIcon())
        self.map_preview.setEditable(False)
        self.save_button.setEnabled(False)
        self.patch_move_button.setEnabled(False)
        self.export_action.setEnabled(False)

    def on_selected(self):
        if not self._restoring_selection:
            visible = {(self.current_code,self.table.item(row,0).data(Qt.ItemDataRole.UserRole))
                       for row in range(self.table.rowCount())}
            self.selected_characters.difference_update(visible)
            self.selected_characters.update((self.current_code,slot) for slot in self.selected_character_slots())
            self.update_selection_status()
        items=self.table.selectedItems()
        if not items:
            self.clear_details();return
        slot=items[0].data(Qt.ItemDataRole.UserRole)
        skin=self.display_inventory.skins.get((self.current_code,slot))
        if not skin:return
        self.current_slot=slot
        detail_key = (self.pack.revision,self.current_code,slot,self.current_code in self.independent_normalize_codes)
        if self._detail_key == detail_key:
            return
        self._detail_key = detail_key
        self.selected_label.setText(f'{skin.name or "Unnamed"}  ·  Slot {self.staged_slot(self.current_code,slot)}' + ('  ·  Patches' if self.current_code not in self.independent_normalize_codes and self.pack.is_patch_skin(self.current_code,slot) else ''))
        self.name_field.setText(skin.name)
        self.author_field.setText(skin.author)
        editable = self.pack.can_edit_skin(self.current_code, slot) and not self.independent_normalize_codes
        self.patch_move_button.setEnabled(not self.pack.developer_mode and self.pack.is_patch_skin(self.current_code, slot))
        self.save_button.setEnabled(editable)
        self.export_action.setEnabled(True)
        self.name_field.setReadOnly(not editable)
        self.author_field.setReadOnly(not editable)
        permission_tip = ('Edit this skin' if editable else 'Read-only distribution skin. '
                          'Enable Developer Mode to edit original assets.')
        self.name_field.setToolTip(permission_tip)
        self.author_field.setToolTip(permission_tip)
        cnt=skin.counts
        self.resource_info.setText(f"Driver: {cnt['Driver']}   ·   Vehicle archives: {cnt['RaceKart']}/12\nMenu: {cnt['AllKart']}   ·   Map: {cnt['Map']}   ·   CSS: {cnt['Portrait']}   ·   Sounds: {cnt['Sound']}")
        self.resource_list.clear()
        self.expand_resources_button.setEnabled(True)
        self.view_model_button.setEnabled(True)
        self.edit_sounds_button.setEnabled(True)
        for asset in skin.files:
            from PySide6.QtWidgets import QListWidgetItem
            item = QListWidgetItem(f'{asset.category}  ·  {self.display_asset_path(asset.relpath).name}')
            item.setData(Qt.ItemDataRole.UserRole, asset.relpath)
            self.resource_list.addItem(item)
        pix=self.skin_image(skin,'Portrait')
        self.portrait.setIcon(QIcon())
        self.portrait.setEditable(editable)
        if pix is None:
            self.portrait.setText('Click to add CSS' if editable else 'No CSS')
        else:
            self.portrait.setText('')
            self.portrait.setIcon(QIcon(pix))
            self.portrait.setIconSize(QSize(116,116))
        map_pix=self.skin_image(skin,'Map')
        self.map_preview.setIcon(QIcon())
        self.map_preview.setEditable(editable)
        if map_pix is None:
            self.map_preview.setText('Add map' if editable else 'No map')
        else:
            self.map_preview.setText('')
            self.map_preview.setIcon(QIcon(map_pix))
            self.map_preview.setIconSize(QSize(61,61))

    def show_character_table_context(self, point):
        """Right-click a skin row: show Rename / Export / Delete immediately.

        The main table summarizes many resources in one row. Each operation
        therefore contains file choices rather than showing a preliminary,
        potentially confusing resource-picker popup.
        """
        row = self.table.rowAt(point.y())
        if row < 0:
            return
        slot_item = self.table.item(row, 0)
        if slot_item is None:
            return
        slot = slot_item.data(Qt.ItemDataRole.UserRole)
        code = self.current_code
        skin = self.display_inventory.skins.get((code, slot))
        if skin is None:
            return
        global_pos = self.table.viewport().mapToGlobal(point)
        # Select the clicked row as well as opening the menu, so its details
        # match the resources the menu will operate on.
        if self.table.currentRow() != row:
            self.table.selectRow(row)

        assets = []
        for asset in skin.files:
            source = self.display_asset_path(asset.relpath)
            if (source.is_file() and not source.is_symlink() and
                    (self.pack.developer_mode or
                     source.resolve().is_relative_to(self.pack.patches_path))):
                assets.append(asset)

        menu = QMenu(self)
        if not assets:
            message = menu.addAction('Original RR resources are read-only in Patches Mode')
            message.setEnabled(False)
            menu.exec(global_pos)
            return

        column = self.table.columnAt(point.x())
        preferred = {1: ('Portrait',), 3: ('Driver',),
                     4: ('RaceKart', 'AllKart'), 5: ('Map',),
                     6: ('Portrait',), 7: ('Sound',)}.get(column, ())
        assets.sort(key=lambda asset: (asset.category not in preferred,
                                      asset.category, self.display_asset_path(asset.relpath).name.casefold()))
        # Show the actions first, even when the character has several files.
        # The clicked column's resource types appear first, but every file
        # remains accessible from any cell in that character's row.
        actions = {}
        for title, operation in (('Rename…', 'rename'),
                                 ('Export…', 'export'),
                                 ('Delete…', 'delete')):
            if len(assets) == 1:
                action = menu.addAction(title)
                actions[action] = (operation, assets[0])
            else:
                submenu = menu.addMenu(title)
                for asset in assets:
                    name = self.display_asset_path(asset.relpath).name
                    action = submenu.addAction(f'{asset.category}  ·  {name}')
                    actions[action] = (operation, asset)
        chosen = menu.exec(global_pos)
        if chosen in actions:
            operation, asset = actions[chosen]
            resource_context_menu(self, self.pack, code, slot, asset,
                                  global_pos, self.run_plan, operation=operation)

    def show_resource_list_context(self, point):
        item = self.resource_list.itemAt(point)
        if item is None or self.current_slot is None:
            return
        skin = self.display_inventory.skins.get((self.current_code, self.current_slot))
        if skin is None:
            return
        asset = next((asset for asset in skin.files
                      if asset.relpath == item.data(Qt.ItemDataRole.UserRole)), None)
        if asset is not None:
            resource_context_menu(self, self.pack, self.current_code, self.current_slot,
                                  asset, self.resource_list.viewport().mapToGlobal(point), self.run_plan)

    def load_thumbnail_chunk(self):
        # Decode at most two cold thumbnails per event-loop turn. Navigation
        # replaces this queue, so no obsolete section work accumulates.
        for _ in range(min(2,len(self._thumbnail_queue))):
            row,skin = self._thumbnail_queue.pop(0)
            item = self.table.item(row,1)
            if item is None or item.data(Qt.ItemDataRole.UserRole)!=skin.slot:
                continue
            pix = self.skin_thumbnail(skin)
            item.setText('' if pix is not None else '+ Add')
            if pix is not None:
                item.setIcon(QIcon(pix.scaled(64,64,Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)))
        if not self._thumbnail_queue:self._thumbnail_timer.stop()

    def skin_thumbnail(self, skin, cached_only=False):
        portrait = self.skin_portrait(skin,cached_only=cached_only)
        return portrait if portrait is not None else self.skin_image(skin,'Map',crop_transparent=True,cached_only=cached_only)

    def skin_portrait(self,skin,cached_only=False):
        return self.skin_image(skin,'Portrait',crop_transparent=True,cached_only=cached_only)

    def skin_image(self,skin,category,crop_transparent=False,*,cached_only=False):
        asset=next((a for a in skin.files if a.category==category),None)
        if not asset:return None
        try:
            path = self.display_asset_path(asset.relpath)
            stat = path.stat()
            key = (str(path),stat.st_mtime_ns,stat.st_ctime_ns,stat.st_size,crop_transparent)
            if key in self._icon_cache:
                self._icon_cache.move_to_end(key)
                return self._icon_cache[key]
            if cached_only:return None
            for old in list(self._icon_cache):
                if old[0]==key[0] and old[1:4]!=key[1:4]:
                    removed = self._icon_cache.pop(old)
                    self._icon_cache_bytes -= removed.width()*removed.height()*4
            image=read_tpl(path.read_bytes())
            # Crop transparent padding for table thumbnails only; never modify the TPL itself.
            if crop_transparent:
                bounds=image.convert('RGBA').getchannel('A').getbbox()
                if bounds:
                    image=image.crop(bounds)
            raw=image.tobytes('raw','RGBA')
            qimage=QImage(raw,image.width,image.height,image.width*4,QImage.Format.Format_RGBA8888).copy()
            pixmap = QPixmap.fromImage(qimage)
            if pixmap.width()>256 or pixmap.height()>256:
                pixmap = pixmap.scaled(256,256,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
            self._icon_cache[key] = pixmap
            self._icon_cache_bytes += pixmap.width()*pixmap.height()*4
            while len(self._icon_cache)>512 or self._icon_cache_bytes>8*1024*1024:
                _,removed = self._icon_cache.popitem(last=False)
                self._icon_cache_bytes -= removed.width()*removed.height()*4
            return pixmap
        except (OSError,ValueError):
            return None

    def on_table_cell_clicked(self,row,col):
        if col!=1 or len(self.selected_character_slots()) != 1 or QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:return
        item=self.table.item(row,0)
        if item is None:return
        self.current_slot=item.data(Qt.ItemDataRole.UserRole)
        if not self.pack.can_edit_skin(self.current_code, self.current_slot):
            return
        self.replace_css_portrait()

    def replace_css_portrait(self):
        if self.current_slot is not None and not self.pack.can_edit_skin(self.current_code, self.current_slot):
            return
        if self.current_slot is None:
            QMessageBox.information(self,'Select a skin','Select an installed skin first.');return
        file_name,_=QFileDialog.getOpenFileName(self,'Choose CSS portrait PNG or TPL','',
            'CSS portrait images (*.png *.tpl);;PNG images (*.png);;TPL textures (*.tpl)')
        if not file_name:return
        try:
            plan=self.pack.replace_portrait(self.current_code,self.current_slot,Path(file_name))
        except Exception as e:
            QMessageBox.warning(self,'Cannot import portrait',str(e));return
        self.run_plan(plan)

    def replace_map_icon(self):
        if self.current_slot is not None and not self.pack.can_edit_skin(self.current_code, self.current_slot):
            return
        if self.current_slot is None:
            QMessageBox.information(self,'Select a skin','Select an installed skin first.');return
        file_name,_=QFileDialog.getOpenFileName(self,'Choose minimap icon PNG or TPL','',
            'Minimap images (*.png *.tpl);;PNG images (*.png);;TPL textures (*.tpl)')
        if not file_name:return
        try:
            plan=self.pack.replace_map(self.current_code,self.current_slot,Path(file_name))
        except Exception as e:
            QMessageBox.warning(self,'Cannot import minimap',str(e));return
        self.run_plan(plan)

    def set_voice_baseline(self):
        filename,_=QFileDialog.getOpenFileName(self,'Choose original Mario Kart Wii revo_kart.brsar','','BRSAR sound archive (*.brsar)')
        if not filename:return
        from .voices import VoiceArchive
        try:
            read_library_background(lambda:VoiceArchive(Path(filename),self.current_code or 'mr'),self,
                title='Checking Vanilla Voices',message='Validating original voice groups…')
            QSettings('Retro Rewind','Character Manager').setValue('voice/vanillaArchive',filename)
            QMessageBox.information(self,'Vanilla voices configured','The original archive will be used when opening Edit Sounds and importing WAV voice clips. It will remain read-only.')
        except Exception as exc:QMessageBox.warning(self,'Invalid voice baseline',str(exc))

    def edit_sounds(self):
        if self.current_slot is None:
            QMessageBox.information(self,'Select a character','Select an installed character first.');return
        if self.has_staged_changes():
            QMessageBox.information(self,'Unsaved slot changes','Save or revert slot changes before editing voices.');return
        from .voices import baseline_path, VoiceSession
        from .voice_editor import VoiceEditor
        baseline = baseline_path(self.pack)
        if baseline is None:
            filename,_=QFileDialog.getOpenFileName(self,'Choose original Mario Kart Wii revo_kart.brsar','','BRSAR sound archive (*.brsar)')
            if not filename:return
            baseline=Path(filename)
        try:
            session=read_library_background(lambda:VoiceSession(self.pack,self.current_code,self.current_slot,baseline),
                self,title='Loading Character Voices',message='Reading vanilla event tables and installed voice resources…')
            QSettings('Retro Rewind','Character Manager').setValue('voice/vanillaArchive',str(baseline))
            editor=VoiceEditor(session,self)
            try:
                editor.exec()
                if editor.changed:self.reload_view()
            finally:
                editor.deleteLater()
        except Exception as exc:
            QMessageBox.warning(self,'Cannot open Voice Editor',str(exc))

    def run_plan(self,plan:EditPlan):
        if self.has_staged_changes():
            QMessageBox.information(self, 'Unsaved character changes', 'Save or Revert staged character changes before editing other resources.')
            return
        try:self.pack.prepare_name_sync(plan)
        except Exception as e:QMessageBox.warning(self,'Cannot synchronize names',str(e));return
        if not plan.moves and not plan.writes and not plan.deletes:
            QMessageBox.information(self,'No changes','Everything is already up to date.');return
        if PreviewDialog(plan,self).exec()!=QDialog.DialogCode.Accepted:return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            backup=self.pack.commit(plan)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            box=QMessageBox(self);box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle('Update failed');box.setText(str(e));box.setDetailedText(traceback.format_exc());box.exec()
            return
        QApplication.restoreOverrideCursor()
        self.reload_view()
        QMessageBox.information(self,'Saved successfully',f'Changes applied.\n\nBackup location:\n{backup}')

    def import_character(self):
        if self.has_staged_changes():
            QMessageBox.information(self, 'Unsaved slot changes', 'Save or revert staged slot changes before importing or moving characters.')
            return
        dialog=ImportWizard(self.pack,self.current_code,self)
        if dialog.exec()==QDialog.DialogCode.Accepted and dialog.plan:
            self.current_code=dialog.base.currentData()
            self.current_slot=dialog.slot.value()
            self.run_plan(dialog.plan)

    def mass_import(self):
        """Install independent .mkchara packages into empty slots, one transaction each."""
        if self.has_staged_changes():
            QMessageBox.information(self, 'Unsaved slot changes', 'Save or revert staged slot changes before importing or moving characters.')
            return
        folder = QFileDialog.getExistingDirectory(self, 'Choose folder containing .mkchara files')
        if not folder:
            return
        packages = sorted((p for p in Path(folder).rglob('*')
                           if p.is_file() and p.suffix.lower() == '.mkchara'), key=lambda p: str(p).casefold())
        if not packages:
            QMessageBox.information(self, 'Mass Import', 'No .mkchara files found in this folder.')
            return
        destination = 'Character' if self.pack.developer_mode else 'Patches'
        choice = QMessageBox.question(self, 'Mass Import',
            f'Install {len(packages)} .mkchara packages into available {destination} slots?\n'
            'Each import has its own backup.')
        if choice != QMessageBox.StandardButton.Yes:
            return
        self._thumbnail_timer.stop();self._thumbnail_queue.clear()
        progress = MassImportProgress(self.pack, packages, self)
        progress.exec()
        progress.worker.wait()
        successes, failures = progress.worker.successes, progress.worker.failures
        progress.deleteLater()
        self.reload_view()
        summary = (f'Imported {len(successes)} of {len(packages)} packages.\n'
                   f'Failed: {len(failures)}\n\n' +
                   '\n'.join(successes + (['', 'Failures:'] + failures if failures else [])))
        result = QMessageBox(self)
        result.setWindowTitle('Mass Import Results')
        result.setIcon(QMessageBox.Icon.Warning if failures else QMessageBox.Icon.Information)
        result.setText(f'Mass Import finished: {len(successes)} succeeded · {len(failures)} failed')
        result.setDetailedText(summary)
        result.setInformativeText('Open Details to see installed slots and any failures.')
        result.exec()
        result.deleteLater()

    def save_metadata(self):
        if self.current_slot is None or not self.pack.can_edit_skin(self.current_code, self.current_slot):return
        try:
            plan=self.pack.edit_text(self.current_code,self.current_slot,self.name_field.text().strip(),self.author_field.text().strip())
        except Exception as e:
            QMessageBox.warning(self,'Cannot save',str(e));return
        self.run_plan(plan)

    def synchronize_character_names(self):
        try:self.run_plan(self.pack.synchronize_character_names())
        except Exception as e:QMessageBox.warning(self,'Cannot synchronize names',str(e))

    def rename_vanilla_character(self):
        if not self.pack.developer_mode:return
        from .bmg import name_id,author_id
        cid=CODE_IDS[self.current_code]
        current=self.pack.bmg.get_text(name_id(cid,0)) or CHARACTER_NAMES[cid]
        text,ok=QInputDialog.getText(self,'Rename Vanilla Character','Menu and in-race name:',text=current)
        if not ok:return
        try:self.run_plan(self.pack.edit_text(self.current_code,0,text.strip(),self.pack.bmg.get_text(author_id(cid,0))))
        except Exception as e:QMessageBox.warning(self,'Cannot rename',str(e))

    def move_character(self):
        if self.has_staged_changes():
            QMessageBox.information(self, 'Unsaved slot changes', 'Save or revert staged slot changes before importing or moving characters.')
            return
        if not self.pack.developer_mode:
            QMessageBox.information(self, 'Developer Mode required',
                'Moving slots modifies distributed skins. Reopen the pack with Developer Mode enabled.')
            return
        if self.current_slot is None:
            QMessageBox.information(self,'Select a skin','Choose a skin to move first.');return
        slot,ok=QInputDialog.getInt(self,'Move Character','New slot (1–100):',self.current_slot,1,100)
        if not ok:return
        try:plan=self.pack.move_slot(self.current_code,self.current_slot,slot)
        except Exception as e:QMessageBox.warning(self,'Cannot move skin',str(e));return
        self.current_slot=slot
        self.run_plan(plan)

    def view_installed_model(self):
        if self.current_slot is None:
            return
        skin = self.display_inventory.skins.get((self.current_code, self.current_slot))
        if skin is None:
            return
        physical = []
        seen = set()
        for asset in skin.files:
            path = self.display_asset_path(asset.relpath)
            if path.suffix.lower() in ('.szs', '.brres') and path not in seen:
                physical.append(path)
                seen.add(path)
        try:
            candidates, entries = read_library_background(lambda: find_installed_models(physical,
                patches=self.pack.patches_path,character=self.pack.character),self,
                title='Loading Character Models',message='Reading standalone and embedded models…')
            if not candidates:
                QMessageBox.information(self, 'No models', 'No BRRES models found for this skin.')
                return
            dialog = ModelExplorerDialog(entries, allow_driver=False, parent=self,candidates=candidates)
            try:
                dialog.exec()
            finally:
                dialog.deleteLater()
        except Exception as exc:
            QMessageBox.warning(self, 'Cannot inspect character models', str(exc))

    def open_resource_editor(self):
        if self.current_slot is None:
            QMessageBox.information(self, 'Select a skin', 'Choose a character first.')
            return
        dialog = ResourceEditorDialog(self.pack, self.current_code, self.current_slot, self)
        # Maximize to usable screen area; normal system close/minimize remains available.
        dialog.setWindowState(dialog.windowState() | Qt.WindowState.WindowMaximized)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.plan is not None:
            self.run_plan(dialog.plan)
        dialog.deleteLater()

    def prepare_selection(self, control):
        if control and not self._selection_started and not self.selected_characters:
            self.table.blockSignals(True);self.table.clearSelection();self.table.blockSignals(False)
        self._selection_started = True
        if not control:
            self.selected_characters.clear()

    def selected_character_keys(self):
        return sorted(self.selected_characters)

    def update_selection_status(self):
        count = len(self.selected_characters)
        self.selection_summary.setText(f'{count} selected across sections' if count else '')
        self.mass_export_action.setEnabled(bool(count))
        self.mass_export_action.setText(f'Mass Export (.mkchara)… ({count} selected)' if count else 'Mass Export (.mkchara)…')

    def mass_export(self):
        self.export_selected(grouped=True)

    def export_selected(self, *, grouped=True):
        if self.independent_normalize_codes:
            QMessageBox.information(self, 'Unsaved normalization', 'Save or revert Character slot normalization before editing or exporting characters.')
            return
        keys = self.selected_character_keys()
        if not keys:
            QMessageBox.information(self,'Mass Export','Select characters with Ctrl+Click first.')
            return
        folder = QFileDialog.getExistingDirectory(self,'Choose Mass Export destination')
        if not folder:
            return
        worker = MassExportWorker(self.pack,keys,folder,grouped=grouped)
        progress = MassImportProgress(self.pack,keys,self,worker=worker)
        self._thumbnail_timer.stop()
        progress.exec();worker.wait()
        if self._thumbnail_queue:self._thumbnail_timer.start()
        result = QMessageBox(self)
        result.setWindowTitle('Mass Export Results')
        result.setIcon(QMessageBox.Icon.Warning if worker.failures else QMessageBox.Icon.Information)
        result.setText(f'Mass Export finished: {len(worker.successes)} succeeded · {len(worker.failures)} failed')
        result.setInformativeText(f'Files are grouped by base character under {Path(folder)/"CharacterExport"}.' if grouped else f'Files were exported to {folder}.')
        result.setDetailedText('\n'.join(worker.successes + (['','Failures:',*worker.failures] if worker.failures else [])))
        result.exec()
        result.deleteLater();progress.deleteLater()

    def selected_character_slots(self):
        return [
            self.table.item(index.row(),0).data(Qt.ItemDataRole.UserRole)
            for index in sorted(self.table.selectionModel().selectedRows(), key=lambda item:item.row())]

    def character_context_menu(self, position):
        row = self.table.rowAt(position.y())
        if row < 0:
            return
        if not self.table.selectionModel().isRowSelected(row,self.table.rootIndex()):
            self.table.clearSelection()
            self.table.selectRow(row)
        menu = QMenu(self)
        export = menu.addAction('Export as .mkchara')
        delete = menu.addAction('Delete Character')
        delete.setEnabled(all(self.pack.can_edit_skin(*key) for key in self.selected_character_keys()))
        selected = menu.exec(self.table.viewport().mapToGlobal(position))
        if selected == export:
            self.export_character()
        elif selected == delete:
            self.delete_characters()

    def delete_characters(self):
        keys = self.selected_character_keys() or [(self.current_code,slot) for slot in self.selected_character_slots()]
        if not keys:
            return
        if self.has_staged_changes():
            QMessageBox.information(self,'Unsaved slot moves','Save or revert staged slot moves before deleting characters.')
            return
        try:
            plan = self.pack.delete_characters(keys)
            # Existing review dialog is the single confirmation, listing every
            # character and file. Cancellation leaves files and text unchanged.
            self.run_plan(plan)
        except Exception as exc:
            QMessageBox.warning(self,'Cannot delete characters',str(exc))

    def export_character(self):
        if self.independent_normalize_codes:
            QMessageBox.information(self, 'Unsaved normalization', 'Save or revert Character slot normalization before editing or exporting characters.')
            return
        if self.current_slot is None:
            return
        try:
            from .mkchara import build_package, write_package
            keys = self.selected_character_keys()
            if len(keys)>1:
                self.export_selected(grouped=False)
                return
            payload = build_package(self.pack, self.current_code, self.current_slot)
            skin = self.pack.inventory.skins[self.current_code, self.current_slot]
            import re
            filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', skin.name).strip(' .') or 'Character'
            path, _ = QFileDialog.getSaveFileName(self, 'Export Character', filename+'.mkchara',
                                                  'Character packages (*.mkchara)')
            if not path:
                return
            target = Path(path)
            if target.suffix.lower() != '.mkchara':
                target = target.with_suffix('.mkchara')
            backup = write_package(target, payload)
            message = f'Exported {skin.name} to {target.name}.'
            if backup:
                message += f'\nPrevious package backed up to {backup.name}.'
            QMessageBox.information(self, 'Character exported', message)
        except Exception as exc:
            QMessageBox.warning(self, 'Cannot export character', str(exc))

    def refresh(self):
        if self.has_staged_changes() and QMessageBox.question(self, 'Discard staged moves?',
            'Refreshing will discard unsaved slot changes. Continue?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.pending_patch_slots.clear()
        self.staging_patches = False
        self.pending_organization = False
        self.independent_normalize_codes.clear()
        self._thumbnail_timer.stop();self._thumbnail_queue.clear()
        try:read_library_background(self.pack.reload,self)
        except Exception as e:QMessageBox.warning(self,'Refresh failed',str(e));return
        self.reload_view()

    def open_pack(self):
        if self.has_staged_changes() and QMessageBox.question(self, 'Unsaved slot changes',
                'Switching packs will discard unsaved slot moves. Continue?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        dialog=OpenPackDialog(self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.pack=dialog.pack
            self.pending_patch_slots.clear()
            self.staging_patches = False
            self.pending_organization = False
            self.independent_normalize_codes.clear()
            self.current_code='bmr';self.current_slot=None
            self.selected_characters.clear();self._icon_cache.clear();self._icon_cache_bytes=0;self._detail_key=None;self._selection_started=False
            self.reload_view()
    
    def about(self):
        QMessageBox.information(self,'About Retro Rewind Character Manager',
            f'Retro Rewind Character Manager · v{__version__}\n\n'
            'Manages RR-compatible Character libraries and Patches, ReplacedAssets.szs BMG names, '
            'slot insertion/reordering, voices, CSS/map TPL icons, .mkchara packages and backups.\n\n'
            'Not a BRRES model converter. Raw character assets must have a compatible vanilla skeleton. '
            'Text changes require review; runtime loading still depends on your loader. Textured bind-pose previews do not emulate animation or TEV.')


def launch():
    app=QApplication(sys.argv)
    app.setApplicationName('Retro Rewind Character Manager')
    app.setApplicationVersion(__version__)
    app.setOrganizationName('Retro Rewind')
    # PyInstaller extracts bundled data under _MEIPASS; use the source root otherwise.
    icon_root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    icon_file = icon_root / 'full-motorcycle-helmet.png'
    if icon_file.is_file():
        app.setWindowIcon(QIcon(str(icon_file)))
    app.setStyle('Fusion')
    app.setFont(QFont('Segoe UI',10))
    app.setStyleSheet(STYLESHEET)
    dialog=OpenPackDialog()
    if dialog.exec()!=QDialog.DialogCode.Accepted:
        return 0
    window=MainWindow(dialog.pack)
    window.show()
    return app.exec()
