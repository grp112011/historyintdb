import html
import random
import re
import sqlite3
import sys

from PyQt6.QtCore import QEvent, QPoint, QTimer, Qt
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

DB_PATH = "database.sqlite"
HTML_PREVIEW_DELAY_MS = 350
HTML_PREVIEW_WIDTH = 560
HTML_PREVIEW_HEIGHT = 380
HTML_PREVIEW_COLUMNS = {
    "information", "description", "details", "информация", "описание", "подробности",
}
HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")

QUIZ_QUESTION_COUNT = 10
QUIZ_OPTION_COUNT = 4
QUIZ_MAX_ANSWER_LENGTH = 120
QUIZ_MAX_CLUE_LENGTH = 320
QUIZ_RICH_CLUE_LENGTH = 40
QUIZ_CLUE_COLUMNS_MIN = 2
QUIZ_CLUE_COLUMNS_MAX = 3
QUIZ_MAX_QUESTION_ATTEMPTS = QUIZ_QUESTION_COUNT * 100
QUIZ_COLUMN_TEMPLATES = {
    "name": "О ком или о чём идёт речь?", "full name": "Каково полное имя этой личности?",
    "born date": "Когда родился этот человек?", "death date": "Когда умер этот человек?",
    "information": "Выберите правильное описание.", "begin date": "Когда началось это событие?",
    "end date": "Когда завершилось это событие?", "side 2": "Какая сторона указана второй?",
    "result": "Каков итог этого события?", "course": "Как проходило это событие?",
}
QUIZ_EXCLUDED_ANSWER_COLUMNS = {"side 1"}
QUIZ_OPTION_STYLE = "font-size: 14px; padding: 2px 0;"


def quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


