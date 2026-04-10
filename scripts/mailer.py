"""
QAFFEINE Mailer — Professional HTML Email Dispatcher
=====================================================
Sends mobile-responsive, QAFFEINE-branded HTML email briefs with:
  - Anomaly digest (Z-score flagged revenue dips)
  - Jarvis Diagnosis (root-cause narrative from LLM)
  - Jarvis Recommendation (recovery bundle from live basket analysis)

Security:
  - Credentials loaded from .env (SMTP_HOST, SMTP_PORT, SMTP_USER,
    SMTP_PASS, ALERT_RECIPIENT) or st.secrets on Streamlit Cloud.
  - Uses smtplib with TLS.

Usage:
    from mailer import send_morning_brief
    success, msg = send_morning_brief(anomalies, diagnosis_paragraphs, recommendations)
"""

import os, csv, datetime, smtplib, ssl
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# ── Paths & env ───────────────────────────────────────────────────────────────
BASE     = Path(__file__).resolve().parent.parent
ENV_PATH = BASE.parent / ".env"
LOG_DIR  = BASE / "logs"
LOG_CSV  = LOG_DIR / "notification_history.csv"

load_dotenv(ENV_PATH, override=True)

# ── SMTP Configuration ───────────────────────────────────────────────────────
def _get_smtp_config() -> dict:
    """
    Load SMTP creds from environment (.env) or st.secrets (Streamlit Cloud).
    Returns dict with host, port, user, password, recipient.
    """
    # Try Streamlit secrets first (for Streamlit Cloud deployment)
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            secrets = st.secrets
            # Attempt to read a key — this will raise if no secrets.toml exists
            return {
                "host"      : secrets.get("SMTP_HOST",       os.getenv("SMTP_HOST", "smtp.gmail.com")),
                "port"      : int(secrets.get("SMTP_PORT",   os.getenv("SMTP_PORT", "587"))),
                "user"      : secrets.get("SMTP_USER",       os.getenv("SMTP_USER", "")),
                "password"  : secrets.get("SMTP_PASS",       os.getenv("SMTP_PASS", "")),
                "recipient" : secrets.get("ALERT_RECIPIENT",  os.getenv("ALERT_RECIPIENT", "")),
            }
    except Exception:
        pass   # Not running in Streamlit, or no secrets file — fall through to env vars

    return {
        "host"      : os.getenv("SMTP_HOST",       "smtp.gmail.com"),
        "port"      : int(os.getenv("SMTP_PORT",    "587")),
        "user"      : os.getenv("SMTP_USER",        ""),
        "password"  : os.getenv("SMTP_PASS",        ""),
        "recipient" : os.getenv("ALERT_RECIPIENT",   ""),
    }


# ══════════════════════════════════════════════════════════════════════════════
# HTML EMAIL TEMPLATE
# ══════════════════════════════════════════════════════════════════════════════

def _build_anomaly_rows_html(anomalies: list[dict]) -> str:
    """Build HTML table rows for anomaly records."""
    if not anomalies:
        return """
        <tr>
            <td colspan="5" style="padding:16px;text-align:center;color:#10b981;font-weight:600">
                ✅ No significant revenue anomalies detected
            </td>
        </tr>"""

    rows = []
    for a in anomalies:
        severity_color = "#ef4444" if a.get("severity") == "CRITICAL" else "#f59e0b"
        severity_bg    = "#ef444418" if a.get("severity") == "CRITICAL" else "#f59e0b18"
        z_score        = a.get("z_score", 0)
        pct_dev        = a.get("pct_deviation", 0)

        rows.append(f"""
        <tr style="border-bottom:1px solid #1e293b">
            <td style="padding:12px 8px;color:#e2e8f0;font-weight:600;font-size:14px">{a.get('date', '—')}</td>
            <td style="padding:12px 8px;color:#cbd5e1;font-size:13px">{a.get('outlet_name', '—')[:24]}</td>
            <td style="padding:12px 8px;color:#f1f5f9;font-weight:700;font-size:14px;text-align:right">₹{a.get('revenue', 0):,.0f}</td>
            <td style="padding:12px 8px;text-align:center">
                <span style="background:{severity_bg};color:{severity_color};padding:3px 10px;
                             border-radius:20px;font-size:12px;font-weight:700">Z = {z_score:.2f}</span>
            </td>
            <td style="padding:12px 8px;color:{severity_color};font-weight:700;text-align:right;font-size:13px">{pct_dev:+.1f}%</td>
        </tr>""")

    return "\n".join(rows)


