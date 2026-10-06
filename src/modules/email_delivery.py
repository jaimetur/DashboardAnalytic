"""SMTP email delivery for scheduled reports, configured in Application Config."""
from __future__ import annotations

import json
import mimetypes
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from typing import Any

EMAIL_DELIVERY_STATE_KEY = 'email_delivery_v1'
EMAIL_SECURITY_MODES = ('starttls', 'ssl', 'none')
EMAIL_ADDRESS_PATTERN = re.compile(r'^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$')
DEFAULT_MAX_ATTACHMENTS_MB = 20
SMTP_TIMEOUT_SECONDS = 60

# Deployment defaults; values saved in Application Config take precedence.
EMAIL_ENVIRONMENT_DEFAULTS = {
    'host': 'SMTP_HOST', 'port': 'SMTP_PORT', 'security': 'SMTP_SECURITY', 'username': 'SMTP_USERNAME',
    'password': 'SMTP_PASSWORD', 'from_address': 'SMTP_FROM', 'from_name': 'SMTP_FROM_NAME',
    'max_attachments_mb': 'SMTP_MAX_ATTACHMENTS_MB',
}


def parse_recipients(value: str | list[str] | None) -> list[str]:
    """Split a comma, semicolon or line separated recipient list, keeping order."""
    items = value if isinstance(value, list) else re.split(r'[,;\n]+', str(value or ''))
    return list(dict.fromkeys(item.strip() for item in items if str(item).strip()))


def invalid_recipients(recipients: list[str]) -> list[str]:
    return [item for item in recipients if not EMAIL_ADDRESS_PATTERN.match(item)]


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def email_delivery_settings(repository: Any, *, include_password: bool = False) -> dict[str, Any]:
    """Saved SMTP settings over environment defaults; the password is only returned on request."""
    values: dict[str, Any] = {key: os.environ.get(variable, '') for key, variable in EMAIL_ENVIRONMENT_DEFAULTS.items()}
    try:
        stored = json.loads(repository.get_application_state(EMAIL_DELIVERY_STATE_KEY) or '{}')
    except (TypeError, ValueError):
        stored = {}
    if isinstance(stored, dict):
        for key, value in stored.items():
            # An empty saved password keeps the deployment password, if any.
            if key in EMAIL_ENVIRONMENT_DEFAULTS and (key != 'password' or value):
                values[key] = value
    security = str(values.get('security') or 'starttls').strip().casefold()
    settings = {
        'host': str(values.get('host') or '').strip(),
        'port': _int(values.get('port'), 465 if security == 'ssl' else 587 if security == 'starttls' else 25),
        'security': security if security in EMAIL_SECURITY_MODES else 'starttls',
        'username': str(values.get('username') or '').strip(),
        'from_address': str(values.get('from_address') or '').strip(),
        'from_name': str(values.get('from_name') or 'DriveTest Analyzer').strip(),
        'max_attachments_mb': max(1, _int(values.get('max_attachments_mb'), DEFAULT_MAX_ATTACHMENTS_MB)),
        'password_configured': bool(values.get('password')),
    }
    settings['configured'] = bool(settings['host'] and settings['from_address'])
    if include_password:
        settings['password'] = str(values.get('password') or '')
    return settings


def save_email_delivery_settings(repository: Any, values: dict[str, Any], *, keep_password: bool) -> dict[str, Any]:
    """Validate and persist SMTP settings; keep_password retains the saved password."""
    try:
        previous = json.loads(repository.get_application_state(EMAIL_DELIVERY_STATE_KEY) or '{}')
    except (TypeError, ValueError):
        previous = {}
    previous = previous if isinstance(previous, dict) else {}
    security = str(values.get('security') or 'starttls').strip().casefold()
    if security not in EMAIL_SECURITY_MODES:
        raise ValueError('Choose STARTTLS, SSL/TLS or no encryption.')
    port = _int(values.get('port'), 0)
    if not 1 <= port <= 65535:
        raise ValueError('The SMTP port must be between 1 and 65535.')
    from_address = str(values.get('from_address') or '').strip()
    if from_address and not EMAIL_ADDRESS_PATTERN.match(from_address):
        raise ValueError('Enter a valid sender address.')
    max_attachments_mb = _int(values.get('max_attachments_mb'), DEFAULT_MAX_ATTACHMENTS_MB)
    if not 1 <= max_attachments_mb <= 500:
        raise ValueError('The attachment size limit must be between 1 and 500 MB.')
    stored = {
        'host': str(values.get('host') or '').strip(), 'port': port, 'security': security,
        'username': str(values.get('username') or '').strip(),
        'password': str(previous.get('password') or '') if keep_password else str(values.get('password') or ''),
        'from_address': from_address, 'from_name': str(values.get('from_name') or '').strip(),
        'max_attachments_mb': max_attachments_mb,
    }
    repository.set_application_state(EMAIL_DELIVERY_STATE_KEY, json.dumps(stored, sort_keys=True))
    return email_delivery_settings(repository)


def build_email(settings: dict[str, Any], recipients: list[str], subject: str, text: str, html: str,
                attachments: list[tuple[str, Path]]) -> EmailMessage:
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = formataddr((settings.get('from_name') or '', settings['from_address']))
    message['To'] = ', '.join(recipients)
    message['Message-ID'] = make_msgid(domain=settings['from_address'].rsplit('@', 1)[-1])
    message.set_content(text)
    message.add_alternative(html, subtype='html')
    for file_name, path in attachments:
        content_type = mimetypes.guess_type(file_name)[0] or 'application/octet-stream'
        maintype, subtype = content_type.split('/', 1)
        message.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=file_name)
    return message


def send_email(settings: dict[str, Any], recipients: list[str], subject: str, text: str, html: str,
               attachments: list[tuple[str, Path]] | None = None) -> None:
    """Send one message through the configured SMTP server; raises on failure."""
    if not settings.get('configured'):
        raise RuntimeError('Email delivery is not configured. Set the SMTP server and sender in Application Config.')
    if not recipients:
        raise RuntimeError('The report has no recipients.')
    attachments = attachments or []
    total_bytes = sum(path.stat().st_size for _name, path in attachments)
    limit_bytes = int(settings.get('max_attachments_mb') or DEFAULT_MAX_ATTACHMENTS_MB) * 1024 * 1024
    if total_bytes > limit_bytes:
        raise RuntimeError(
            f'The attachments total {total_bytes / 1024 / 1024:.1f} MB, above the '
            f'{settings.get("max_attachments_mb")} MB limit set in Application Config.'
        )
    message = build_email(settings, recipients, subject, text, html, attachments)
    host, port, security = settings['host'], int(settings['port']), settings['security']
    context = ssl.create_default_context()
    if security == 'ssl':
        server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT_SECONDS, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS)
    with server:
        server.ehlo()
        if security == 'starttls':
            server.starttls(context=context)
            server.ehlo()
        if settings.get('username'):
            server.login(settings['username'], settings.get('password') or '')
        server.send_message(message)
