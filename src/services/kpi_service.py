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
        SELECT IFNULL(ROUND(SUM(NETAMT),2), 0) AS total_revenue,
               COUNT(DISTINCT TRNNO)           AS total_orders,
               IFNULL(ROUND(SUM(NETAMT)/NULLIF(COUNT(DISTINCT TRNNO),0),2), 0) AS aov,
               IFNULL(SUM(CAST(PAX AS INTEGER)), 0) AS total_pax,
               IFNULL(SUM(CASH_AMT), 0) AS cash,
               IFNULL(SUM(CARD_AMT), 0) AS card,
               IFNULL(SUM(PAYMENT_UPI), 0) AS upi
        FROM AI_TEST_INVOICEBILLREGISTER
        WHERE LOCATION_NAME IN ({outlet_ph}) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
    """
    sql_top5 = f"""
        SELECT PRODUCT_NAME AS item_name,
               IFNULL(ROUND(SUM(NET_AMT),2), 0) AS revenue,
               SUM(CAST(QTY AS REAL))           AS qty
        FROM AI_TEST_TAXCHARGED_REPORT
        WHERE LOCATION_NAME IN ({outlet_ph}) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
          AND PRODUCT_NAME IS NOT NULL
        GROUP BY PRODUCT_NAME ORDER BY revenue DESC LIMIT 5
    """
    sql_by_outlet = f"""
        SELECT LOCATION_NAME AS outlet_name, IFNULL(ROUND(SUM(NETAMT),2), 0) AS revenue,
               COUNT(DISTINCT TRNNO) AS orders
        FROM AI_TEST_INVOICEBILLREGISTER
        WHERE LOCATION_NAME IN ({outlet_ph}) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
        GROUP BY LOCATION_NAME ORDER BY revenue DESC
    """
    sql_daily = f"""
        SELECT SUBSTR(DT, 1, 10) AS date, IFNULL(ROUND(SUM(NETAMT),2), 0) AS revenue,
               COUNT(DISTINCT TRNNO) AS orders
        FROM AI_TEST_INVOICEBILLREGISTER
        WHERE LOCATION_NAME IN ({outlet_ph}) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
        GROUP BY SUBSTR(DT, 1, 10) ORDER BY SUBSTR(DT, 1, 10)
    """
    sql_raw = f"""
        SELECT SUBSTR(DT, 1, 10) AS date, LOCATION_NAME AS outlet_name, PRODUCT_NAME AS item_name,
               NET_AMT AS net_revenue, QTY AS quantity,
               ORDERTYPE_NAME AS channel, TRNNO AS bill_no, GROUP_NAME AS product_group,
               ORDER_STARTTIME AS kot_time
        FROM AI_TEST_TAXCHARGED_REPORT
        WHERE LOCATION_NAME IN ({outlet_ph}) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
        ORDER BY SUBSTR(DT, 1, 10), LOCATION_NAME
    """
    with sqlite_connection(base_dir) as conn:
        kpi = pd.read_sql_query(sql_kpi, conn, params=params)
        top5 = pd.read_sql_query(sql_top5, conn, params=params)
        by_outlet = pd.read_sql_query(sql_by_outlet, conn, params=params)
        daily = pd.read_sql_query(sql_daily, conn, params=params)
        raw_df = pd.read_sql_query(sql_raw, conn, params=params)
    return KPITabData(kpi=kpi, top5=top5, by_outlet=by_outlet, daily=daily, raw_df=raw_df)
