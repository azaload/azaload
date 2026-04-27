"""Système d'alerte: terminal en temps réel + intégrations optionnelles.

Toutes les fonctions Telegram/Discord ne s'activent que si les variables
d'environnement correspondantes sont définies. Sinon elles sont no-op.
"""

from __future__ import annotations

import json
from typing import Iterable

import requests

from .logger import get_logger
from .pump_dump import PumpDumpSignal
from .signals import Signal

log = get_logger(__name__)


# ANSI colors (no extra dependency)
_RESET = "\033[0m"
_BOLD = "\033[1m"
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_MAGENTA = "\033[95m"
_GRAY = "\033[90m"


def _color_for(action: str) -> str:
    return {
        "BUY": _GREEN, "LONG": _GREEN,
        "SELL": _RED, "SHORT": _RED,
        "HOLD": _YELLOW, "NONE": _YELLOW,
    }.get(action, _RESET)


def format_terminal(signal: Signal) -> str:
    """Construit une chaîne lisible pour la sortie console."""
    color = _color_for(signal.action)
    bar = "─" * 70

    lines = [
        f"{_GRAY}{bar}{_RESET}",
        f"{_BOLD}{color}  {signal.action:<5}{_RESET}  "
        f"{_BOLD}{signal.symbol}{_RESET} ({signal.name})  "
        f"{_GRAY}{signal.timestamp.strftime('%Y-%m-%d %H:%M UTC')}{_RESET}",
        f"  Confiance      : {_BOLD}{signal.confidence:5.1f}%{_RESET}",
        f"  Entrée         : {signal.entry_price:.6f}",
    ]
    if signal.action != "HOLD":
        lines += [
            f"  Stop Loss      : {_RED}{signal.stop_loss:.6f}{_RESET}",
            f"  Take Profit    : {_GREEN}{signal.take_profit:.6f}{_RESET}",
            f"  Risk/Reward    : {signal.risk_reward:.2f}",
        ]
    lines.append(f"  {_CYAN}Score par stratégie{_RESET} :")
    for sname, sscore in signal.strategy_breakdown.items():
        lines.append(f"    - {sname:<16} {sscore:+.2f}")

    if signal.reasons:
        lines.append(f"  {_CYAN}Raisons{_RESET} :")
        for r in signal.reasons:
            lines.append(f"    • {r}")

    lines.append(f"{_GRAY}{bar}{_RESET}")
    return "\n".join(lines)


def send_terminal(signal: Signal) -> None:
    print(format_terminal(signal))


def format_pump_dump_terminal(signal: PumpDumpSignal) -> str:
    """Construit l'affichage console pour un signal pump/dump (futures)."""
    color = _color_for(signal.direction)
    bar = "═" * 70
    label = "PUMP DETECTED" if signal.direction == "LONG" else "DUMP DETECTED"

    lines = [
        f"{_MAGENTA}{bar}{_RESET}",
        f"{_BOLD}{color}  ⚡ {label} — {signal.direction:<5}{_RESET}  "
        f"{_BOLD}{signal.symbol}{_RESET} ({signal.name})  "
        f"{_GRAY}{signal.timestamp.strftime('%Y-%m-%d %H:%M UTC')}{_RESET}",
        f"  Probabilité    : {_BOLD}{signal.probability:5.1f}%{_RESET}",
        f"  Entrée         : {signal.entry_price:.6f}",
        f"  Stop Loss      : {_RED}{signal.stop_loss:.6f}{_RESET}",
        f"  Take Profit    : {_GREEN}{signal.take_profit:.6f}{_RESET}",
        f"  Risk/Reward    : {signal.risk_reward:.2f}",
        f"  {_CYAN}Triggers actifs{_RESET} :",
    ]
    triggers = signal.triggers
    # Si triggers contient "long"/"short" (cas NONE), on n'affiche pas
    if isinstance(next(iter(triggers.values()), None), bool):
        for k, v in triggers.items():
            mark = f"{_GREEN}✓{_RESET}" if v else f"{_GRAY}·{_RESET}"
            lines.append(f"    {mark} {k}")
    if signal.reasons:
        lines.append(f"  {_CYAN}Raisons{_RESET} :")
        for r in signal.reasons:
            lines.append(f"    • {r}")
    lines.append(f"{_MAGENTA}{bar}{_RESET}")
    return "\n".join(lines)


