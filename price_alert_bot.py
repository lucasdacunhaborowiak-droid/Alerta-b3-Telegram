import json
import os
import requests

CONFIG_PATH = "alerts.json"

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def get_price(ticker):
    """Busca o preço atual do ativo na API pública do Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    data = r.json()
    result = data["chart"]["result"][0]
    return result["meta"]["regularMarketPrice"]


def send_telegram(message):
    """Envia uma mensagem para o chat configurado via Bot API do Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    r = requests.post(url, data=payload, timeout=10)
    r.raise_for_status()


def main():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        categories = json.load(f)

    changed = False

    for category, alerts in categories.items():
        for alert in alerts:
            if alert.get("triggered"):
                continue  # já disparou antes, não repete

            ticker = alert["ticker"]
            target = alert["target_price"]
            condition = alert["condition"]  # "above" ou "below"

            try:
                price = get_price(ticker)
            except Exception as e:
                print(f"Erro ao buscar {ticker}: {e}")
                continue

            hit = (condition == "above" and price >= target) or (
                condition == "below" and price <= target
            )

            if hit:
                emoji = "🟢" if condition == "above" else "🔴"
                cond_texto = "acima de" if condition == "above" else "abaixo de"
                send_telegram(
                    f"{emoji} [{category}] Alerta disparado!\n"
                    f"{ticker}: R$ {price:.2f}\n"
                    f"Alvo: {cond_texto} R$ {target:.2f}"
                )
                alert["triggered"] = True
                changed = True
                print(f"Alerta disparado para {ticker} ({category})")
            else:
                print(
                    f"[{category}] {ticker}: R$ {price:.2f} "
                    f"(alvo {condition} R$ {target:.2f}) - sem alerta ainda"
                )

    if changed:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(categories, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
