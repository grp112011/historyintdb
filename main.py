import html
import random
import re
import sqlite3
import sys

DEBUG_MODE = True

from PyQt6.QtCore import QEvent, QPoint, QTimer, Qt
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTabWidget,
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

QUIZ_QUESTION_COUNT = 10
QUIZ_OPTION_COUNT = 4
QUIZ_MAX_ANSWER_LENGTH = 120
QUIZ_MAX_CLUE_LENGTH = 320
QUIZ_RICH_CLUE_LENGTH = 40
QUIZ_CLUE_COLUMNS_MIN = 2
QUIZ_CLUE_COLUMNS_MAX = 3
QUIZ_MAX_QUESTION_ATTEMPTS = QUIZ_QUESTION_COUNT * 100
QUIZ_COLUMN_TEMPLATES = {
    "name": "О ком или о чём идёт речь?",
    "full name": "Каково полное имя этой личности?",
    "born date": "Когда родился этот человек?",
    "death date": "Когда умер этот человек?",
    "information": "Выберите правильное описание.",
    "begin date": "Когда началось это событие?",
    "end date": "Когда завершилось это событие?",
    "side 2": "Какая сторона указана второй?",
    "result": "Каков итог этого события?",
    "course": "Как проходило это событие?",
}
QUIZ_EXCLUDED_ANSWER_COLUMNS = {"side 1"}


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


