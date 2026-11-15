import re
import sqlite3
import sys

DEBUG_MODE = True

from PyQt6.QtCore import QEvent, QPoint, QTimer, Qt
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

DB_PATH = "database.sqlite"

HTML_PREVIEW_DELAY_MS = 350
HTML_PREVIEW_WIDTH = 560
HTML_PREVIEW_HEIGHT = 380
HTML_PREVIEW_COLUMNS = {
    "information",
    "description",
    "details",
    "информация",
    "описание",
    "подробности",
}
HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


class HtmlPreviewPopup(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint,
        )
        self.setObjectName("htmlPreviewPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet(
            "QFrame#htmlPreviewPopup {"
            " background: #ffffff;"
            " border: 1px solid #b8b8b8;"
            " border-radius: 6px;"
            "}"
        )

        self.browser = QTextBrowser(self)
        self.browser.setFrameShape(QFrame.Shape.NoFrame)
        self.browser.setOpenExternalLinks(False)
        self.browser.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.browser.setStyleSheet(
            "QTextBrowser { background: transparent; color: #202124; }"
        )
        self.browser.document().setDocumentMargin(14)
        self.browser.document().setDefaultStyleSheet(
            "body { color: #202124; font-size: 13px; }"
            "p { margin-top: 0; margin-bottom: 8px; }"
            "ul { margin-top: 0; }"
            "li { margin-bottom: 5px; }"
            "strong { color: #111111; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.addWidget(self.browser)
        self.resize(HTML_PREVIEW_WIDTH, HTML_PREVIEW_HEIGHT)

    def show_html(self, html: str, global_pos: QPoint) -> None:
        self.browser.setHtml(html)
        self.browser.verticalScrollBar().setValue(0)

        screen = QGuiApplication.screenAt(global_pos)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry()

        x = global_pos.x() + 20
        y = global_pos.y() + 20
        if x + self.width() > available.right():
            x = global_pos.x() - self.width() - 20
        if y + self.height() > available.bottom():
            y = global_pos.y() - self.height() - 20

        x = max(available.left(), min(x, available.right() - self.width() + 1))
        y = max(available.top(), min(y, available.bottom() - self.height() + 1))
        self.move(x, y)
        self.show()
        self.raise_()


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Браузер базы данных")
        self.resize(1100, 650)

        self.connection = sqlite3.connect(DB_PATH)
        self.cursor = self.connection.cursor()

        self.table_combo = QComboBox()
        self.table_combo.addItems(
            [
                row[0]
                for row in self.cursor.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY name"
                ).fetchall()
            ]
        )
        self.table_combo.currentTextChanged.connect(self.change_table)

        if DEBUG_MODE:
            print(f'[DEBUG] DB imported')
        self.search_layout = QHBoxLayout()
        self.search_layout.setContentsMargins(0, 0, 0, 0)
        self.search_layout.setSpacing(0)
        self.search_fields = []

        self.current_table = ""
        self.columns = []
        self.not_null_columns = set()
        self.required_columns = []
        self.row_ids = []

        self.table = QTableWidget()
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.EditKeyPressed
            | QTableWidget.EditTrigger.AnyKeyPressed
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setMinimumSectionSize(40)
        self.table.itemChanged.connect(self.save_item)

        self.preview_popup = HtmlPreviewPopup(self)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.show_html_preview)
        self.hover_cell: tuple[int, int] | None = None
        self.hover_pos = QPoint()

        self.table.viewport().setMouseTracking(True)
        self.table.viewport().installEventFilter(self)
        self.table.installEventFilter(self)
        self.table.horizontalScrollBar().valueChanged.connect(
            self.reset_html_preview
        )
        self.table.verticalScrollBar().valueChanged.connect(
            self.reset_html_preview
        )

        self.add_row_button = QPushButton("Добавить строку")
        self.add_row_button.clicked.connect(self.add_row)

        self.delete_row_button = QPushButton("Удалить строку")
        self.delete_row_button.clicked.connect(self.delete_row)

        top = QHBoxLayout()
        top.addWidget(QLabel("Таблица:"))
        top.addWidget(self.table_combo)
        top.addWidget(self.add_row_button)
        top.addWidget(self.delete_row_button)
        top.addStretch()

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(self.search_layout)
        layout.addWidget(self.table, 1)
        if DEBUG_MODE:
            print(f'[DEBUG] base UI crated')

        self.change_table(self.table_combo.currentText())

    def change_table(self, name: str) -> None:
        if not name:
            return

        self.reset_html_preview()

        if DEBUG_MODE:
            print(f'[DEBUG] table changing started')

        self.current_table = name
        info = self.cursor.execute(f'PRAGMA table_info("{name}")').fetchall()
        all_columns = [row[1] for row in info]
        primary_keys = [row[1] for row in info if row[5]]
        primary_key = primary_keys[0] if len(primary_keys) == 1 else None

        self.columns = [column for column in all_columns if column != primary_key]
        self.not_null_columns = {row[1] for row in info if row[3]}
        self.required_columns = [
            row[1]
            for row in info
            if row[3] and row[4] is None and row[1] != primary_key
        ]

        while self.search_layout.count():
            widget = self.search_layout.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        self.search_fields.clear()

        for column in self.columns:
            field = QLineEdit()
            field.setPlaceholderText(column)
            field.setClearButtonEnabled(True)
            field.textChanged.connect(self.filter_rows)
            self.search_layout.addWidget(field)
            self.search_fields.append(field)

        rows = self.cursor.execute(f'SELECT rowid, * FROM "{name}"').fetchall()
        self.row_ids = [row[0] for row in rows]
        indexes = {column: index + 1 for index, column in enumerate(all_columns)}

        self.table.blockSignals(True)
        self.table.clear()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.setRowCount(len(rows))
        for row_number, row in enumerate(rows):
            for column_number, column in enumerate(self.columns):
                value = row[indexes[column]]
                self.table.setItem(
                    row_number,
                    column_number,
                    QTableWidgetItem("" if value is None else str(value)),
                )
        self.table.blockSignals(False)

        self.table.resizeColumnsToContents()
        if DEBUG_MODE:
            print(f'[DEBUG][change_table] UI updated')
        self.filter_rows()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.table.viewport():
            if event.type() == QEvent.Type.MouseMove:
                index = self.table.indexAt(event.position().toPoint())
                self.update_html_preview_hover(
                    index, event.globalPosition().toPoint()
                )
            elif event.type() == QEvent.Type.Leave:
                self.reset_html_preview()
            elif event.type() in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonDblClick,
                QEvent.Type.Wheel,
                QEvent.Type.KeyPress,
            ):
                self.reset_html_preview()
        elif watched is self.table and event.type() == QEvent.Type.KeyPress:
            self.reset_html_preview()

        return super().eventFilter(watched, event)

    def update_html_preview_hover(self, index, global_pos: QPoint) -> None:
        row = index.row()
        column = index.column()
        column_name = self.columns[column] if 0 <= column < len(self.columns) else ""
        item = self.table.item(row, column) if index.isValid() else None

        if (
            not index.isValid()
            or self.table.isRowHidden(row)
            or item is None
            or not self.should_show_html_preview(column_name, item.text())
        ):
            self.reset_html_preview()
            return

        self.hover_pos = global_pos
        cell = (row, column)
        if cell != self.hover_cell:
            self.hover_cell = cell
            self.preview_popup.hide()
            self.preview_timer.start(HTML_PREVIEW_DELAY_MS)

    def should_show_html_preview(self, column: str, text: str) -> bool:
        if not text.strip():
            return False
        return (
            column.casefold() in HTML_PREVIEW_COLUMNS
            or HTML_TAG_RE.search(text) is not None
        )

    def show_html_preview(self) -> None:
        if self.hover_cell is None:
            return

        row, column = self.hover_cell
        if (
            row >= self.table.rowCount()
            or column >= self.table.columnCount()
            or self.table.isRowHidden(row)
        ):
            self.reset_html_preview()
            return

        item = self.table.item(row, column)
        column_name = self.columns[column] if column < len(self.columns) else ""
        if item is None or not self.should_show_html_preview(
            column_name, item.text()
        ):
            self.reset_html_preview()
            return

        cursor_index = self.table.indexAt(
            self.table.viewport().mapFromGlobal(QCursor.pos())
        )
        if cursor_index.row() != row or cursor_index.column() != column:
            return

        self.preview_popup.show_html(item.text(), self.hover_pos)

    def reset_html_preview(self) -> None:
        self.preview_timer.stop()
        self.hover_cell = None
        self.preview_popup.hide()

    def save_item(self, item: QTableWidgetItem) -> None:
        row_number = item.row()
        if row_number >= len(self.row_ids):
            return

        column = self.columns[item.column()]
        text = item.text()
        value = None if text == "" and column not in self.not_null_columns else text

        try:
            self.cursor.execute(
                f'UPDATE "{self.current_table}" SET "{column}" = ? '
                "WHERE rowid = ?",
                (value, self.row_ids[row_number]),
            )
            self.connection.commit()
        except sqlite3.Error as error:
            self.connection.rollback()
            QMessageBox.critical(
                self,
                "Ошибка сохранения",
                f"Не удалось сохранить изменения:\n{error}",
            )
            self.change_table(self.current_table)
            return

        self.filter_rows()

    def add_row(self) -> None:
        try:
            if self.required_columns:
                columns = ", ".join(f'"{column}"' for column in self.required_columns)
                placeholders = ", ".join("?" for _ in self.required_columns)
                self.cursor.execute(
                    f'INSERT INTO "{self.current_table}" '
                    f"({columns}) VALUES ({placeholders})",
                    [""] * len(self.required_columns),
                )
            else:
                self.cursor.execute(
                    f'INSERT INTO "{self.current_table}" DEFAULT VALUES'
                )
            new_row_id = self.cursor.lastrowid
            self.connection.commit()
        except sqlite3.Error as error:
            self.connection.rollback()
            QMessageBox.critical(
                self,
                "Ошибка добавления",
                f"Не удалось добавить строку:\n{error}",
            )
            return

        for field in self.search_fields:
            field.clear()
        self.change_table(self.current_table)

        if new_row_id in self.row_ids:
            row_number = self.row_ids.index(new_row_id)
            self.table.setCurrentCell(row_number, 0)
            self.table.editItem(self.table.item(row_number, 0))

    def delete_row(self) -> None:
        row_numbers = sorted(
            {index.row() for index in self.table.selectedIndexes()}
        )
        if not row_numbers and self.table.currentRow() >= 0:
            row_numbers = [self.table.currentRow()]
        row_numbers = [
            row_number
            for row_number in row_numbers
            if row_number < len(self.row_ids)
        ]

        if not row_numbers:
            QMessageBox.information(
                self,
                "Удаление строки",
                "Сначала выберите строку для удаления.",
            )
            return

        question = (
            "Удалить выбранную строку?"
            if len(row_numbers) == 1
            else f"Удалить выбранные строки ({len(row_numbers)})?"
        )
        if (
            QMessageBox.question(self, "Удаление строки", question)
            != QMessageBox.StandardButton.Yes
        ):
            return

        try:
            self.cursor.executemany(
                f'DELETE FROM "{self.current_table}" WHERE rowid = ?',
                [(self.row_ids[row_number],) for row_number in row_numbers],
            )
            self.connection.commit()
        except sqlite3.Error as error:
            self.connection.rollback()
            QMessageBox.critical(
                self,
                "Ошибка удаления",
                f"Не удалось удалить строку:\n{error}",
            )
            return

        if DEBUG_MODE:
            print(f'[DEBUG] deleted rows: {row_numbers}')
        self.change_table(self.current_table)

    def filter_rows(self) -> None:
        if DEBUG_MODE:
            print(f'[DEBUG] filter_row started')
        needles = [field.text().casefold() for field in self.search_fields]
        for row_number in range(self.table.rowCount()):
            values = [
                self.table.item(row_number, column_number).text().casefold()
                for column_number in range(self.table.columnCount())
            ]
            self.table.setRowHidden(
                row_number,
                not all(
                    not needle or needle in value
                    for needle, value in zip(needles, values)
                ),
            )

        if DEBUG_MODE:
            print(f'[DEBUG] filter_row finished')


def main() -> int:
    app = QApplication(sys.argv)
    window = App()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
