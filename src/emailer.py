import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def parse_recipients(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [addr.strip() for addr in re.split(r"[;,]", raw) if addr.strip()]


def send_email(subject: str, html_body: str, text_body: str | None = None) -> None:
    user = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASS")
    recipients = parse_recipients(os.getenv("EMAIL_TO"))

    if not user or not password or not recipients:
        print("Email skipped: EMAIL_USER, EMAIL_PASS, or EMAIL_TO missing.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(recipients)

    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(user, password)
        server.sendmail(user, recipients, msg.as_string())

    print(f"Email sent to {len(recipients)} recipient(s).")
