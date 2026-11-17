import csv
import json
import sqlite3
import tkinter as tk
from collections import Counter
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk


BASE_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = BASE_DIR / "settings.json"
LANGUAGES = ("ENG", "HU")


def read_po(path):
    """A fordítási adatokat közvetlenül .po fájlból olvassa."""
    translations = {}
    msgid = None
    msgstr = None
    field = None

    def unquote(value):
        try:
            return json.loads(value.strip())
        except (json.JSONDecodeError, TypeError):
            return ""

    def save_entry():
        if msgid and msgstr is not None:
            translations[msgid] = msgstr

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return translations

    for line in lines + [""]:
        line = line.strip()

        if not line or line.startswith("#"):
            if not line:
                save_entry()
                msgid = msgstr = field = None
            continue

        if line.startswith("msgid "):
            msgid = unquote(line[6:])
            field = "msgid"
        elif line.startswith("msgstr "):
            msgstr = unquote(line[7:])
            field = "msgstr"
        elif line.startswith('"'):
            part = unquote(line)
            if field == "msgid":
                msgid = (msgid or "") + part
            elif field == "msgstr":
                msgstr = (msgstr or "") + part

    return translations


def read_language():
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        lang = data.get("language", "ENG")
        return lang if lang in LANGUAGES else "ENG"
    except (OSError, json.JSONDecodeError, AttributeError):
        return "ENG"


