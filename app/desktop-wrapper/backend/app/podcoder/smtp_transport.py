"""TLS-only SMTP transport. Configuration in env; error details never contain secrets."""
import os
import ssl
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

LAST_ERROR = {'kind': ''}


def configured():
    return bool(os.environ.get('SMTP_HOST') and os.environ.get('SMTP_FROM'))


def _clean_address(value):
    text = str(value or '').strip()
    if not text or any(ch in text for ch in '\r\n\x00') or len(text) > 320:
        return ''
    _name, address = parseaddr(text)
    if address.count('@') != 1 or ' ' in address:
        return ''
    return text


def build_message(to, title, detail):
    """Header-injection-safe message. Raises ValueError for unsafe headers."""
    sender, recipient = _clean_address(os.environ.get('SMTP_FROM')), _clean_address(to)
    subject = str(title or '')
    if not sender or not recipient or any(ch in subject for ch in '\r\n'):
        raise ValueError('unsafe mail header')
    message = EmailMessage()
    message['From'], message['To'], message['Subject'] = sender, recipient, subject[:200]
    message['Date'] = formatdate(localtime=False)
    message['Message-ID'] = make_msgid(domain=parseaddr(sender)[1].split('@')[-1] or None)
    message['Auto-Submitted'] = 'auto-generated'
    message.set_content(str(detail or ''))
    return message


def send(to, title, detail, *, smtp_module=None):
    """Return 'smtp', 'dev' (not configured) or 'error'. Never retries silently."""
    LAST_ERROR['kind'] = ''
    if not configured() or not to:
        return 'dev'
    lib = smtp_module or smtplib
    try:
        port = int(os.environ.get('SMTP_PORT', '587'))
        if port not in (465, 587):
            LAST_ERROR['kind'] = 'port'
            return 'error'
        message = build_message(to, title, detail)
        context = ssl.create_default_context()
        cls = lib.SMTP_SSL if port == 465 else lib.SMTP
        kwargs = {'timeout': 15}
        if port == 465:
            kwargs['context'] = context
        with cls(os.environ['SMTP_HOST'], port, **kwargs) as smtp:
            if port == 587:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            if os.environ.get('SMTP_USER'):
                smtp.login(os.environ['SMTP_USER'], os.environ.get('SMTP_PASSWORD', ''))
            refused = smtp.send_message(message)
            if refused:
                LAST_ERROR['kind'] = 'refused'
                return 'error'
        return 'smtp'
    except ValueError:
        LAST_ERROR['kind'] = 'header'
        return 'error'
    except Exception as exc:
        # Class name only: never the server banner, credentials or recipient.
        LAST_ERROR['kind'] = type(exc).__name__
        return 'error'
