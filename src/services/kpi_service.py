"""KPI read models — all parameterized reads for the dashboard KPI tab (plan D1/D3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from src.contracts.kpi_tab import KpiTabQuery
from src.data.access.db import sqlite_connection
from src.data.sidebar_bounds import load_outlet_date_bounds


@dataclass(frozen=True)
class SidebarFilterOptions:
    outlets: list[str]
    min_date: date
    max_date: date


def load_sidebar_filter_options(base_dir: Path) -> SidebarFilterOptions:
    b = load_outlet_date_bounds(base_dir)
    return SidebarFilterOptions(outlets=b.outlets, min_date=b.min_date, max_date=b.max_date)


@dataclass(frozen=True)
class KPITabData:
    kpi: pd.DataFrame
    top5: pd.DataFrame
    by_outlet: pd.DataFrame
    daily: pd.DataFrame
    raw_df: pd.DataFrame


def load_kpi_tab_data(
    base_dir: Path,
    outlets: list[str],
    date_start: str,
    date_end: str,
) -> KPITabData:
    if not outlets:
        empty = pd.DataFrame()
        return KPITabData(empty, empty, empty, empty, empty)
    KpiTabQuery(outlets=outlets, date_start=date_start, date_end=date_end)
    outlet_ph = ",".join("?" * len(outlets))
    params = list(outlets) + [date_start, date_end]

    sql_kpi = f"""
        SELECT IFNULL(ROUND(SUM(NET_AMT),2), 0) AS total_revenue,
               COUNT(DISTINCT INVOICE_NO)           AS total_orders,
               IFNULL(ROUND(SUM(NET_AMT)/NULLIF(COUNT(DISTINCT INVOICE_NO),0),2), 0) AS aov,
               IFNULL(SUM(QTY_PACKS), 0) AS total_packs,
               IFNULL(ROUND(SUM(TOTAL_VOLUME_BILLED_LTR), 0), 0) AS total_volume_ltr
        FROM VIEW_AI_SALES
        WHERE ZONE IN ({outlet_ph}) AND SUBSTR(INVOICE_DATE, 1, 10) BETWEEN ? AND ?
    """
    sql_top5 = f"""
        SELECT PRODUCT AS item_name,
               IFNULL(ROUND(SUM(NET_AMT),2), 0) AS revenue,
               SUM(QTY_PACKS)                    AS qty
        FROM VIEW_AI_SALES
        WHERE ZONE IN ({outlet_ph}) AND SUBSTR(INVOICE_DATE, 1, 10) BETWEEN ? AND ?
          AND PRODUCT IS NOT NULL
        GROUP BY PRODUCT ORDER BY revenue DESC LIMIT 5
    """
    sql_by_outlet = f"""
        SELECT ZONE AS outlet_name, IFNULL(ROUND(SUM(NET_AMT),2), 0) AS revenue,
               COUNT(DISTINCT INVOICE_NO) AS orders
        FROM VIEW_AI_SALES
        WHERE ZONE IN ({outlet_ph}) AND SUBSTR(INVOICE_DATE, 1, 10) BETWEEN ? AND ?
        GROUP BY ZONE ORDER BY revenue DESC
    """
    sql_daily = f"""
        SELECT SUBSTR(INVOICE_DATE, 1, 10) AS date, IFNULL(ROUND(SUM(NET_AMT),2), 0) AS revenue,
               COUNT(DISTINCT INVOICE_NO) AS orders
        FROM VIEW_AI_SALES
        WHERE ZONE IN ({outlet_ph}) AND SUBSTR(INVOICE_DATE, 1, 10) BETWEEN ? AND ?
        GROUP BY SUBSTR(INVOICE_DATE, 1, 10) ORDER BY SUBSTR(INVOICE_DATE, 1, 10)
    """
    sql_raw = f"""
        SELECT SUBSTR(INVOICE_DATE, 1, 10) AS date, ZONE AS outlet_name, PRODUCT AS item_name,
               NET_AMT AS net_revenue, QTY_PACKS AS quantity,
               CHANNEL AS channel, INVOICE_NO AS bill_no, PRODUCT_CLASS AS product_group
        FROM VIEW_AI_SALES
        WHERE ZONE IN ({outlet_ph}) AND SUBSTR(INVOICE_DATE, 1, 10) BETWEEN ? AND ?
        ORDER BY SUBSTR(INVOICE_DATE, 1, 10), ZONE
    """
    with sqlite_connection(base_dir) as conn:
        kpi = pd.read_sql_query(sql_kpi, conn, params=params)
        top5 = pd.read_sql_query(sql_top5, conn, params=params)
        by_outlet = pd.read_sql_query(sql_by_outlet, conn, params=params)
        daily = pd.read_sql_query(sql_daily, conn, params=params)
        raw_df = pd.read_sql_query(sql_raw, conn, params=params)
    return KPITabData(kpi=kpi, top5=top5, by_outlet=by_outlet, daily=daily, raw_df=raw_df)
