"""Local storage for field-specific rotation inputs."""
from contextlib import closing
from pathlib import Path
import sqlite3
import streamlit as st

DATABASE = Path(__file__).resolve().parents[1] / "data/local/field_profiles.sqlite3"


def fields():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DATABASE)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS fields (id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS inputs (field_id INTEGER, setting TEXT, value TEXT, PRIMARY KEY(field_id, setting))")
        db.execute("INSERT OR IGNORE INTO fields(id,name) VALUES(1,'Evia pilot')")
        return dict(db.execute("SELECT id,name FROM fields ORDER BY id"))


def inputs(field):
    with closing(sqlite3.connect(DATABASE)) as db:
        return dict(db.execute("SELECT setting,value FROM inputs WHERE field_id=?", (field,)))


def save_widget(field, setting, widget):
    save_input(field, setting, st.session_state[widget])


def save_input(field, setting, value):
    with closing(sqlite3.connect(DATABASE)) as db, db:
        db.execute("INSERT INTO inputs VALUES(?,?,?) ON CONFLICT(field_id,setting) DO UPDATE SET value=excluded.value",
                   (field, setting, value))


def select_field():
    choices = fields()
    with st.sidebar.expander("Add a field"):
        with st.form("new_field", clear_on_submit=True):
            name = st.text_input("Field name", max_chars=100).strip()
            if st.form_submit_button("Create field"):
                if not name:
                    st.error("Enter a field name.")
                else:
                    try:
                        with closing(sqlite3.connect(DATABASE)) as db, db:
                            field = db.execute("INSERT INTO fields(name) VALUES(?)", (name,)).lastrowid
                        st.session_state["selected_field"] = field
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("That field name already exists.")
    return st.sidebar.selectbox("Field", choices.keys(), format_func=choices.get, key="selected_field")
