# src/tools/ts_forecast.py
from typing import Dict, Any, Tuple
from pathlib import Path
import pandas as pd
import numpy as np
from statsmodels.tsa.arima.model import ARIMA

from ..sandbox import must_be_allowed
from ..config import TIMEOUT_SECONDS

tool_spec = {
    "name": "ts_forecast",
    "description": "Pronóstico ARIMA básico para una columna numérica.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "column": {"type": "string"},
            "horizon": {"type": "integer"},
            "date_col": {"type": "string"},          # opcional: columna de fechas (p. ej., 'fecha')
            "freq": {"type": "string"},              # opcional: 'D','W','M', etc.
            "order": {                               # opcional: [p,d,q]
                "type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3
            }
        },
        "required": ["path", "column", "horizon"]
    },
    "output_schema": {"type": "object"}
}

def _read_df(p: Path) -> pd.DataFrame:
    suf = p.suffix.lower()
    if suf == ".csv":
        return pd.read_csv(p)
    if suf in (".xlsx", ".xls"):
        return pd.read_excel(p)
    if suf == ".parquet":
        return pd.read_parquet(p)
    raise ValueError(f"Formato no soportado: {suf}. Usa CSV, Excel o Parquet.")

def _prepare_series(df: pd.DataFrame, column: str, date_col: str | None, freq: str | None) -> Tuple[pd.Series, str]:
    if date_col and date_col in df.columns:
        # parseo suave de fechas
        try:
            idx = pd.to_datetime(df[date_col])
        except Exception:
            raise ValueError(f"No se pudo parsear la columna de fechas: {date_col}")
        s = pd.Series(df[column].astype(float).values, index=idx).sort_index()
        if freq:
            s = s.asfreq(freq, method="ffill")  # relleno hacia adelante si faltan puntos
        index_type = "datetime"
    else:
        s = pd.Series(df[column].astype(float).values)
        index_type = "integer"
    s = s.dropna()
    return s, index_type

def _fit_arima(y: pd.Series, order: Tuple[int,int,int]) -> ARIMA:
    # Parámetros lazos para evitar errores por invertibilidad/estacionariedad
    return ARIMA(y, order=order, enforce_stationarity=False, enforce_invertibility=False)

def run(args: Dict[str, Any]) -> Dict[str, Any]:
    p = must_be_allowed(args["path"])
    if not p.exists():
        raise FileNotFoundError(f"No existe el archivo: {p}")

    column: str = args["column"]
    horizon: int = int(args["horizon"])
    date_col: str | None = args.get("date_col")
    freq: str | None = args.get("freq")
    order = args.get("order") or [1, 1, 1]
    if len(order) != 3:
        raise ValueError("order debe ser una lista de tres enteros [p,d,q].")
    order = tuple(int(x) for x in order)

    df = _read_df(p)
    if column not in df.columns:
        raise ValueError(f"Columna '{column}' no está en el archivo.")

    y, index_type = _prepare_series(df, column, date_col, freq)
    if len(y) < 8:
        # Serie demasiado corta: pronóstico ingenuo
        last = float(y.iloc[-1]) if len(y) else 0.0
        forecast = [last] * horizon
        lo = [last] * horizon
        hi = [last] * horizon
        # construir índice futuro
        if index_type == "datetime" and isinstance(y.index, pd.DatetimeIndex):
            step = (y.index[1] - y.index[0]) if len(y.index) > 1 else pd.Timedelta(days=1)
            future_index = [ (y.index[-1] + step*(i+1)).isoformat() for i in range(horizon) ]
        else:
            future_index = [ int(len(y) + i) for i in range(1, horizon+1) ]
        series = [{"t": future_index[i], "yhat": float(forecast[i]), "lo": float(lo[i]), "hi": float(hi[i])}
                  for i in range(horizon)]
        return {
            "model": {"type": "naive", "order": None, "aic": None},
            "forecast": series,
            "meta": {"path": str(p), "column": column, "rows_used": int(len(y)), "index_type": index_type,
                     "timeout_seconds": TIMEOUT_SECONDS}
        }

    # Intentamos (p,d,q) solicitado; si falla, probamos algunos fallbacks razonables
    tried = []
    candidates = [tuple(order), (0, 1, 1), (1, 0, 0)]
    last_err = None
    res = None
    used_order = None
    for cand in candidates:
        if cand in tried:  # evitar repetidos
            continue
        tried.append(cand)
        try:
            model = _fit_arima(y, cand)
            res = model.fit(method_kwargs={"warn_convergence": False})
            used_order = cand
            break
        except Exception as e:
            last_err = e
            continue

    if res is None:
        raise RuntimeError(f"No se pudo ajustar ARIMA. Último error: {last_err}")

    fc = res.get_forecast(steps=horizon)
    mean = fc.predicted_mean.to_numpy().astype(float).tolist()
    ci = fc.conf_int(alpha=0.05)  # 95%
    lo = ci.iloc[:, 0].to_numpy().astype(float).tolist()
    hi = ci.iloc[:, 1].to_numpy().astype(float).tolist()

    # Índice futuro (JSON-safe)
    if index_type == "datetime" and isinstance(y.index, pd.DatetimeIndex):
        step = (y.index[1] - y.index[0]) if len(y.index) > 1 else pd.Timedelta(days=1)
        future_index = [ (y.index[-1] + step*(i+1)).isoformat() for i in range(horizon) ]
    else:
        future_index = [ int(len(y) + i) for i in range(1, horizon+1) ]

    series = [{"t": future_index[i], "yhat": float(mean[i]), "lo": float(lo[i]), "hi": float(hi[i])}
              for i in range(horizon)]

    return {
        "model": {"type": "ARIMA", "order": list(used_order), "aic": float(getattr(res, "aic", np.nan))},
        "forecast": series,
        "meta": {"path": str(p), "column": column, "rows_used": int(len(y)), "index_type": index_type,
                 "timeout_seconds": TIMEOUT_SECONDS}
    }
