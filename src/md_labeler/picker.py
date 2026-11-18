"""Desktop window for choosing albums from a <root>/<artist>/<album> music library."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from md_labeler.albumlist import AlbumEntry
from md_labeler.fetch.local import is_album_folder, read_album
from md_labeler.geometry import Paper, art_px_needed

FOLDER_ROLE = Qt.ItemDataRole.UserRole
INFO_TIP = (
    f"Read from the album's own files. Missing or low-res art (under {art_px_needed()}px) "
    "and missing track tags will be looked up on MusicBrainz / Cover Art Archive."
)


def scan_library(root: Path) -> dict[str, list[Path]]:
    """Artist folder name -> album folders that contain audio, both sorted case-insensitively."""
    library: dict[str, list[Path]] = {}
    for artist in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
        albums = sorted((p for p in artist.iterdir() if p.is_dir() and is_album_folder(p)), key=lambda p: p.name.lower())
        if albums:
            library[artist.name] = albums
    return library


def describe(folder: Path) -> str:
    """Short summary of what local files provide: track count and cover art quality."""
    album, cover = read_album(folder, folder.parent.name, folder.name)
    tracks = f"{len(album.tracks)} tracks"
    if cover is None:
        return f"{tracks}, no art"
    if cover.px < art_px_needed():
        return f"{tracks}, art {cover.px}px (low-res)"
    return f"{tracks}, art {cover.px}px"


class AlbumPicker(QDialog):
    def __init__(self, music_root: Path, slots: dict[Paper, int], paper: Paper):
        super().__init__()
        self.slots = slots
        self.paper = paper
        self.selected: list[AlbumEntry] = []
        self.library: dict[str, list[Path]] = {}
        self.setWindowTitle("md-labeler: pick albums")
        self.resize(1150, 700)
        self._build()
        self._set_root(music_root)

    # --- layout ---

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Music folder:"))
        self.root_label = QLabel()
        self.root_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self.root_label, 1)
        change = QPushButton("Change…")
        change.clicked.connect(self._choose_root)
        top.addWidget(change)
        layout.addLayout(top)

        bar = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Search artists and albums…", clearButtonEnabled=True)
        self.search.textChanged.connect(self._fill_tree)
        bar.addWidget(self.search, 1)
        bar.addWidget(QLabel("Paper:"))
        self.paper_box = QComboBox()
        for p, n in self.slots.items():
            self.paper_box.addItem(f"{p.value} ({n} albums)", p)
        self.paper_box.setCurrentIndex(list(self.slots).index(self.paper))
        self.paper_box.currentIndexChanged.connect(self._paper_changed)
        bar.addWidget(self.paper_box)
        layout.addLayout(bar)

        split = QSplitter()
        self.tree = QTreeWidget(headerHidden=True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(lambda item, _col: self._add() if item.data(0, FOLDER_ROLE) else None)
        split.addWidget(self.tree)

        mid = QWidget()
        mid_layout = QVBoxLayout(mid)
        mid_layout.addStretch()
        self.add_btn = QPushButton("Add →")
        self.add_btn.clicked.connect(self._add)
        remove = QPushButton("← Remove")
        remove.clicked.connect(self._remove)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear)
        for b in (self.add_btn, remove, clear):
            mid_layout.addWidget(b)
        mid_layout.addStretch()
        split.addWidget(mid)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.count_label = QLabel()
        font = self.count_label.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.15)
        self.count_label.setFont(font)
        right_layout.addWidget(self.count_label)
        self.list = QTreeWidget(rootIsDecorated=False)
        self.list.setHeaderLabels(["#", "Artist", "Album", "From local files"])
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        header = self.list.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.list.setColumnWidth(1, 160)
        self.list.setColumnWidth(2, 200)
        right_layout.addWidget(self.list)
        split.addWidget(right)
        split.setSizes([380, 110, 660])
        layout.addWidget(split, 1)

        bottom = QHBoxLayout()
        self.status = QLabel()
        bottom.addWidget(self.status, 1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        self.done_btn = QPushButton("Make labels")
        self.done_btn.setDefault(True)
        self.done_btn.clicked.connect(self._done)
        bottom.addWidget(self.done_btn)
        layout.addLayout(bottom)

        self.search.setFocus()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.tree.hasFocus():
            self._add()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.list.hasFocus():
            self._remove()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return  # don't let Enter in the search box trigger "Make labels"
        else:
            super().keyPressEvent(event)

    # --- library tree ---

    def _set_root(self, root: Path) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.library = scan_library(root)
        except OSError as e:
            QMessageBox.critical(self, "Music folder", f"Can't read {root}:\n{e}")
            self.library = {}
        finally:
            QApplication.restoreOverrideCursor()
        self.root_label.setText(str(root))
        self._fill_tree()
        self._refresh()

    def _choose_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Music folder (artist/album layout)", self.root_label.text())
        if path:
            self._set_root(Path(path))

    def _fill_tree(self) -> None:
        q = self.search.text().strip().lower()
        self.tree.clear()
        for artist, albums in self.library.items():
            shown = albums if not q or q in artist.lower() else [a for a in albums if q in a.name.lower()]
            if not shown:
                continue
            node = QTreeWidgetItem(self.tree, [artist])
            node.setFlags(node.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for album in shown:
                child = QTreeWidgetItem(node, [album.name])
                child.setData(0, FOLDER_ROLE, str(album))
            node.setExpanded(bool(q))

    # --- selection ---

    @property
    def capacity(self) -> int:
        return self.slots[self.paper]

    def _add(self) -> None:
        folders = [Path(i.data(0, FOLDER_ROLE)) for i in self.tree.selectedItems() if i.data(0, FOLDER_ROLE)]
        if not folders:
            self.status.setText("Select an album (expand an artist to see its albums).")
            return
        for folder in folders:
            if len(self.selected) >= self.capacity:
                break
            entry = AlbumEntry(folder.parent.name, folder.name, folder)
            if entry in self.selected:
                continue
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                info = describe(folder)
            except OSError as e:
                info = f"unreadable: {e}"
            finally:
                QApplication.restoreOverrideCursor()
            self.selected.append(entry)
            item = QTreeWidgetItem(self.list, ["", entry.artist, entry.album, info])
            item.setData(0, FOLDER_ROLE, str(folder))
            item.setToolTip(2, str(folder))
            item.setToolTip(3, INFO_TIP)
        self._refresh()

    def _remove(self) -> None:
        for item in self.list.selectedItems():
            folder = item.data(0, FOLDER_ROLE)
            self.selected = [e for e in self.selected if str(e.folder) != folder]
            self.list.takeTopLevelItem(self.list.indexOfTopLevelItem(item))
        self._refresh()

    def _clear(self) -> None:
        self.selected.clear()
        self.list.clear()
        self._refresh()

    def _paper_changed(self, index: int) -> None:
        paper = self.paper_box.itemData(index)
        if len(self.selected) > self.slots[paper]:
            QMessageBox.warning(self, "Paper", f"{paper.value} fits {self.slots[paper]} albums; remove some first.")
            self.paper_box.blockSignals(True)
            self.paper_box.setCurrentIndex(list(self.slots).index(self.paper))
            self.paper_box.blockSignals(False)
            return
        self.paper = paper
        self._refresh()

    def _refresh(self) -> None:
        for i in range(self.list.topLevelItemCount()):
            self.list.topLevelItem(i).setText(0, str(i + 1))
        n, cap = len(self.selected), self.capacity
        self.count_label.setText(f"Selected: {n} / {cap} slots ({self.paper.value}, 2 pages)")
        self.add_btn.setEnabled(n < cap)
        self.done_btn.setEnabled(n > 0)
        if n >= cap:
            self.status.setText(f"All {cap} slots full. Click Make labels.")
        else:
            self.status.setText(f"{cap - n} slot(s) left. Double-click an album to add it.")

    def _done(self) -> None:
        n, cap = len(self.selected), self.capacity
        if n < cap:
            answer = QMessageBox.question(self, "Make labels", f"Only {n} of {cap} slots are filled. Make labels anyway?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.accept()

    def run(self) -> tuple[list[AlbumEntry], Paper] | None:
        return (list(self.selected), self.paper) if self.exec() == QDialog.DialogCode.Accepted else None


def pick_albums(music_root: Path, slots: dict[Paper, int], paper: Paper) -> tuple[list[AlbumEntry], Paper] | None:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("md-labeler")
    return AlbumPicker(music_root, slots, paper).run()