def save_language(language):
    SETTINGS_PATH.write_text(
        json.dumps({"language": language}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class Translator:
    def __init__(self, language):
        self.set_language(language)

    def set_language(self, language):
        self.language = language if language in LANGUAGES else "ENG"
        self.texts = read_po(BASE_DIR / f"{self.language}.po")

    def __call__(self, message_id):
        return self.texts.get(message_id, message_id)


class DataViewer:
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}

    def __init__(self, root):
        self.root = root
        self.language = read_language()
        self.t = Translator(self.language)

        self.headers = []
        self.rows = []
        self.locked = set()
        self.file_path = None
        self.page = 0
        self.page_size = 25

        self.root.geometry("1180x720")
        self.root.minsize(780, 480)
        self.build_ui()
        #.show_welcome()

    def build_ui(self):
        self.root.title(self.t("Gomba Data Viewer"))

        self.toolbar = ttk.Frame(self.root, padding=8)
        self.toolbar.pack(fill="x")

        self.buttons = {}
        button_specs = [
            ("Load", self.load_file),
            ("Settings", self.open_settings),
            ("Statistics", self.open_statistics),
            ("Chart", self.open_chart),
            ("Save CSV", self.save_csv),
            ("Save As...", self.save_as),
            ("Export JSON", self.export_json),
            ("Save to SQLite", self.export_sqlite),
            ("Exit", self.root.destroy),
        ]
        for key, command in button_specs:
            button = ttk.Button(self.toolbar, text=self.t(key), command=command)
            self.buttons[key] = button
            button.pack(side="left", padx=2)

        self.search_label = ttk.Label(self.toolbar, text=self.t("Search:"))
        self.search_label.pack(side="left", padx=(10, 3))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(self.toolbar, textvariable=self.search_var, width=16)
        self.search_entry.pack(side="left")
        self.search_entry.bind("<Return>", lambda _event: self.search())
        self.search_button = ttk.Button(
            self.toolbar, text="🔍", width=3, command=self.search
        )
        self.search_button.pack(side="left", padx=2)

        self.page_size_label = ttk.Label(
            self.toolbar, text=self.t("Rows per page:")
        )
        self.page_size_label.pack(side="left", padx=(8, 3))
        self.page_size_var = tk.StringVar(value="25")
        self.page_size_combo = ttk.Combobox(
            self.toolbar,
            textvariable=self.page_size_var,
            values=("25", "50", "100"),
            width=5,
            state="readonly",
        )
        self.page_size_combo.pack(side="left")
        self.page_size_combo.bind(
            "<<ComboboxSelected>>", self.change_page_size
        )

        self.file_label = ttk.Label(
            self.root, text=self.t("No data loaded."), padding=(10, 0, 10, 6)
        )
        self.file_label.pack(anchor="w")

        table_frame = ttk.Frame(self.root, padding=(8, 0, 8, 4))
        table_frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(table_frame, show="headings")
        yscroll = ttk.Scrollbar(
            table_frame, orient="vertical", command=self.tree.yview
        )
        xscroll = ttk.Scrollbar(
            table_frame, orient="horizontal", command=self.tree.xview
        )
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self.edit_cell)

        footer = ttk.Frame(self.root, padding=8)
        footer.pack(fill="x")
        self.count_label = ttk.Label(footer, text="")
        self.count_label.pack(side="left")
        self.previous_button = ttk.Button(
            footer, text=self.t("Previous"), command=self.previous_page
        )
        self.previous_button.pack(side="right", padx=3)
        self.page_label = ttk.Label(footer, text="")
        self.page_label.pack(side="right", padx=8)
        self.next_button = ttk.Button(
            footer, text=self.t("Next"), command=self.next_page
        )
        self.next_button.pack(side="right", padx=3)

    def load_file(self):
        path = filedialog.askopenfilename(
            title=self.t("Load"),
            filetypes=[
                ("CSV and JSON", "*.csv *.json"),
                ("CSV files", "*.csv"),
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        try:
            suffix = Path(path).suffix.lower()
            if suffix == ".csv":
                with open(path, encoding="utf-8-sig", newline="") as f:
                    sample = f.read(4096)
                    f.seek(0)
                    try:
                        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                    except csv.Error:
                        dialect = csv.excel
                    data = list(csv.reader(f, dialect))

                if not data:
                    raise ValueError("The file is empty.")
                self.headers = [str(value) for value in data[0]]
                self.rows = [
                    [row[i] if i < len(row) else "" for i in range(len(self.headers))]
                    for row in data[1:]
                ]

            elif suffix == ".json":
                with open(path, encoding="utf-8-sig") as f:
                    data = json.load(f)

                if isinstance(data, dict):
                    data = [data]
                if not isinstance(data, list):
                    raise ValueError("The JSON root must be an object or a list.")

                if not data:
                    self.headers, self.rows = [], []
                elif all(isinstance(item, dict) for item in data):
                    self.headers = list(dict.fromkeys(
                        key for item in data for key in item.keys()
                    ))
                    self.rows = [
                        [self.to_text(item.get(key, "")) for key in self.headers]
                        for item in data
                    ]
                elif all(isinstance(item, list) for item in data):
                    self.headers = [str(value) for value in data[0]]
                    self.rows = [
                        [self.to_text(value) for value in row]
                        for row in data[1:]
                    ]
                else:
                    raise ValueError(
                        "JSON list items must all be objects or all be lists."
                    )
            else:
                raise ValueError("Choose a CSV or JSON file.")

            self.file_path = path
            self.locked.clear()
            self.page = 0
            self.file_label.config(text=Path(path).name)

            #if self.welcome.winfo_exists():
            #    self.welcome.destroy()

            self.render()

        except (OSError, UnicodeError, csv.Error, json.JSONDecodeError, ValueError) as e:
            messagebox.showerror(self.t("Error"), f"{self.t('Could not load file:')} {e}")

    @staticmethod
    def to_text(value):
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def filtered_rows(self):
        term = self.search_var.get().strip().casefold()
        if not term:
            return list(enumerate(self.rows))
        return [
            (i, row) for i, row in enumerate(self.rows)
            if any(term in self.to_text(value).casefold() for value in row)
        ]

    def render(self):
        self.tree.delete(*self.tree.get_children())
        column_ids = [f"c{i}" for i in range(len(self.headers))]
        self.tree["columns"] = column_ids

        for i, (column_id, header) in enumerate(zip(column_ids, self.headers)):
            label = f"🔒 {header}" if i in self.locked else header
            self.tree.heading(column_id, text=label)
            self.tree.column(column_id, width=150, minwidth=60, stretch=True)

        matches = self.filtered_rows()
        pages = max(1, (len(matches) + self.page_size - 1) // self.page_size)
        self.page = min(self.page, pages - 1)
        first = self.page * self.page_size

        for _, row in matches[first:first + self.page_size]:
            self.tree.insert(
                "", "end",
                values=[row[i] if i < len(row) else "" for i in range(len(self.headers))],
            )

        self.page_label.config(text=f"{self.page + 1} / {pages}")
        self.count_label.config(
            text=f"{len(matches)} {self.t('results')} / {len(self.rows)} {self.t('Rows')}"
        )

    def search(self):
        self.page = 0
        self.render()

    def change_page_size(self, _event=None):
        self.page_size = int(self.page_size_var.get())
        self.page = 0
        self.render()

    def previous_page(self):
        self.page = max(0, self.page - 1)
        self.render()

    def next_page(self):
        self.page += 1
        self.render()

    def edit_cell(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        item = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not item or not column:
            return

        col_index = int(column[1:]) - 1
        if col_index in self.locked:
            return

        visible_index = self.tree.index(item)
        matches = self.filtered_rows()
        absolute_index = matches[self.page * self.page_size + visible_index][0]

        x, y, width, height = self.tree.bbox(item, column)
        editor = ttk.Entry(self.tree)
        editor.insert(0, self.rows[absolute_index][col_index])
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus()

        def save(_event=None):
            if editor.winfo_exists():
                self.rows[absolute_index][col_index] = editor.get()
                editor.destroy()
                self.render()

        editor.bind("<Return>", save)
        editor.bind("<FocusOut>", save)
        editor.bind("<Escape>", lambda _event: editor.destroy())

    def open_settings(self):
        win = tk.Toplevel(self.root)
        win.title(self.t("Settings"))
        win.geometry("510x480")
        win.transient(self.root)

        ttk.Label(win, text=self.t("Choose language:")).pack(
            anchor="w", padx=10, pady=(12, 4)
        )
        language_var = tk.StringVar(
            value="English" if self.language == "ENG" else "Hungarian"
        )
        language_box = ttk.Combobox(
            win,
            textvariable=language_var,
            values=("English", "Hungarian"),
            state="readonly",
        )
        language_box.pack(fill="x", padx=10)

        def change_language(_event=None):
            language = "ENG" if language_var.get() == "English" else "HU"
            try:
                save_language(language)
                messagebox.showinfo(
                    self.t("Settings"),
                    self.t("Language saved. Restart the application to apply it everywhere."),
                    parent=win,
                )
            except OSError as e:
                messagebox.showerror(self.t("Error"), str(e), parent=win)

        language_box.bind("<<ComboboxSelected>>", change_language)

        ttk.Label(win, text=self.t("Column settings")).pack(
            anchor="w", padx=10, pady=(14, 4)
        )
        columns = tk.Listbox(win, exportselection=False, height=12)
        columns.pack(fill="both", expand=True, padx=10, pady=4)

        def refresh_columns():
            columns.delete(0, "end")
            for i, name in enumerate(self.headers):
                prefix = "🔒 " if i in self.locked else ""
                columns.insert("end", prefix + name)

        def add_column(name):
            name = name.strip()
            if not name:
                return
            if name in self.headers:
                messagebox.showwarning(
                    self.t("Settings"), self.t("Column already exists."), parent=win
                )
                return
            self.headers.append(name)
            for row in self.rows:
                row.append("")
            refresh_columns()
            self.render()

        def add_image_column():
            folder = filedialog.askdirectory(parent=win)
            if not folder:
                return

            name = simpledialog.askstring(
                self.t("Add image URL column"),
                self.t("Column name:"),
                initialvalue="Image URL",
                parent=win,
            )
            if not name or not name.strip():
                return

            images = sorted(
                path for path in Path(folder).iterdir()
                if path.is_file() and path.suffix.lower() in self.IMAGE_EXTENSIONS
            )
            if not images:
                messagebox.showinfo(
                    self.t("Settings"),
                    self.t("The selected folder contains no supported image files."),
                    parent=win,
                )
                return

            add_column(name)
            image_col = len(self.headers) - 1
            by_stem = {image.stem.casefold(): image.resolve().as_uri() for image in images}

            for row_index, row in enumerate(self.rows):
                found = None
                for value in row[:image_col]:
                    key = Path(str(value)).stem.casefold()
                    if key in by_stem:
                        found = by_stem[key]
                        break
                if found is None and row_index < len(images):
                    found = images[row_index].resolve().as_uri()
                row[image_col] = found or ""

            self.render()

        def selected_column():
            selected = columns.curselection()
            return selected[0] if selected else None

        def rename_column():
            index = selected_column()
            if index is None:
                return
            new_name = simpledialog.askstring(
                self.t("Rename"),
                self.t("New column name:"),
                initialvalue=self.headers[index],
                parent=win,
            )
            if new_name and new_name.strip():
                self.headers[index] = new_name.strip()
                refresh_columns()
                self.render()

        def toggle_lock():
            index = selected_column()
            if index is None:
                return
            if index in self.locked:
                self.locked.remove(index)
            else:
                self.locked.add(index)
            refresh_columns()
            self.render()

        buttons = ttk.Frame(win, padding=6)
        buttons.pack(fill="x")
        ttk.Button(
            buttons, text=self.t("Add column"),
            command=lambda: add_column(
                simpledialog.askstring(self.t("Add column"), self.t("Column name:"), parent=win) or ""
            ),
        ).pack(side="left", padx=2)
        ttk.Button(
            buttons, text=self.t("Add image URL column"), command=add_image_column
        ).pack(side="left", padx=2)
        ttk.Button(buttons, text=self.t("Rename"), command=rename_column).pack(side="left", padx=2)
        ttk.Button(
            buttons, text=self.t("Lock / unlock"), command=toggle_lock
        ).pack(side="left", padx=2)

        refresh_columns()

    def open_statistics(self):
        if not self.headers:
            messagebox.showinfo(self.t("Statistics"), self.t("No data loaded."))
            return

        win = tk.Toplevel(self.root)
        win.title(self.t("Statistics"))
        win.geometry("500x450")

        column_var = tk.StringVar(value=self.headers[0])
        selector = ttk.Combobox(
            win, textvariable=column_var, values=self.headers, state="readonly"
        )
        selector.pack(fill="x", padx=10, pady=10)
        output = tk.Text(win, wrap="none")
        output.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        def update(_event=None):
            index = self.headers.index(column_var.get())
            values = [
                row[index].strip() for row in self.rows
                if index < len(row) and row[index].strip()
            ]
            counts = Counter(values)
            output.delete("1.0", "end")
            output.insert("end", f"{self.t('Non-empty values')}: {len(values)}\n")
            output.insert("end", f"{self.t('Unique values')}: {len(counts)}\n\n")
            output.insert("end", f"{self.t('Value')} — {self.t('Count')}\n")
            for value, count in counts.most_common():
                output.insert("end", f"{value} — {count}\n")

        selector.bind("<<ComboboxSelected>>", update)
        update()

    def open_chart(self):
        if not self.headers:
            messagebox.showinfo(self.t("Chart"), self.t("No data loaded."))
            return

        win = tk.Toplevel(self.root)
        win.title(self.t("Chart"))
        win.geometry("720x500")

        column_var = tk.StringVar(value=self.headers[0])
        selector = ttk.Combobox(
            win, textvariable=column_var, values=self.headers, state="readonly"
        )
        selector.pack(fill="x", padx=10, pady=10)
        canvas = tk.Canvas(win, bg="white")
        canvas.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        def draw(_event=None):
            canvas.delete("all")
            index = self.headers.index(column_var.get())
            values = [
                row[index].strip() for row in self.rows
                if index < len(row) and row[index].strip()
            ]
            items = Counter(values).most_common(15)
            if not items:
                canvas.create_text(300, 200, text=self.t("No chart data."))
                return

            width = max(canvas.winfo_width(), 500)
            height = max(canvas.winfo_height(), 350)
            left, right, top, bottom = 55, width - 20, 25, height - 75
            max_value = max(count for _, count in items)
            step = (right - left) / len(items)
            bar_width = max(8, step * 0.65)

            canvas.create_line(left, top, left, bottom, fill="#555")
            canvas.create_line(left, bottom, right, bottom, fill="#555")

            for i, (label, count) in enumerate(items):
                x0 = left + i * step + (step - bar_width) / 2
                x1 = x0 + bar_width
                y1 = bottom - count / max_value * (bottom - top)
                canvas.create_rectangle(x0, y1, x1, bottom, fill="#4d9b73", outline="")
                canvas.create_text((x0 + x1) / 2, y1 - 10, text=str(count))
                display_label = label if len(label) <= 12 else label[:11] + "…"
                canvas.create_text((x0 + x1) / 2, bottom + 20, text=display_label)

        selector.bind("<<ComboboxSelected>>", draw)
        win.after(100, draw)

    def write_csv(self, path):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(self.headers)
            writer.writerows(self.rows)

    def save_csv(self):
        if not self.file_path or Path(self.file_path).suffix.lower() != ".csv":
            self.save_as()
            return
        try:
            self.write_csv(self.file_path)
            messagebox.showinfo(self.t("Save CSV"), self.t("Settings saved."))
        except OSError as e:
            messagebox.showerror(self.t("Error"), f"{self.t('Could not save file:')} {e}")

    def save_as(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not path:
            return
        try:
            self.write_csv(path)
            self.file_path = path
            self.file_label.config(text=Path(path).name)
            messagebox.showinfo(self.t("Save As..."), self.t("Settings saved."))
        except OSError as e:
            messagebox.showerror(self.t("Error"), f"{self.t('Could not save file:')} {e}")

    def export_json(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
        )
        if not path:
            return
        try:
            records = [
                {
                    header: row[i] if i < len(row) else ""
                    for i, header in enumerate(self.headers)
                }
                for row in self.rows
            ]
            Path(path).write_text(
                json.dumps(records, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            messagebox.showinfo(self.t("Export JSON"), self.t("Export complete."))
        except OSError as e:
            messagebox.showerror(self.t("Error"), f"{self.t('Could not save file:')} {e}")

    def export_sqlite(self):
        if not self.headers:
            messagebox.showinfo(self.t("Save to SQLite"), self.t("No data loaded."))
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".sqlite",
            filetypes=[("SQLite database", "*.sqlite *.db")],
        )
        if not path:
            return

        table_name = simpledialog.askstring(
            self.t("Save to SQLite"),
            self.t("SQLite table name:"),
            initialvalue="data",
            parent=self.root,
        )
        if not table_name:
            return

        quote = lambda value: '"' + str(value).replace('"', '""') + '"'
        try:
            columns = ", ".join(f"{quote(name)} TEXT" for name in self.headers)
            with sqlite3.connect(path) as db:
                db.execute(f"DROP TABLE IF EXISTS {quote(table_name)}")
                db.execute(f"CREATE TABLE {quote(table_name)} ({columns})")
                if self.rows:
                    marks = ", ".join("?" for _ in self.headers)
                    values = [
                        tuple(row[i] if i < len(row) else "" for i in range(len(self.headers)))
                        for row in self.rows
                    ]
                    db.executemany(
                        f"INSERT INTO {quote(table_name)} VALUES ({marks})", values
                    )
            messagebox.showinfo(self.t("Save to SQLite"), self.t("Export complete."))
        except (OSError, sqlite3.Error) as e:
            messagebox.showerror(self.t("Error"), f"{self.t('Could not save file:')} {e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = DataViewer(root)
    root.mainloop()
