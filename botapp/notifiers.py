"""Notificadores de alertas — Slack, Discord, Email.

Cada canal é opt-in: se a variável de ambiente correspondente não estiver
definida, o canal é silenciosamente ignorado. Falha em um canal não bloqueia
os outros — cada um é protegido por try/except com logger.exception.

Variáveis de ambiente:
  BOTAPP_SLACK_WEBHOOK_URL        — URL de Incoming Webhook do Slack
  BOTAPP_DISCORD_WEBHOOK_URL      — URL de Webhook do Discord
  BOTAPP_ALERT_EMAIL_RECIPIENTS   — lista separada por vírgula
  BOTAPP_NOTIFIER_TIMEOUT         — timeout HTTP em segundos (default 5)
  BOTAPP_DASHBOARD_URL            — base para gerar link para o bot no dashboard

Usa a configuração de email do Django (settings.EMAIL_*), de modo que o
projeto hospedeiro pode sobrescrever tudo em modo plugin.
"""
from __future__ import annotations

import logging
import os

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

_TIMEOUT = float(os.environ.get('BOTAPP_NOTIFIER_TIMEOUT', '5'))

_SEVERITY_COLOR = {
    'low': '#36a64f',       # verde
    'medium': '#f2c744',    # amarelo
    'high': '#e8770a',      # laranja
    'critical': '#d32f2f',  # vermelho
}

_SEVERITY_EMOJI = {
    'low': ':information_source:',
    'medium': ':warning:',
    'high': ':rotating_light:',
    'critical': ':fire:',
}


def _dashboard_link(alert):
    """Link para o dashboard do bot — opcional, só renderiza se configurado."""
    base = os.environ.get('BOTAPP_DASHBOARD_URL')
    if not base or not alert.bot_id:
        return None
    return f"{base.rstrip('/')}/bots/{alert.bot_id}/"


def _format_title(alert):
    bot_name = alert.bot.name if alert.bot_id else 'global'
    return f"[{alert.severity.upper()}] {alert.get_type_display()} · {bot_name}"


def send_slack(alert) -> bool:
    """Envia alerta para Slack via Incoming Webhook. Retorna True se OK."""
    url = os.environ.get('BOTAPP_SLACK_WEBHOOK_URL')
    if not url:
        return False

    emoji = _SEVERITY_EMOJI.get(alert.severity, ':bell:')
    color = _SEVERITY_COLOR.get(alert.severity, '#888888')
    link = _dashboard_link(alert)

    fields = [
        {'title': 'Tipo', 'value': alert.get_type_display(), 'short': True},
        {'title': 'Severidade', 'value': alert.severity.upper(), 'short': True},
    ]
    if alert.bot_id:
        fields.append({'title': 'Bot', 'value': alert.bot.name, 'short': True})
    if link:
        fields.append({'title': 'Dashboard', 'value': f'<{link}|Abrir>', 'short': True})

    payload = {
        'text': f'{emoji} {_format_title(alert)}',
        'attachments': [{
            'color': color,
            'text': alert.message,
            'fields': fields,
            'ts': int(alert.created_at.timestamp()) if alert.created_at else None,
        }],
    }

    try:
        resp = requests.post(url, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        return True
    except Exception:
        logger.exception('notifier.slack: falha ao enviar alert_id=%s', alert.pk)
        return False


def send_discord(alert) -> bool:
    """Envia alerta para Discord via Webhook. Retorna True se OK."""
    url = os.environ.get('BOTAPP_DISCORD_WEBHOOK_URL')
    if not url:
        return False

    color_hex = _SEVERITY_COLOR.get(alert.severity, '#888888').lstrip('#')
    try:
        color_int = int(color_hex, 16)
    except ValueError:
        color_int = 0x888888

    link = _dashboard_link(alert)
    fields = [
        {'name': 'Tipo', 'value': alert.get_type_display(), 'inline': True},
        {'name': 'Severidade', 'value': alert.severity.upper(), 'inline': True},
    ]
    if alert.bot_id:
        fields.append({'name': 'Bot', 'value': alert.bot.name, 'inline': True})

    embed = {
        'title': _format_title(alert),
        'description': alert.message[:2000],  # Discord embed description limit
        'color': color_int,
        'fields': fields,
        'timestamp': alert.created_at.isoformat() if alert.created_at else None,
    }
    if link:
        embed['url'] = link

    try:
        resp = requests.post(url, json={'embeds': [embed]}, timeout=_TIMEOUT)
        resp.raise_for_status()
        return True
    except Exception:
        logger.exception('notifier.discord: falha ao enviar alert_id=%s', alert.pk)
        return False


def send_email(alert) -> bool:
    """Envia alerta por email para BOTAPP_ALERT_EMAIL_RECIPIENTS. Retorna True se OK."""
    raw = os.environ.get('BOTAPP_ALERT_EMAIL_RECIPIENTS', '')
    recipients = [e.strip() for e in raw.split(',') if e.strip()]
    if not recipients:
        return False

    # Import tardio: evita dependência obrigatória do django.core.mail em
    # contextos que só querem os webhooks.
    from django.core.mail import send_mail
    from django.conf import settings

    subject = _format_title(alert)
    link = _dashboard_link(alert)
    body_lines = [
        alert.message,
        '',
        f'Tipo: {alert.get_type_display()}',
        f'Severidade: {alert.severity.upper()}',
    ]
    if alert.bot_id:
        body_lines.append(f'Bot: {alert.bot.name}')
    if link:
        body_lines.extend(['', f'Dashboard: {link}'])
    body = '\n'.join(body_lines)

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', None)

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=from_email,
            recipient_list=recipients,
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception('notifier.email: falha ao enviar alert_id=%s', alert.pk)
        return False


def dispatch_alert(alert) -> dict:
    """Envia o alerta por todos os canais configurados.

    Retorna dict com o status de cada canal. Atualiza alert.notified_at
    se *qualquer* canal teve sucesso — assim `check_alerts` não fica
    disparando notificações a cada rodada.
    """
    results = {
        'slack': send_slack(alert),
        'discord': send_discord(alert),
        'email': send_email(alert),
    }

    if any(results.values()):
        alert.notified_at = timezone.now()
        alert.save(update_fields=['notified_at', 'updated_at'])

    logger.info(
        'alert.dispatched id=%s type=%s severity=%s results=%s',
        alert.pk, alert.type, alert.severity, results,
    )
    return results
