# src/tools/data_profile.py
from typing import Dict, Any
from pathlib import Path
import warnings
import pandas as pd
from pandas.api.types import is_datetime64_any_dtype

from ..sandbox import must_be_allowed
from ..config import TIMEOUT_SECONDS


tool_spec = {
    "name": "data_profile",
    "description": "Perfilado de CSV/Excel/Parquet: describe, nulos, tipos, datetime y vista previa.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "sep": {"type": "string"},               # para CSV (opcional)
            "sheet": {"type": "string"},             # para Excel (opcional)
            "limit_rows": {"type": "integer"},       # límite de filas a leer (por defecto 100k)
            "columns": {"type": "array", "items": {"type": "string"}},
            "encoding": {"type": "string"}           # encoding CSV; default utf-8
        },
        "required": ["path"]
    },
    "output_schema": {"type": "object"}
}


def _read_df(p: Path, sep: str | None, sheet: str | None,
             limit_rows: int | None, encoding: str | None) -> pd.DataFrame:
    """Carga dataframe de forma robusta según la extensión."""
    suf = p.suffix.lower()
    if suf == ".csv":
        return pd.read_csv(
            p, sep=sep or ",", nrows=limit_rows,
            encoding=encoding or "utf-8", on_bad_lines="skip"
        )
    if suf in (".xlsx", ".xls"):
        try:
            return pd.read_excel(p, sheet_name=sheet or 0, nrows=limit_rows)
        except ImportError as e:
            raise ImportError("Falta 'openpyxl' para leer Excel: pip install openpyxl") from e
    if suf == ".parquet":
        try:
            df = pd.read_parquet(p)
            return df if not limit_rows else df.head(limit_rows)
        except Exception as e:
            raise RuntimeError("Para Parquet se recomienda 'pyarrow' instalado") from e
    raise ValueError(f"Formato no soportado: {suf}. Usa CSV, Excel o Parquet.")


def run(args: Dict[str, Any]) -> Dict[str, Any]:
    # Validación de ruta y parámetros
    p = must_be_allowed(args["path"])
    if not p.exists():
        raise FileNotFoundError(f"No existe el archivo: {p}")

    sep = args.get("sep")
    sheet = args.get("sheet")
    limit_rows = int(args.get("limit_rows") or 100_000)
    columns = args.get("columns")
    encoding = args.get("encoding")

    # Lectura protegida
    try:
        df = _read_df(p, sep, sheet, limit_rows, encoding)
    except Exception as e:
        raise RuntimeError(f"No se pudo leer el archivo: {e}") from e

    # Intento de parseo de fechas SIN argumentos deprecados.
    # Silenciamos warnings de inferencia y si no se puede, no convertimos.
    for c in df.columns:
        if df[c].dtype == "object":
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=UserWarning)
                    parsed = pd.to_datetime(df[c])  # lanza excepción si no aplica
                # Si se pudo convertir, usamos la columna convertida
                df[c] = parsed
            except Exception:
                pass

    # Filtrado opcional de columnas
    if columns:
        miss = [c for c in columns if c not in df.columns]
        if miss:
            raise ValueError(f"Columnas no encontradas: {miss}")
        df = df[columns]

    # --- Perfilado ---
    memory_bytes = int(df.memory_usage(deep=True).sum())
    dtypes = {c: str(t) for c, t in df.dtypes.items()}
    nulls = df.isna().sum().to_dict()

    # Describe numérico
    num_df = df.select_dtypes(include="number")
    describe_numeric = {} if num_df.empty else num_df.describe().transpose().to_dict(orient="index")

    # Describe datetime (portátil)
    dt_cols = [c for c in df.columns if is_datetime64_any_dtype(df[c])]
    describe_datetime = {
        c: {
            "count": int(df[c].notna().sum()),
            "min": (df[c].min().isoformat() if pd.notna(df[c].min()) else None),
            "max": (df[c].max().isoformat() if pd.notna(df[c].max()) else None),
        }
        for c in dt_cols
    }

    # Describe objetos/categorías
    obj_df = df.select_dtypes(include=["object", "category"])
    try:
        describe_non_numeric = {} if obj_df.empty else obj_df.describe().transpose().to_dict(orient="index")
    except Exception:
        describe_non_numeric = {}

    # Vista previa JSON-safe (convertimos datetimes a string)
    prev = df.head(5).copy()
    for c in dt_cols:
        prev[c] = prev[c].astype(str)
    preview = prev.to_dict(orient="records")

    return {
        "meta": {
            "path": str(p),
            "rows": int(df.shape[0]),
            "cols": int(df.shape[1]),
            "memory_bytes": memory_bytes,
            "timeout_seconds": TIMEOUT_SECONDS,
        },
        "schema": dtypes,
        "nulls": nulls,
        "describe_numeric": describe_numeric,
        "describe_datetime": describe_datetime,
        "describe_non_numeric": describe_non_numeric,
        "preview": preview,
    }
