import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

CONFIG_PATH = "alerts.json"
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def get_quote(ticker):
    """Busca preço atual e dados básicos do ativo no Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()
    result = data["chart"]["result"][0]
    meta = result["meta"]

    price = meta.get("regularMarketPrice")
    previous_close = meta.get("previousClose") or meta.get("chartPreviousClose")

    if price is None:
        raise ValueError(f"Preço indisponível para {ticker}")

    change_pct = None
    if previous_close not in (None, 0):
        change_pct = ((price - previous_close) / previous_close) * 100

    return {
        "price": float(price),
        "previous_close": float(previous_close) if previous_close is not None else None,
        "change_pct": change_pct,
    }


def send_telegram(message):
    """Envia uma mensagem para o chat configurado via Bot API do Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }
    r = requests.post(url, data=payload, timeout=15)
    r.raise_for_status()


def load_alerts():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_alerts(categories):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(categories, f, ensure_ascii=False, indent=2)


def format_price(ticker, value):
    if ticker.endswith("-USD"):
        return f"US$ {value:,.2f}"
    return f"R$ {value:,.2f}"


def unique_tickers(categories):
    """Retorna cada ticker uma única vez, preservando categoria e ordem."""
    seen = set()
    result = []
    for category, alerts in categories.items():
        for alert in alerts:
            ticker = alert["ticker"]
            if ticker not in seen:
                seen.add(ticker)
                result.append((category, ticker))
    return result




def nearest_pending_target(categories, ticker, current_price):
    """Encontra o alvo ainda não disparado mais próximo do preço atual."""
    candidates = []
    for alerts in categories.values():
        for alert in alerts:
            if alert.get("ticker") != ticker or alert.get("triggered"):
                continue

            target = float(alert["target_price"])
            condition = alert["condition"]
            distance = abs(target - current_price)
            candidates.append((distance, target, condition))

    if not candidates:
        return None

    _, target, condition = min(candidates, key=lambda item: item[0])
    move_pct = ((target - current_price) / current_price) * 100 if current_price else None

    hit = (condition == "above" and current_price >= target) or (
        condition == "below" and current_price <= target
    )

    return {
        "target": target,
        "condition": condition,
        "distance": abs(target - current_price),
        "move_pct": move_pct,
        "hit": hit,
    }

def check_targets(categories):
    changed = False

    for category, alerts in categories.items():
        for alert in alerts:
            if alert.get("triggered"):
                continue

            ticker = alert["ticker"]
            target = alert["target_price"]
            condition = alert["condition"]

            try:
                quote = get_quote(ticker)
                price = quote["price"]
            except Exception as e:
                print(f"Erro ao buscar {ticker}: {e}")
                continue

            hit = (condition == "above" and price >= target) or (
                condition == "below" and price <= target
            )

            if hit:
                emoji = "🟢" if condition == "above" else "🔴"
                cond_text = "acima de" if condition == "above" else "abaixo de"
                send_telegram(
                    f"{emoji} [{category}] Alerta disparado!\n"
                    f"{ticker}: {format_price(ticker, price)}\n"
                    f"Alvo: {cond_text} {format_price(ticker, target)}"
                )
                alert["triggered"] = True
                changed = True
                print(f"Alerta disparado para {ticker} ({category})")
            else:
                print(
                    f"[{category}] {ticker}: {format_price(ticker, price)} "
                    f"(alvo {condition} {format_price(ticker, target)}) - sem alerta ainda"
                )

    if changed:
        save_alerts(categories)


def send_market_summary(categories, label):
    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    lines = [f"📊 {label} — {now.strftime('%d/%m/%Y')}"]

    current_category = None
    for category, ticker in unique_tickers(categories):
        if category != current_category:
            lines.append("")
            lines.append(f"{category}")
            current_category = category

        try:
            quote = get_quote(ticker)
            price = quote["price"]
            change_pct = quote["change_pct"]

            if change_pct is None:
                change_text = ""
            else:
                arrow = "▲" if change_pct > 0 else "▼" if change_pct < 0 else "•"
                change_text = f" | {arrow} {change_pct:+.2f}%"

            lines.append(f"• {ticker}: {format_price(ticker, price)}{change_text}")

            nearest = nearest_pending_target(categories, ticker, price)
            if nearest is None:
                lines.append("  ↳ Sem alvos pendentes")
            elif nearest["hit"]:
                lines.append(
                    f"  ↳ Alvo mais próximo: {format_price(ticker, nearest['target'])} "
                    f"| alvo já atingido/ultrapassado"
                )
            else:
                direction = "▲" if nearest["target"] > price else "▼"
                pct = abs(nearest["move_pct"]) if nearest["move_pct"] is not None else 0
                lines.append(
                    f"  ↳ Alvo mais próximo: {format_price(ticker, nearest['target'])} "
                    f"| faltam {format_price(ticker, nearest['distance'])} ({direction} {pct:.2f}%)"
                )
        except Exception as e:
            lines.append(f"• {ticker}: indisponível")
            print(f"Erro ao buscar {ticker}: {e}")

    # Telegram limita mensagens a 4096 caracteres; divide com folga.
    chunks = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > 3500:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)

    for chunk in chunks:
        send_telegram(chunk)


def send_test_message():
    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    send_telegram(
        "✅ Bot de preços funcionando!\n"
        f"Teste realizado em {now.strftime('%d/%m/%Y às %H:%M')} (horário de Brasília).\n"
        "Os alertas de preço e resumos estão ativos."
    )


def main():
    categories = load_alerts()
    mode = (os.getenv("BOT_MODE") or (sys.argv[1] if len(sys.argv) > 1 else "alerts")).lower()

    if mode == "alerts":
        check_targets(categories)
    elif mode == "open":
        send_market_summary(categories, "Abertura do mercado")
    elif mode == "close":
        send_market_summary(categories, "Fechamento do mercado")
    elif mode == "test":
        send_test_message()
    else:
        raise ValueError(f"BOT_MODE inválido: {mode}")


if __name__ == "__main__":
    main()
