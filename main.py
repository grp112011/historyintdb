import sqlite3
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

DB_PATH = Path(__file__).resolve().parent / "database.sqlite"


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Браузер базы данных")
        self.resize(1100, 650)

        self.db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row

        self.table_combo = QComboBox()
        self.table_combo.addItems(
            [
                row[0]
                for row in self.db.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY name"
                )
            ]
        )
        self.table_combo.currentTextChanged.connect(self.change_table)

        self.search_layout = QHBoxLayout()
        self.search_layout.setContentsMargins(0, 0, 0, 0)
        self.search_layout.setSpacing(0)
        self.search_fields = []

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )

        top = QHBoxLayout()
        top.addWidget(QLabel("Таблица:"))
        top.addWidget(self.table_combo)
        top.addStretch()

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(self.search_layout)
        layout.addWidget(self.table, 1)

        self.change_table(self.table_combo.currentText())

    def change_table(self, name: str) -> None:
        while self.search_layout.count():
            widget = self.search_layout.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        self.search_fields.clear()

        self.columns = [
            row["name"]
            for row in self.db.execute(f'PRAGMA table_info("{name}")')
            if row["name"].casefold() != "id"
        ]

        for column in self.columns:
            field = QLineEdit()
            field.setPlaceholderText(column)
            field.setClearButtonEnabled(True)
            field.textChanged.connect(self.filter_rows)
            self.search_layout.addWidget(field)
            self.search_fields.append(field)

        rows = self.db.execute(f'SELECT * FROM "{name}"').fetchall()

        self.table.clear()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.setRowCount(len(rows))

        for row_number, row in enumerate(rows):
            for column_number, column in enumerate(self.columns):
                value = row[column]
                self.table.setItem(
                    row_number,
                    column_number,
                    QTableWidgetItem("" if value is None else str(value)),
                )

        self.filter_rows()

    def filter_rows(self) -> None:
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


def main() -> int:
    app = QApplication(sys.argv)
    window = App()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