def _build_diagnosis_html(diagnosis_paragraphs: list[dict]) -> str:
    """Build HTML blocks for each diagnosis paragraph."""
    if not diagnosis_paragraphs:
        return """
        <div style="padding:16px;color:#94a3b8;font-style:italic;text-align:center">
            No anomalies to diagnose — all outlets within normal range.
        </div>"""

    blocks = []
    for d in diagnosis_paragraphs:
        z_score = d.get("z_score", 0)
        badge_color = "#ef4444" if z_score < -2.5 else "#f59e0b"
        blocks.append(f"""
        <div style="background:linear-gradient(135deg,#1e293b,#0f172a);border-left:4px solid {badge_color};
                     border-radius:0 12px 12px 0;padding:16px 20px;margin-bottom:12px">
            <div style="font-size:13px;font-weight:700;color:{badge_color};margin-bottom:6px;
                        letter-spacing:0.03em;text-transform:uppercase">
                📍 {d.get('outlet_name', 'Unknown')} — {d.get('date', '—')} · Z = {z_score:.2f}
            </div>
            <div style="font-size:14px;color:#e2e8f0;line-height:1.65">
                {d.get('diagnosis', 'Diagnosis pending...')}
            </div>
        </div>""")

    return "\n".join(blocks)


def _build_recommendation_html(recommendations: str) -> str:
    """Build HTML for Jarvis recovery bundle recommendations."""
    if not recommendations or recommendations.strip() == "":
        return """
        <div style="padding:16px;color:#94a3b8;font-style:italic;text-align:center">
            No recovery recommendations available at this time.
        </div>"""

    # Convert plain-text recommendation lines to HTML
    lines = recommendations.strip().split("\n")
    html_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#") or line.startswith("Top") or line.startswith("Live"):
            html_lines.append(
                f'<div style="font-size:14px;font-weight:700;color:#f59e0b;margin:8px 0 4px">{line}</div>')
        elif line.startswith("  #"):
            html_lines.append(
                f'<div style="font-size:13px;color:#e2e8f0;padding:6px 0 2px;'
                f'border-bottom:1px solid rgba(255,255,255,0.05)">{line}</div>')
        else:
            html_lines.append(
                f'<div style="font-size:12px;color:#94a3b8;padding:2px 0 2px 16px">{line}</div>')

    return "\n".join(html_lines)