def send_pump_dump_terminal(signal: PumpDumpSignal) -> None:
    print(format_pump_dump_terminal(signal))


def send_telegram(signal: Signal, bot_token: str | None, chat_id: str | None) -> bool:
    if not (bot_token and chat_id):
        return False
    text = _format_plain(signal)
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.warning("Telegram send failed: %s", exc)
        return False


def send_discord(signal: Signal, webhook_url: str | None) -> bool:
    if not webhook_url:
        return False
    text = _format_plain(signal)
    try:
        resp = requests.post(webhook_url, json={"content": text}, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.warning("Discord send failed: %s", exc)
        return False


def _format_plain(signal: Signal) -> str:
    head = f"*{signal.action}* `{signal.symbol}` ({signal.name}) — {signal.confidence:.1f}%"
    body = [
        f"Entrée: {signal.entry_price:.6f}",
    ]
    if signal.action != "HOLD":
        body += [
            f"SL: {signal.stop_loss:.6f}",
            f"TP: {signal.take_profit:.6f}",
            f"R/R: {signal.risk_reward:.2f}",
        ]
    body += ["Raisons:"] + [f"- {r}" for r in signal.reasons[:6]]
    return head + "\n" + "\n".join(body)


def _format_pump_dump_plain(signal: PumpDumpSignal) -> str:
    label = "PUMP" if signal.direction == "LONG" else "DUMP"
    head = (
        f"⚡ *{label} {signal.direction}* `{signal.symbol}` ({signal.name}) — "
        f"{signal.probability:.1f}%"
    )
    body = [
        f"Entrée: {signal.entry_price:.6f}",
        f"SL: {signal.stop_loss:.6f}",
        f"TP: {signal.take_profit:.6f}",
        f"R/R: {signal.risk_reward:.2f}",
        "Raisons:",
    ] + [f"- {r}" for r in signal.reasons[:6]]
    return head + "\n" + "\n".join(body)


def send_pump_dump_telegram(
    signal: PumpDumpSignal, bot_token: str | None, chat_id: str | None
) -> bool:
    if not (bot_token and chat_id):
        return False
    text = _format_pump_dump_plain(signal)
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.warning("Telegram pump/dump send failed: %s", exc)
        return False


def send_pump_dump_discord(signal: PumpDumpSignal, webhook_url: str | None) -> bool:
    if not webhook_url:
        return False
    try:
        resp = requests.post(
            webhook_url, json={"content": _format_pump_dump_plain(signal)}, timeout=10
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.warning("Discord pump/dump send failed: %s", exc)
        return False


def dispatch_pump_dump(
    signal: PumpDumpSignal,
    *,
    telegram_token: str | None = None,
    telegram_chat: str | None = None,
    discord_webhook: str | None = None,
) -> None:
    """Envoie une alerte pump/dump sur tous les canaux configurés."""
    send_pump_dump_terminal(signal)
    if telegram_token and telegram_chat:
        send_pump_dump_telegram(signal, telegram_token, telegram_chat)
    if discord_webhook:
        send_pump_dump_discord(signal, discord_webhook)


def dispatch(
    signal: Signal,
    *,
    telegram_token: str | None = None,
    telegram_chat: str | None = None,
    discord_webhook: str | None = None,
    extra_sinks: Iterable = (),
) -> None:
    """Envoie l'alerte sur tous les canaux configurés."""
    send_terminal(signal)
    if telegram_token and telegram_chat:
        send_telegram(signal, telegram_token, telegram_chat)
    if discord_webhook:
        send_discord(signal, discord_webhook)
    for sink in extra_sinks:
        try:
            sink(signal)
        except Exception as exc:  # ne jamais casser la boucle d'alerte
            log.warning("Custom sink error: %s", exc)


def dump_json(signal: Signal | PumpDumpSignal) -> str:
    return json.dumps(signal.to_dict(), ensure_ascii=False, indent=2)