class KnowledgeQuiz(QWidget):
    def __init__(self, connection: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.connection = connection
        self.questions: list[dict] = []
        self.current_index = 0
        self.score = 0
        self.answered = False

        self.progress_label = QLabel()
        self.progress_label.setStyleSheet("color: #5f6368; font-size: 13px;")

        self.question_label = QLabel()
        self.question_label.setWordWrap(True)
        self.question_label.setTextFormat(Qt.TextFormat.RichText)
        self.question_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.question_label.setStyleSheet(
            "QLabel { font-size: 15px; color: #202124; }"
        )

        self.options_widget = QWidget()
        self.options_layout = QVBoxLayout(self.options_widget)
        self.options_layout.setContentsMargins(0, 8, 0, 8)
        self.options_layout.setSpacing(6)

        self.option_group = QButtonGroup(self)
        self.option_group.setExclusive(True)

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
        buttons.addWidget(self.answer_button)
        buttons.addWidget(self.next_button)
        buttons.addWidget(self.restart_button)
        buttons.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.question_label)
        layout.addWidget(self.options_widget)
        layout.addWidget(self.feedback_label)
        layout.addLayout(buttons)
        layout.addStretch()

        self.start_quiz()

    def start_quiz(self) -> None:
        self.questions = self.build_questions()
        self.current_index = 0
        self.score = 0
        self.answered = False

        if not self.questions:
            self.progress_label.setText("Тест недоступен")
            self.question_label.setText(
                "Не удалось составить вопросы: в базе недостаточно данных."
            )
            self.options_widget.hide()
            self.feedback_label.hide()
            self.answer_button.hide()
            self.next_button.hide()
            self.restart_button.show()
            return

        self.options_widget.show()
        self.feedback_label.show()
        self.restart_button.show()
        self.show_question()

    def build_questions(self) -> list[dict]:
        schemas = self.load_schemas()
        if not schemas:
            return []

        questions = []
        used = set()
        attempts = 0
        while (
            len(questions) < QUIZ_QUESTION_COUNT
            and attempts < QUIZ_MAX_QUESTION_ATTEMPTS
        ):
            attempts += 1
            question = self.make_question(schemas)
            if question is None:
                continue

            key = (
                question["table"],
                question["answer_column"],
                question["correct"],
            )
            if key in used:
                continue

            used.add(key)
            questions.append(question)

        return questions

    def load_schemas(self) -> list[dict]:
        schemas = []
        try:
            cursor = self.connection.cursor()
            tables = cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ).fetchall()

            for (table_name,) in tables:
                info = cursor.execute(
                    f"PRAGMA table_info({self.quote_identifier(table_name)})"
                ).fetchall()
                columns = [row[1] for row in info]
                if not columns:
                    continue

                rows = cursor.execute(
                    f"SELECT * FROM {self.quote_identifier(table_name)}"
                ).fetchall()
                if len(rows) < QUIZ_OPTION_COUNT:
                    continue

                schemas.append(
                    {
                        "table": table_name,
                        "columns": columns,
                        "primary_keys": {
                            row[1] for row in info if row[5]
                        },
                        "records": [
                            dict(zip(columns, row)) for row in rows
                        ],
                    }
                )
        except sqlite3.Error:
            return []

        return schemas

    def make_question(self, schemas: list[dict]) -> dict | None:
        schema = random.choice(schemas)
        records = schema["records"]
        answer_columns = []

        for column in schema["columns"]:
            if (
                column in schema["primary_keys"]
                or column in QUIZ_EXCLUDED_ANSWER_COLUMNS
            ):
                continue
            values = [
                value
                for record in records
                if (value := self.answer_text(record.get(column)))
            ]
            if len(set(values)) < QUIZ_OPTION_COUNT:
                continue
            if max(len(value) for value in values) > QUIZ_MAX_ANSWER_LENGTH:
                continue
            answer_columns.append(column)

        if not answer_columns:
            return None

        answer_column = random.choice(answer_columns)
        rows_with_answer = [
            record
            for record in records
            if self.answer_text(record.get(answer_column))
        ]
        target = random.choice(rows_with_answer)
        correct = self.answer_text(target.get(answer_column))

        all_answers = list(
            dict.fromkeys(
                value
                for record in records
                if (value := self.answer_text(record.get(answer_column)))
            )
        )
        distractors = [value for value in all_answers if value != correct]
        if len(distractors) < QUIZ_OPTION_COUNT - 1:
            return None

        clue_candidates = []
        for column in schema["columns"]:
            if column == answer_column or column in schema["primary_keys"]:
                continue
            value = self.cell_text(target.get(column))
            clue = self.clue_text(value)
            if not clue or self.values_overlap(clue, correct):
                continue
            clue_candidates.append((column, clue))

        if not clue_candidates:
            return None

        rich_clues = [
            candidate
            for candidate in clue_candidates
            if len(candidate[1]) >= QUIZ_RICH_CLUE_LENGTH
        ]
        if rich_clues:
            selected = [random.choice(rich_clues)]
            remaining = [
                candidate
                for candidate in clue_candidates
                if candidate[0] != selected[0][0]
            ]
            max_extra = min(QUIZ_CLUE_COLUMNS_MAX - 1, len(remaining))
            extra_count = (
                random.randint(1, max_extra) if max_extra else 0
            )
            selected.extend(random.sample(remaining, extra_count))
        else:
            min_count = min(QUIZ_CLUE_COLUMNS_MIN, len(clue_candidates))
            max_count = min(QUIZ_CLUE_COLUMNS_MAX, len(clue_candidates))
            selected = random.sample(
                clue_candidates,
                random.randint(min_count, max_count),
            )

        clue_columns = sorted(
            (column for column, _ in selected),
            key=schema["columns"].index,
        )

        question_text = self.build_question_text(
            answer_column, clue_columns, target
        )
        visible_text = self.plain_text(question_text).casefold()
        if correct.casefold() in visible_text:
            return None

        suitable = [
            value for value in distractors if value.casefold() not in visible_text
        ]
        if len(suitable) < QUIZ_OPTION_COUNT - 1:
            suitable = distractors

        options = [correct]
        options.extend(random.sample(suitable, QUIZ_OPTION_COUNT - 1))
        random.shuffle(options)
        return {
            "table": schema["table"],
            "answer_column": answer_column,
            "text": question_text,
            "options": options,
            "correct": correct,
        }

    def build_question_text(
        self,
        answer_column: str,
        clue_columns: list[str],
        record: dict,
    ) -> str:
        facts = [
            f"<li>{html.escape(self.clue_text(record.get(column)))}</li>"
            for column in clue_columns
        ]
        template = QUIZ_COLUMN_TEMPLATES.get(
            answer_column, "Определите правильное значение."
        )
        return (
            f"<p><b>{html.escape(template)}</b></p>"
            f"<ul>{''.join(facts)}</ul>"
        )

    @staticmethod
    def quote_identifier(name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    @staticmethod
    def cell_text(value) -> str:
        return "" if value is None else str(value).strip()

    def answer_text(self, value) -> str:
        return self.format_date(self.cell_text(value))

    @staticmethod
    def plain_text(value) -> str:
        if value is None:
            return ""
        text = html.unescape(re.sub(r"<[^>]+>", " ", str(value)))
        return re.sub(r"\s+", " ", text).strip()

    def clue_text(self, value) -> str:
        text = self.plain_text(value)
        if not text:
            return ""

        sentences = re.split(r"(?<=[.!?])\s+", text)
        text = " ".join(sentences[:2]).strip()
        if len(text) > QUIZ_MAX_CLUE_LENGTH:
            text = text[:QUIZ_MAX_CLUE_LENGTH].rsplit(" ", 1)[0]
            text = text.rstrip(" ,;:") + "…"
        return self.format_date(text)

    @staticmethod
    def values_overlap(first: str, second: str) -> bool:
        first_value = first.casefold().strip()
        second_value = second.casefold().strip()
        return bool(
            first_value
            and second_value
            and (
                first_value in second_value
                or second_value in first_value
            )
        )

    @staticmethod
    def format_date(value) -> str:
        text = "" if value is None else str(value).strip()
        match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
        if match:
            year, month, day = match.groups()
            return f"{day}.{month}.{year}"
        return text

    def clear_options(self) -> None:
        for button in self.option_group.buttons():
            self.option_group.removeButton(button)
        while self.options_layout.count():
            item = self.options_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def show_question(self) -> None:
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
            button.setStyleSheet("font-size: 14px; padding: 2px 0;")
            self.option_group.addButton(button)
            self.options_layout.addWidget(button)

        self.feedback_label.clear()
        self.feedback_label.setStyleSheet("")
        self.answer_button.show()
        self.answer_button.setEnabled(True)
        self.next_button.setText("Показать результат")
        self.next_button.hide()

    def check_answer(self) -> None:
        if self.answered:
            return

        checked = self.option_group.checkedButton()
        if checked is None:
            self.feedback_label.setText("Сначала выберите вариант ответа.")
            self.feedback_label.setStyleSheet("color: #8a6d3b;")
            return

        question = self.questions[self.current_index]
        correct = question["correct"]
        selected = checked.text()
        self.answered = True

        if selected == correct:
            self.score += 1
            self.feedback_label.setText("Верно!")
            self.feedback_label.setStyleSheet(
                "color: #1b7f3b; font-weight: bold;"
            )
        else:
            self.feedback_label.setText(f"Неверно. Правильный ответ: {correct}")
            self.feedback_label.setStyleSheet(
                "color: #b3261e; font-weight: bold;"
            )

        for button in self.option_group.buttons():
            button.setEnabled(False)
            if button.text() == correct:
                button.setStyleSheet(
                    "font-size: 14px; padding: 2px 0;"
                    " color: #1b7f3b; font-weight: bold;"
                )
            elif button is checked:
                button.setStyleSheet(
                    "font-size: 14px; padding: 2px 0; color: #b3261e;"
                )

        self.answer_button.hide()
        self.next_button.setText(
            "Показать результат"
            if self.current_index == len(self.questions) - 1
            else "Следующий вопрос"
        )
        self.next_button.show()

    def go_next(self) -> None:
        if self.current_index + 1 >= len(self.questions):
            self.show_result()
            return

        self.current_index += 1
        self.show_question()

    def show_result(self) -> None:
        total = len(self.questions)
        self.progress_label.setText(f"Результат: {self.score} из {total}")
        self.question_label.setText(
            "<h2>Тест завершён</h2>"
            f"<p>Правильных ответов: <b>{self.score} из {total}</b></p>"
            "<p>Нажмите «Начать заново», чтобы пройти тест ещё раз.</p>"
        )
        self.options_widget.hide()
        self.feedback_label.hide()
        self.answer_button.hide()
        self.next_button.hide()
        self.restart_button.show()


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
