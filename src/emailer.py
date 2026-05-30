import os
import smtplib
from email.mime.text import MIMEText


def send_email(subject: str, body: str) -> None:
    user = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASS")
    to_addr = os.getenv("EMAIL_TO")

    if not user or not password or not to_addr:
        print("Email skipped: EMAIL_USER, EMAIL_PASS, or EMAIL_TO missing.")
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(user, password)
        server.sendmail(user, [to_addr], msg.as_string())

    print("Email sent.")
