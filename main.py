import sqlite3
import sys

DEBUG_MODE = True

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

DB_PATH = "database.sqlite"


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
        if DEBUG_MODE:
            print(f'[DEBUG] base UI crated')

        self.change_table(self.table_combo.currentText())

    def change_table(self, name: str) -> None:
        if DEBUG_MODE:
            print(f'[DEBUG] table changing started')
        while self.search_layout.count():
            widget = self.search_layout.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        self.search_fields.clear()
        self.columns = [
            row[1]
            for row in self.cursor.execute(f'PRAGMA table_info("{name}")').fetchall()
            if row[1].casefold() != "id"
        ]

        for column in self.columns:
            field = QLineEdit()
            field.setPlaceholderText(column)
            field.setClearButtonEnabled(True)
            field.textChanged.connect(self.filter_rows)
            self.search_layout.addWidget(field)
            self.search_fields.append(field)

        rows = self.cursor.execute(f'SELECT * FROM "{name}"').fetchall()

        self.table.clear()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.setRowCount(len(rows))
        if DEBUG_MODE:
            print(f'[DEBUG][change_table] UI updated')
        for row_number, row in enumerate(rows):
            for column_number, column in enumerate(self.columns):
                value = row[column_number + 1]
                
                self.table.setItem(
                    row_number,
                    column_number,
                    QTableWidgetItem("" if value is None else str(value)),
                )
                if DEBUG_MODE:
                    print(f'[DEBUG][change_table] item {column_number + 1} added')
                


        self.filter_rows()

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