class HtmlPreviewPopup(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("htmlPreviewPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet("QFrame#htmlPreviewPopup { background: #ffffff; border: 1px solid #b8b8b8; border-radius: 6px; }")
        self.browser = QTextBrowser(self)
        self.browser.setFrameShape(QFrame.Shape.NoFrame)
        self.browser.setOpenExternalLinks(False)
        self.browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.browser.setStyleSheet("QTextBrowser { background: transparent; color: #202124; }")
        self.browser.document().setDocumentMargin(14)
        self.browser.document().setDefaultStyleSheet(
            "body { color: #202124; font-size: 13px; } p { margin-top: 0; margin-bottom: 8px; } "
            "ul { margin-top: 0; } li { margin-bottom: 5px; } strong { color: #111111; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.addWidget(self.browser)
        self.resize(HTML_PREVIEW_WIDTH, HTML_PREVIEW_HEIGHT)

    def show_html(self, html, global_pos):
        self.browser.setHtml(html)
        self.browser.verticalScrollBar().setValue(0)
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        x, y = global_pos.x() + 20, global_pos.y() + 20
        if x + self.width() > available.right(): x = global_pos.x() - self.width() - 20
        if y + self.height() > available.bottom(): y = global_pos.y() - self.height() - 20
        self.move(max(available.left(), min(x, available.right() - self.width() + 1)),
                  max(available.top(), min(y, available.bottom() - self.height() + 1)))
        self.show()
        self.raise_()


class KnowledgeQuiz(QWidget):
    def __init__(self, connection, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.questions = []
        self.current_index = self.score = 0
        self.answered = False
        self.progress_label = QLabel()
        self.progress_label.setStyleSheet("color: #5f6368; font-size: 13px;")
        self.question_label = QLabel()
        self.question_label.setWordWrap(True)
        self.question_label.setTextFormat(Qt.TextFormat.RichText)
        self.question_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.question_label.setStyleSheet("QLabel { font-size: 15px; color: #202124; }")
        self.options_widget = QWidget()
        self.options_layout = QVBoxLayout(self.options_widget)
        self.options_layout.setContentsMargins(0, 8, 0, 8)
        self.options_layout.setSpacing(6)
        self.option_group = QButtonGroup(self)
        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setMinimumHeight(24)
        self.answer_button = QPushButton("Ответить")
        self.answer_button.clicked.connect(self.check_answer)
        self.next_button = QPushButton("Следующий вопрос")
        self.next_button.clicked.connect(self.go_next)
        self.restart_button = QPushButton("Начать заново")
        self.restart_button.clicked.connect(self.start_quiz)
        buttons = QHBoxLayout()
        for button in (self.answer_button, self.next_button, self.restart_button):
            buttons.addWidget(button)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        for widget in (self.progress_label, self.question_label, self.options_widget, self.feedback_label):
            layout.addWidget(widget)
        layout.addLayout(buttons)
        layout.addStretch()
        self.start_quiz()

    def start_quiz(self):
        self.questions = self.build_questions()
        self.current_index = self.score = 0
        if not self.questions:
            self.progress_label.setText("Тест недоступен")
            self.question_label.setText("Не удалось составить вопросы: в базе недостаточно данных.")
            return self.hide_question_controls()
        self.options_widget.show()
        self.feedback_label.show()
        self.show_question()

    def build_questions(self):
        schemas = self.load_schemas()
        if not schemas:
            return []
        questions, used = [], set()
        for _ in range(QUIZ_MAX_QUESTION_ATTEMPTS):
            if len(questions) == QUIZ_QUESTION_COUNT:
                break
            question = self.make_question(schemas)
            if question is None:
                continue
            key = (question["table"], question["answer_column"], question["correct"])
            if key not in used:
                used.add(key)
                questions.append(question)
        return questions

    def load_schemas(self):
        schemas = []
        try:
            cursor = self.connection.cursor()
            tables = cursor.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            for (table_name,) in tables:
                info = cursor.execute(f"PRAGMA table_info({quote_identifier(table_name)})").fetchall()
                columns = [row[1] for row in info]
                rows = cursor.execute(f"SELECT * FROM {quote_identifier(table_name)}").fetchall()
                if columns and len(rows) >= QUIZ_OPTION_COUNT:
                    schemas.append({
                        "table": table_name, "columns": columns,
                        "primary_keys": {row[1] for row in info if row[5]},
                        "records": [dict(zip(columns, row)) for row in rows],
                    })
        except sqlite3.Error:
            return []
        return schemas

    def make_question(self, schemas):
        schema = random.choice(schemas)
        records, primary_keys = schema["records"], schema["primary_keys"]
        answer_columns = []
        for column in schema["columns"]:
            if column in primary_keys or column in QUIZ_EXCLUDED_ANSWER_COLUMNS:
                continue
            values = {self.format_date(r.get(column)) for r in records} - {""}
            if len(values) < QUIZ_OPTION_COUNT or max(map(len, values)) > QUIZ_MAX_ANSWER_LENGTH:
                continue
            answer_columns.append(column)
        if not answer_columns:
            return None
        answer_column = random.choice(answer_columns)
        target = random.choice([r for r in records if self.format_date(r.get(answer_column))])
        correct = self.format_date(target.get(answer_column))
        distractors = list({self.format_date(r.get(answer_column)) for r in records} - {"", correct})
        if len(distractors) < QUIZ_OPTION_COUNT - 1:
            return None
        clue_candidates = []
        for column in schema["columns"]:
            if column == answer_column or column in primary_keys:
                continue
            clue = self.clue_text(target.get(column))
            if clue and not self.values_overlap(clue, correct):
                clue_candidates.append((column, clue))
        if not clue_candidates:
            return None
        rich_clues = [c for c in clue_candidates if len(c[1]) >= QUIZ_RICH_CLUE_LENGTH]
        if rich_clues:
            selected = [random.choice(rich_clues)]
            remaining = [c for c in clue_candidates if c != selected[0]]
            max_extra = min(QUIZ_CLUE_COLUMNS_MAX - 1, len(remaining))
            if max_extra:
                selected += random.sample(remaining, random.randint(1, max_extra))
        else:
            selected = random.sample(clue_candidates, random.randint(
                min(QUIZ_CLUE_COLUMNS_MIN, len(clue_candidates)),
                min(QUIZ_CLUE_COLUMNS_MAX, len(clue_candidates))))
        selected.sort(key=lambda clue: schema["columns"].index(clue[0]))
        question_text = self.build_question_text(answer_column, selected)
        visible_text = self.plain_text(question_text).casefold()
        if correct.casefold() in visible_text:
            return None
        suitable = [v for v in distractors if v.casefold() not in visible_text]
        if len(suitable) < QUIZ_OPTION_COUNT - 1:
            suitable = distractors
        options = [correct, *random.sample(suitable, QUIZ_OPTION_COUNT - 1)]
        random.shuffle(options)
        return {"table": schema["table"], "answer_column": answer_column, "text": question_text,
                "options": options, "correct": correct}

    def build_question_text(self, answer_column, clues):
        facts = "".join(f"<li>{html.escape(c)}</li>" for _, c in clues)
        template = QUIZ_COLUMN_TEMPLATES.get(answer_column, "Определите правильное значение.")
        return f"<p><b>{html.escape(template)}</b></p><ul>{facts}</ul>"

    def plain_text(self, value):
        if value is None:
            return ""
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value)))).strip()

    def clue_text(self, value):
        text = self.plain_text(value)
        if not text:
            return ""
        text = " ".join(re.split(r"(?<=[.!?])\s+", text)[:2]).strip()
        if len(text) > QUIZ_MAX_CLUE_LENGTH:
            text = text[:QUIZ_MAX_CLUE_LENGTH].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
        return self.format_date(text)

    def values_overlap(self, first, second):
        first, second = first.casefold().strip(), second.casefold().strip()
        return bool(first and second and (first in second or second in first))

    def format_date(self, value):
        text = "" if value is None else str(value).strip()
        match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
        return f"{match.group(3)}.{match.group(2)}.{match.group(1)}" if match else text

    def clear_options(self):
        for button in self.option_group.buttons():
            self.option_group.removeButton(button)
        while self.options_layout.count():
            if (widget := self.options_layout.takeAt(0).widget()):
                widget.deleteLater()

    def hide_question_controls(self):
        for widget in (self.options_widget, self.feedback_label, self.answer_button, self.next_button):
            widget.hide()

    def show_question(self):
        question = self.questions[self.current_index]
        self.answered = False
        self.progress_label.setText(
            f"Вопрос {self.current_index + 1} из {len(self.questions)}"
            f"   ·   Правильных ответов: {self.score}"
        )
        self.question_label.setText(question["text"])
        self.clear_options()
        for option in question["options"]:
            button = QRadioButton(option)
            button.setStyleSheet(QUIZ_OPTION_STYLE)
            self.option_group.addButton(button)
            self.options_layout.addWidget(button)
        self.feedback_label.clear()
        self.feedback_label.setStyleSheet("")
        self.answer_button.show()
        self.answer_button.setEnabled(True)
        self.next_button.hide()

    def check_answer(self):
        if self.answered:
            return
        checked = self.option_group.checkedButton()
        if checked is None:
            self.feedback_label.setText("Сначала выберите вариант ответа.")
            self.feedback_label.setStyleSheet("color: #8a6d3b;")
            return
        correct = self.questions[self.current_index]["correct"]
        selected = checked.text()
        self.answered = True
        if selected == correct:
            self.score += 1
            self.feedback_label.setText("Верно!")
            self.feedback_label.setStyleSheet("color: #1b7f3b; font-weight: bold;")
        else:
            self.feedback_label.setText(f"Неверно. Правильный ответ: {correct}")
            self.feedback_label.setStyleSheet("color: #b3261e; font-weight: bold;")
        for button in self.option_group.buttons():
            button.setEnabled(False)
            if button.text() == correct:
                button.setStyleSheet(f"{QUIZ_OPTION_STYLE} color: #1b7f3b; font-weight: bold;")
            elif button is checked:
                button.setStyleSheet(f"{QUIZ_OPTION_STYLE} color: #b3261e;")
        self.answer_button.hide()
        self.next_button.setText(
            "Показать результат" if self.current_index == len(self.questions) - 1
            else "Следующий вопрос"
        )
        self.next_button.show()

    def go_next(self):
        if self.current_index + 1 >= len(self.questions):
            return self.show_result()
        self.current_index += 1
        self.show_question()

    def show_result(self):
        total = len(self.questions)
        self.progress_label.setText(f"Результат: {self.score} из {total}")
        self.question_label.setText(
            f"<h2>Тест завершён</h2><p>Правильных ответов: <b>{self.score} из {total}</b></p>"
            "<p>Нажмите «Начать заново», чтобы пройти тест ещё раз.</p>"
        )
        self.hide_question_controls()


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Браузер базы данных")
        self.resize(1100, 650)
        self.connection = sqlite3.connect(DB_PATH)
        self.cursor = self.connection.cursor()
        self.table_combo = QComboBox()
        self.table_combo.addItems([row[0] for row in self.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )])
        self.table_combo.currentTextChanged.connect(self.change_table)
        self.search_layout = QHBoxLayout()
        self.search_layout.setContentsMargins(0, 0, 0, 0)
        self.search_layout.setSpacing(0)
        self.search_fields = []
        self.current_table = ""
        self.columns, self.required_columns, self.row_ids = [], [], []
        self.not_null_columns = set()
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.AnyKeyPressed)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(40)
        self.table.itemChanged.connect(self.save_item)
        self.preview_popup = HtmlPreviewPopup(self)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.show_html_preview)
        self.hover_cell = None
        self.hover_pos = QPoint()
        self.table.viewport().setMouseTracking(True)
        self.table.viewport().installEventFilter(self)
        self.table.installEventFilter(self)
        for bar in (self.table.horizontalScrollBar(), self.table.verticalScrollBar()):
            bar.valueChanged.connect(self.reset_html_preview)
        self.add_row_button = QPushButton("Добавить строку")
        self.add_row_button.clicked.connect(self.add_row)
        self.delete_row_button = QPushButton("Удалить строку")
        self.delete_row_button.clicked.connect(self.delete_row)
        top = QHBoxLayout()
        for widget in (QLabel("Таблица:"), self.table_combo, self.add_row_button, self.delete_row_button):
            top.addWidget(widget)
        top.addStretch()
        table_page = QWidget()
        table_page_layout = QVBoxLayout(table_page)
        table_page_layout.setContentsMargins(0, 0, 0, 0)
        table_page_layout.addLayout(top)
        table_page_layout.addLayout(self.search_layout)
        table_page_layout.addWidget(self.table, 1)
        knowledge_page = QWidget()
        knowledge_page_layout = QVBoxLayout(knowledge_page)
        knowledge_page_layout.setContentsMargins(0, 0, 0, 0)
        self.quiz = KnowledgeQuiz(self.connection)
        knowledge_page_layout.addWidget(self.quiz)
        self.tabs = QTabWidget()
        self.tabs.addTab(table_page, "Таблица")
        self.tabs.addTab(knowledge_page, "Проверка знаний")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.tabs)
        self.change_table(self.table_combo.currentText())

    def change_table(self, name):
        if not name:
            return
        self.reset_html_preview()
        self.current_table = name
        info = self.cursor.execute(f"PRAGMA table_info({quote_identifier(name)})").fetchall()
        all_columns = [row[1] for row in info]
        primary_keys = [row[1] for row in info if row[5]]
        primary_key = primary_keys[0] if len(primary_keys) == 1 else None
        self.columns = [c for c in all_columns if c != primary_key]
        self.not_null_columns = {row[1] for row in info if row[3]}
        self.required_columns = [row[1] for row in info if row[3] and row[4] is None and row[1] != primary_key]
        while self.search_layout.count():
            if (widget := self.search_layout.takeAt(0).widget()):
                widget.deleteLater()
        self.search_fields.clear()
        for column in self.columns:
            field = QLineEdit()
            field.setPlaceholderText(column)
            field.setClearButtonEnabled(True)
            field.textChanged.connect(self.filter_rows)
            self.search_layout.addWidget(field)
            self.search_fields.append(field)
        rows = self.cursor.execute(f"SELECT rowid, * FROM {quote_identifier(name)}").fetchall()
        self.row_ids = [row[0] for row in rows]
        self.table.blockSignals(True)
        self.table.clear()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.setRowCount(len(rows))
        for row_number, row in enumerate(rows):
            record = dict(zip(all_columns, row[1:]))
            for column_number, column in enumerate(self.columns):
                value = record[column]
                self.table.setItem(row_number, column_number, QTableWidgetItem("" if value is None else str(value)))
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self.filter_rows()

    def eventFilter(self, watched, event):
        if watched is self.table.viewport():
            if event.type() == QEvent.Type.MouseMove:
                self.update_html_preview_hover(
                    self.table.indexAt(event.position().toPoint()), event.globalPosition().toPoint()
                )
            elif event.type() == QEvent.Type.Leave or event.type() in (
                QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick,
                QEvent.Type.Wheel, QEvent.Type.KeyPress,
            ):
                self.reset_html_preview()
        elif watched is self.table and event.type() == QEvent.Type.KeyPress:
            self.reset_html_preview()
        return super().eventFilter(watched, event)

    def html_preview_text(self, row, column):
        if not (0 <= row < self.table.rowCount() and 0 <= column < len(self.columns)):
            return None
        item = self.table.item(row, column)
        if item is None or self.table.isRowHidden(row):
            return None
        text = item.text()
        return text if self.should_show_html_preview(self.columns[column], text) else None

    def update_html_preview_hover(self, index, global_pos):
        if not index.isValid() or self.html_preview_text(index.row(), index.column()) is None:
            return self.reset_html_preview()
        self.hover_pos = global_pos
        cell = (index.row(), index.column())
        if cell != self.hover_cell:
            self.hover_cell = cell
            self.preview_popup.hide()
            self.preview_timer.start(HTML_PREVIEW_DELAY_MS)

    def should_show_html_preview(self, column, text):
        return bool(text.strip()) and (
            column.casefold() in HTML_PREVIEW_COLUMNS or HTML_TAG_RE.search(text) is not None
        )

    def show_html_preview(self):
        if self.hover_cell is None:
            return
        row, column = self.hover_cell
        text = self.html_preview_text(row, column)
        if text is None:
            return self.reset_html_preview()
        cursor_index = self.table.indexAt(self.table.viewport().mapFromGlobal(QCursor.pos()))
        if cursor_index.row() == row and cursor_index.column() == column:
            self.preview_popup.show_html(text, self.hover_pos)

    def reset_html_preview(self):
        self.preview_timer.stop()
        self.hover_cell = None
        self.preview_popup.hide()

    def save_item(self, item):
        row = item.row()
        if row >= len(self.row_ids):
            return
        column = self.columns[item.column()]
        text = item.text()
        value = None if text == "" and column not in self.not_null_columns else text
        try:
            self.cursor.execute(
                f"UPDATE {quote_identifier(self.current_table)} "
                f"SET {quote_identifier(column)} = ? WHERE rowid = ?",
                (value, self.row_ids[row]),
            )
            self.connection.commit()
        except sqlite3.Error as error:
            self.connection.rollback()
            QMessageBox.critical(self, "Ошибка сохранения", f"Не удалось сохранить изменения:\n{error}")
            self.change_table(self.current_table)
            return
        self.filter_rows()

    def add_row(self):
        table = quote_identifier(self.current_table)
        columns = self.required_columns
        sql = (
            f"INSERT INTO {table} ({', '.join(map(quote_identifier, columns))}) "
            f"VALUES ({', '.join('?' for _ in columns)})"
            if columns else f"INSERT INTO {table} DEFAULT VALUES"
        )
        try:
            self.cursor.execute(sql, [""] * len(columns))
            new_row_id = self.cursor.lastrowid
            self.connection.commit()
        except sqlite3.Error as error:
            self.connection.rollback()
            QMessageBox.critical(self, "Ошибка добавления", f"Не удалось добавить строку:\n{error}")
            return
        for field in self.search_fields:
            field.clear()
        self.change_table(self.current_table)
        if new_row_id in self.row_ids:
            row_number = self.row_ids.index(new_row_id)
            self.table.setCurrentCell(row_number, 0)
            self.table.editItem(self.table.item(row_number, 0))

    def delete_row(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]
        rows = [row for row in rows if row < len(self.row_ids)]
        if not rows:
            return QMessageBox.information(self, "Удаление строки", "Сначала выберите строку для удаления.")
        question = "Удалить выбранную строку?" if len(rows) == 1 else f"Удалить выбранные строки ({len(rows)})?"
        if QMessageBox.question(self, "Удаление строки", question) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.cursor.executemany(
                f"DELETE FROM {quote_identifier(self.current_table)} WHERE rowid = ?",
                [(self.row_ids[row],) for row in rows],
            )
            self.connection.commit()
        except sqlite3.Error as error:
            self.connection.rollback()
            QMessageBox.critical(self, "Ошибка удаления", f"Не удалось удалить строку:\n{error}")
            return
        self.change_table(self.current_table)

    def filter_rows(self):
        needles = [field.text().casefold() for field in self.search_fields]
        for row in range(self.table.rowCount()):
            values = [self.table.item(row, column).text().casefold()
                      for column in range(self.table.columnCount())]
            self.table.setRowHidden(row, any(n not in v for n, v in zip(needles, values)))


def main():
    app = QApplication(sys.argv)
    window = App()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