def build_email_html(
    anomalies          : list[dict],
    diagnosis_paragraphs: list[dict],
    recommendations    : str = "",
    generated_at       : str = "",
) -> str:
    """
    Build the complete QAFFEINE-branded HTML email.
    Mobile-responsive with dark theme.
    """
    now = generated_at or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    anomaly_count = len(anomalies)
    severity_label = (
        "🔴 CRITICAL" if any(a.get("severity") == "CRITICAL" for a in anomalies)
        else ("🟡 WARNING" if anomalies else "🟢 ALL CLEAR")
    )

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QAFFEINE Morning Brief</title>
</head>
<body style="margin:0;padding:0;background:#0a0a1a;font-family:'Segoe UI',Arial,sans-serif;-webkit-font-smoothing:antialiased">
    <!-- Wrapper -->
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="background:#0a0a1a;padding:20px 0">
        <tr>
            <td align="center">
                <!-- Main container (600px max for email clients) -->
                <table role="presentation" width="600" cellpadding="0" cellspacing="0"
                       style="max-width:600px;width:100%;background:#0f172a;border-radius:16px;
                              overflow:hidden;border:1px solid rgba(255,255,255,0.08)">

                    <!-- ═══ HEADER ═══ -->
                    <tr>
                        <td style="background:linear-gradient(135deg,#1a1a2e 0%,#302b63 100%);
                                   padding:32px 24px;text-align:center;
                                   border-bottom:1px solid rgba(245,158,11,0.3)">
                            <div style="font-size:36px;margin-bottom:4px">☕</div>
                            <div style="font-size:22px;font-weight:800;color:#f1f5f9;
                                        letter-spacing:0.12em">QAFFEINE</div>
                            <div style="font-size:11px;color:#f59e0b;letter-spacing:0.15em;
                                        text-transform:uppercase;margin-top:4px;font-weight:600">
                                JARVIS MORNING BRIEF</div>
                            <div style="font-size:12px;color:#64748b;margin-top:8px">{now}</div>
                        </td>
                    </tr>

                    <!-- ═══ STATUS BANNER ═══ -->
                    <tr>
                        <td style="padding:20px 24px 12px">
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td style="background:linear-gradient(135deg,rgba(245,158,11,0.12),rgba(249,115,22,0.08));
                                               border:1px solid rgba(245,158,11,0.25);border-radius:12px;
                                               padding:16px 20px">
                                        <div style="display:inline-block;width:100%">
                                            <div style="font-size:12px;color:#94a3b8;font-weight:700;
                                                        letter-spacing:0.08em;text-transform:uppercase">
                                                System Status</div>
                                            <div style="font-size:18px;font-weight:800;color:#f1f5f9;
                                                        margin-top:4px">{severity_label}</div>
                                            <div style="font-size:13px;color:#cbd5e1;margin-top:4px">
                                                {anomaly_count} anomal{'y' if anomaly_count == 1 else 'ies'} detected across outlet network</div>
                                        </div>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- ═══ SECTION 1: ANOMALY TABLE ═══ -->
                    <tr>
                        <td style="padding:16px 24px 8px">
                            <div style="font-size:13px;font-weight:800;color:#f59e0b;
                                        letter-spacing:0.08em;text-transform:uppercase;
                                        margin-bottom:12px;padding-bottom:8px;
                                        border-bottom:1px solid rgba(245,158,11,0.2)">
                                📊 Revenue Anomaly Scan
                            </div>
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                                   style="border-collapse:collapse">
                                <thead>
                                    <tr style="border-bottom:2px solid #1e293b">
                                        <th style="padding:8px;text-align:left;font-size:11px;color:#64748b;
                                                   font-weight:700;letter-spacing:0.05em;text-transform:uppercase">Date</th>
                                        <th style="padding:8px;text-align:left;font-size:11px;color:#64748b;
                                                   font-weight:700;letter-spacing:0.05em;text-transform:uppercase">Outlet</th>
                                        <th style="padding:8px;text-align:right;font-size:11px;color:#64748b;
                                                   font-weight:700;letter-spacing:0.05em;text-transform:uppercase">Revenue</th>
                                        <th style="padding:8px;text-align:center;font-size:11px;color:#64748b;
                                                   font-weight:700;letter-spacing:0.05em;text-transform:uppercase">Z-Score</th>
                                        <th style="padding:8px;text-align:right;font-size:11px;color:#64748b;
                                                   font-weight:700;letter-spacing:0.05em;text-transform:uppercase">Deviation</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {_build_anomaly_rows_html(anomalies)}
                                </tbody>
                            </table>
                        </td>
                    </tr>

                    <!-- ═══ SECTION 2: JARVIS DIAGNOSIS ═══ -->
                    <tr>
                        <td style="padding:20px 24px 8px">
                            <div style="font-size:13px;font-weight:800;color:#a78bfa;
                                        letter-spacing:0.08em;text-transform:uppercase;
                                        margin-bottom:12px;padding-bottom:8px;
                                        border-bottom:1px solid rgba(167,139,250,0.2)">
                                🧠 Jarvis Root-Cause Diagnosis
                            </div>
                            {_build_diagnosis_html(diagnosis_paragraphs)}
                        </td>
                    </tr>

                    <!-- ═══ SECTION 3: JARVIS RECOMMENDATION ═══ -->
                    <tr>
                        <td style="padding:20px 24px 8px">
                            <div style="font-size:13px;font-weight:800;color:#10b981;
                                        letter-spacing:0.08em;text-transform:uppercase;
                                        margin-bottom:12px;padding-bottom:8px;
                                        border-bottom:1px solid rgba(16,185,129,0.2)">
                                🎯 Jarvis's Recommendation — Recovery Bundle (Next 24h)
                            </div>
                            <div style="background:linear-gradient(135deg,rgba(16,185,129,0.08),rgba(6,182,212,0.06));
                                         border:1px solid rgba(16,185,129,0.2);border-radius:12px;
                                         padding:16px 20px">
                                {_build_recommendation_html(recommendations)}
                            </div>
                        </td>
                    </tr>

                    <!-- ═══ FOOTER ═══ -->
                    <tr>
                        <td style="padding:24px;text-align:center;
                                   border-top:1px solid rgba(255,255,255,0.06);margin-top:16px">
                            <div style="font-size:11px;color:#475569;letter-spacing:0.05em">
                                QAFFEINE Analytics · Jarvis AI Engine · Automated Brief
                            </div>
                            <div style="font-size:10px;color:#334155;margin-top:6px">
                                This email was generated automatically. Reply to this email for support.
                            </div>
                        </td>
                    </tr>

                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# EMAIL SENDER
# ══════════════════════════════════════════════════════════════════════════════

