# Notebooks

Cuadernos exploratorios del proyecto. **No son código de producción**: no se
importan desde la app, no tienen gates y pueden quedar desactualizados respecto
al esquema de `data/lifestyle.db` (regenerable con las migraciones de
`src/migrations/`).

| Cuaderno | Propósito |
|---|---|
| `db_explorer.ipynb` | Exploración ad-hoc de la base (tablas, datos, pruebas de análisis). |

Para reproducirlos: entorno del proyecto (`.venv`) con `uv sync --locked` y un
kernel con el mismo intérprete.
