import sqlite3
import pandas as pd

def init_db(db_path: str) -> None:
    """Crea las tablas en la base de datos SQLite."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        DROP TABLE IF EXISTS training_sets;
        DROP TABLE IF EXISTS ejercicios;
        
        CREATE TABLE ejercicios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grupo_muscular TEXT NOT NULL,
            ejercicio TEXT NOT NULL UNIQUE
        );
        
        CREATE TABLE training_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semana INTEGER NOT NULL,
            dia TEXT NOT NULL,
            fecha TEXT,
            set_orden INTEGER NOT NULL,
            ejercicio TEXT NOT NULL,
            reps REAL,
            kg REAL,
            rir REAL
        );
        
        CREATE INDEX idx_training_semana ON training_sets(semana);
        CREATE INDEX idx_training_ejercicio ON training_sets(ejercicio);
    """)
    conn.commit()
    conn.close()

def load_ejercicios(db_path: str, df: pd.DataFrame) -> None:
    """Carga el catálogo de ejercicios en la tabla 'ejercicios'."""
    conn = sqlite3.connect(db_path)
    for _, row in df.iterrows():
        conn.execute(
            "INSERT OR IGNORE INTO ejercicios (grupo_muscular, ejercicio) VALUES (?, ?)",
            (row["grupo_muscular"], row["ejercicio"]),
        )
    conn.commit()
    conn.close()

def load_training_data(db_path: str, df: pd.DataFrame) -> None:
    """Carga los sets de entrenamiento en la tabla 'training_sets'."""
    conn = sqlite3.connect(db_path)
    # Usar to_sql de pandas es lo más eficiente y limpio
    df.to_sql("training_sets", conn, if_exists="append", index=False)
    conn.commit()
    conn.close()