def send_email(html_body: str, subject: str = "") -> tuple[bool, str]:
    """
    Send an HTML email using SMTP credentials from .env / st.secrets.

    Returns (success: bool, message: str).
    """
    config = _get_smtp_config()

    if not config["user"] or not config["password"]:
        return False, (
            "SMTP credentials not configured. Set SMTP_USER and SMTP_PASS "
            "in your .env file or Streamlit secrets."
        )

    if not config["recipient"]:
        return False, (
            "No recipient configured. Set ALERT_RECIPIENT in your .env file "
            "or Streamlit secrets."
        )

    if not subject:
        subject = f"☕ QAFFEINE Jarvis Brief — {datetime.datetime.now().strftime('%d %b %Y %H:%M')}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = config["user"]
    msg["To"]      = config["recipient"]
    msg.attach(MIMEText(html_body, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(config["host"], config["port"]) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(config["user"], config["password"])
            server.sendmail(config["user"], [config["recipient"]], msg.as_string())

        return True, f"Email sent to {config['recipient']}"

    except smtplib.SMTPAuthenticationError:
        return False, (
            "SMTP authentication failed. If using Gmail, ensure you have an "
            "App Password configured (not your regular password)."
        )
    except Exception as exc:
        return False, f"Email send failed: {exc}"


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFICATION HISTORY LOG
# ══════════════════════════════════════════════════════════════════════════════

def log_notification(
    timestamp      : str,
    anomaly_count  : int,
    outlets_flagged: str,
    root_cause     : str,
    email_status   : str,
    recipient      : str = "",
) -> None:
    """Append a record to logs/notification_history.csv."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    file_exists = LOG_CSV.exists()

    with open(LOG_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "timestamp", "anomaly_count", "outlets_flagged",
                "root_cause_summary", "email_status", "recipient",
            ])
        writer.writerow([
            timestamp, anomaly_count, outlets_flagged,
            root_cause[:200], email_status, recipient,
        ])


def load_notification_history(last_n: int = 5) -> list[dict]:
    """Load the last N notification records from the CSV log."""
    if not LOG_CSV.exists():
        return []

    with open(LOG_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    return rows[-last_n:]


# ══════════════════════════════════════════════════════════════════════════════
# HIGH-LEVEL PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def send_morning_brief(
    anomalies           : list[dict],
    diagnosis_paragraphs: list[dict],
    recommendations     : str = "",
) -> tuple[bool, str]:
    """
    Full morning brief pipeline:
        1. Build branded HTML email
        2. Send via SMTP
        3. Log to notification_history.csv

    Returns (success, message).
    """
    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # Build HTML
    html = build_email_html(
        anomalies=anomalies,
        diagnosis_paragraphs=diagnosis_paragraphs,
        recommendations=recommendations,
        generated_at=generated_at,
    )

    # Send
    success, msg = send_email(html)

    # Log
    outlets_flagged = ", ".join(set(a.get("outlet_name", "") for a in anomalies))
    root_causes = "; ".join(
        f"{d.get('outlet_name','?')}: {d.get('diagnosis','')[:60]}"
        for d in diagnosis_paragraphs
    )

    config = _get_smtp_config()
    log_notification(
        timestamp       = generated_at,
        anomaly_count   = len(anomalies),
        outlets_flagged = outlets_flagged,
        root_cause      = root_causes,
        email_status    = "SENT" if success else f"FAILED: {msg[:80]}",
        recipient       = config.get("recipient", ""),
    )

    return success, msg


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  QAFFEINE Mailer — Test Run")
    print("=" * 60)

    # Build a test email with sample data
    test_anomalies = [{
        "date": "2025-12-07", "outlet_name": "QAFFEINE HITECH CITY",
        "revenue": 28456, "rolling_mean": 34680, "rolling_std": 3200,
        "z_score": -1.94, "pct_deviation": -17.9, "severity": "WARNING",
    }]
    test_diagnosis = [{
        "date": "2025-12-07", "outlet_name": "QAFFEINE HITECH CITY",
        "z_score": -1.94,
        "diagnosis": ("Hitech City revenue fell 18% (Z = −1.94). Correlated with "
                      "Sunday early closure and power disruption at 3 outlets after 4 PM."),
    }]
    test_reco = "Recovery Bundle: Cappuccino + Croissant → ₹299 (15% off)"

    html = build_email_html(test_anomalies, test_diagnosis, test_reco)

    # Save test HTML for preview
    preview_path = BASE / "logs" / "test_email_preview.html"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    preview_path.write_text(html, encoding="utf-8")
    print(f"\n  Preview saved: {preview_path}")
    print(f"  Open in browser to verify layout.\n")

    # Attempt send (will fail gracefully if SMTP not configured)
    ok, msg = send_email(html, subject="QAFFEINE Test Brief")
    print(f"  Send result: {'✅' if ok else '❌'} {msg}")
