import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


CONFIG_PATH = "alerts.json"

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

SUMMARY_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
BUY_CHAT_ID = os.getenv("TELEGRAM_BUY_CHAT_ID") or SUMMARY_CHAT_ID
SELL_CHAT_ID = os.getenv("TELEGRAM_SELL_CHAT_ID") or SUMMARY_CHAT_ID

BRT = ZoneInfo("America/Sao_Paulo")


def categories_only(data):
    for category, alerts in data.items():
        if isinstance(alerts, list):
            yield category, alerts


def get_quote(ticker, retries=3):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    params = {
        "range": "1d",
        "interval": "5m",
        "includePrePost": "false"
    }

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=15
            )

            response.raise_for_status()

            data = response.json()

            result = data["chart"]["result"][0]
            meta = result["meta"]

            price = meta.get("regularMarketPrice")

            previous_close = (
                meta.get("previousClose")
                or meta.get("chartPreviousClose")
            )

            if price is None:
                raise ValueError(
                    f"Preço indisponível para {ticker}"
                )

            day_low = meta.get("regularMarketDayLow")
            day_high = meta.get("regularMarketDayHigh")

            indicators = result.get("indicators") or {}
            quote_blocks = indicators.get("quote") or []

            if quote_blocks:

                lows = [
                    value
                    for value in quote_blocks[0].get("low", [])
                    if value is not None
                ]

                highs = [
                    value
                    for value in quote_blocks[0].get("high", [])
                    if value is not None
                ]

                if day_low is None and lows:
                    day_low = min(lows)

                if day_high is None and highs:
                    day_high = max(highs)

            change_pct = None

            if previous_close not in (None, 0):
                change_pct = (
                    (price - previous_close)
                    / previous_close
                ) * 100

            return {
                "price": float(price),
                "previous_close": (
                    float(previous_close)
                    if previous_close is not None
                    else None
                ),
                "change_pct": change_pct,
                "day_low": (
                    float(day_low)
                    if day_low is not None
                    else float(price)
                ),
                "day_high": (
                    float(day_high)
                    if day_high is not None
                    else float(price)
                )
            }

        except Exception as error:

            last_error = error

            print(
                f"[Tentativa {attempt}/{retries}] "
                f"Erro ao buscar {ticker}: {error}"
            )

            if attempt < retries:
                time.sleep(2 * attempt)

    raise RuntimeError(
        f"Falha ao buscar {ticker} após "
        f"{retries} tentativas: {last_error}"
    )


def send_telegram(message, chat_id):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True
    }

    response = requests.post(
        url,
        data=payload,
        timeout=15
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram não confirmou envio: {result}"
        )

    return True


def load_alerts():

    with open(
        CONFIG_PATH,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(file)


def save_alerts(data):

    temp_path = f"{CONFIG_PATH}.tmp"

    with open(
        temp_path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )

        file.flush()
        os.fsync(file.fileno())

    os.replace(
        temp_path,
        CONFIG_PATH
    )


def format_price(ticker, value):

    if ticker.endswith("-USD"):
        return f"US$ {value:,.2f}"

    return f"R$ {value:,.2f}"


def unique_tickers(categories):

    seen = set()
    result = []

    for category, alerts in categories_only(categories):

        for alert in alerts:

            ticker = alert["ticker"]

            if ticker not in seen:

                seen.add(ticker)

                result.append(
                    (category, ticker)
                )

    return result


def build_quote_cache(categories):

    cache = {}
    errors = {}

    for _, ticker in unique_tickers(categories):

        try:

            cache[ticker] = get_quote(ticker)

        except Exception as error:

            errors[ticker] = str(error)

            print(
                f"[ERRO FINAL] {ticker}: {error}"
            )

    return cache, errors


def nearest_pending_target(
    categories,
    ticker,
    current_price
):

    candidates = []

    for _, alerts in categories_only(categories):

        for alert in alerts:

            if (
                alert.get("ticker") != ticker
                or alert.get("triggered")
            ):
                continue

            target = float(
                alert["target_price"]
            )

            condition = alert["condition"]

            distance = abs(
                target - current_price
            )

            candidates.append(
                (
                    distance,
                    target,
                    condition
                )
            )

    if not candidates:
        return None

    _, target, condition = min(
        candidates,
        key=lambda item: item[0]
    )

    move_pct = None

    if current_price:

        move_pct = (
            (target - current_price)
            / current_price
        ) * 100

    hit = (
        (
            condition == "above"
            and current_price >= target
        )
        or
        (
            condition == "below"
            and current_price <= target
        )
    )

    return {
        "target": target,
        "condition": condition,
        "distance": abs(
            target - current_price
        ),
        "move_pct": move_pct,
        "hit": hit
    }


def resolve_alert_type(alert):

    explicit = str(
        alert.get(
            "alert_type",
            ""
        )
    ).lower().strip()

    if explicit in {
        "buy",
        "sell"
    }:
        return explicit

    if alert.get("condition") == "above":
        return "sell"

    return "buy"


def alert_chat_id(alert):

    alert_type = resolve_alert_type(alert)

    if alert_type == "sell":
        return SELL_CHAT_ID

    return BUY_CHAT_ID


def hit_details(alert, quote):

    target = float(
        alert["target_price"]
    )

    condition = alert["condition"]

    if condition == "below":

        hit = (
            quote["price"] <= target
            or
            quote["day_low"] <= target
        )

        observed = min(
            quote["price"],
            quote["day_low"]
        )

        if quote["price"] <= target:
            source = "preço atual"
        else:
            source = "mínima do dia"

    elif condition == "above":

        hit = (
            quote["price"] >= target
            or
            quote["day_high"] >= target
        )

        observed = max(
            quote["price"],
            quote["day_high"]
        )

        if quote["price"] >= target:
            source = "preço atual"
        else:
            source = "máxima do dia"

    else:

        raise ValueError(
            f"Condição inválida: {condition}"
        )

    return (
        hit,
        observed,
        source
    )


def check_targets(categories):

    quote_cache, errors = build_quote_cache(
        categories
    )

    checked_alerts = 0
    sent_alerts = 0

    for category, alerts in categories_only(categories):

        for alert in alerts:

            if alert.get("triggered"):
                continue

            ticker = alert["ticker"]

            if ticker not in quote_cache:

                print(
                    f"[NÃO VERIFICADO] "
                    f"{ticker} - sem cotação válida"
                )

                continue

            checked_alerts += 1

            quote = quote_cache[ticker]

            target = float(
                alert["target_price"]
            )

            condition = alert["condition"]

            try:

                (
                    hit,
                    observed_price,
                    source
                ) = hit_details(
                    alert,
                    quote
                )

            except Exception as error:

                print(
                    f"[ERRO] {ticker}: {error}"
                )

                continue

            if not hit:

                print(
                    f"[{category}] "
                    f"{ticker}: "
                    f"{format_price(ticker, quote['price'])} | "
                    f"mín {format_price(ticker, quote['day_low'])} | "
                    f"máx {format_price(ticker, quote['day_high'])} | "
                    f"alvo {condition} "
                    f"{format_price(ticker, target)} "
                    f"- pendente"
                )

                continue

            alert_type = resolve_alert_type(
                alert
            )

            if alert_type == "buy":

                emoji = "🟢"
                title = "ALERTA DE COMPRA"

            else:

                emoji = "🔴"
                title = "ALERTA DE VENDA"

            if condition == "below":
                cond_text = "abaixo de"
            else:
                cond_text = "acima de"

            message = (
                f"{emoji} {title}\n"
                f"[{category}] {ticker}\n"
                f"Preço atual: "
                f"{format_price(ticker, quote['price'])}\n"
                f"Alvo: {cond_text} "
                f"{format_price(ticker, target)}\n"
                f"Detectado por: "
                f"{source} "
                f"({format_price(ticker, observed_price)})"
            )

            try:

                send_telegram(
                    message,
                    alert_chat_id(alert)
                )

                alert["triggered"] = True

                alert["triggered_at"] = (
                    datetime
                    .now(BRT)
                    .isoformat(
                        timespec="seconds"
                    )
                )

                alert["trigger_price"] = round(
                    float(observed_price),
                    6
                )

                save_alerts(categories)

                sent_alerts += 1

                print(
                    f"[ENVIADO] "
                    f"{ticker} "
                    f"({category}) "
                    f"-> {title}"
                )

            except Exception as error:

                print(
                    f"[FALHA TELEGRAM] "
                    f"{ticker}: {error}. "
                    f"O alerta NÃO foi marcado "
                    f"como disparado."
                )

    print(
        f"[RESUMO] "
        f"Alertas pendentes verificados: "
        f"{checked_alerts} | "
        f"Alertas enviados: "
        f"{sent_alerts} | "
        f"Tickers com erro: "
        f"{len(errors)}"
    )

    if errors:

        print(
            "[TICKERS COM ERRO]"
        )

        for ticker, error in errors.items():

            print(
                f"- {ticker}: {error}"
            )


def send_market_summary(
    categories,
    label
):

    now = datetime.now(BRT)

    lines = [
        f"📊 {label} — "
        f"{now.strftime('%d/%m/%Y às %H:%M')}"
    ]

    quote_cache, errors = build_quote_cache(
        categories
    )

    current_category = None

    for category, ticker in unique_tickers(categories):

        if category != current_category:

            lines.append("")
            lines.append(category)

            current_category = category

        quote = quote_cache.get(ticker)

        if quote is None:

            lines.append(
                f"• {ticker}: indisponível"
            )

            continue

        price = quote["price"]
        change_pct = quote["change_pct"]

        if change_pct is None:

            change_text = ""

        else:

            if change_pct > 0:
                arrow = "▲"

            elif change_pct < 0:
                arrow = "▼"

            else:
                arrow = "•"

            change_text = (
                f" | {arrow} "
                f"{change_pct:+.2f}%"
            )

        lines.append(
            f"• {ticker}: "
            f"{format_price(ticker, price)}"
            f"{change_text}"
        )

        nearest = nearest_pending_target(
            categories,
            ticker,
            price
        )

        if nearest is None:

            lines.append(
                "  ↳ Sem alvos pendentes"
            )

        elif nearest["hit"]:

            lines.append(
                "  ↳ Alvo pendente já "
                "atingido/ultrapassado: "
                f"{format_price(ticker, nearest['target'])}"
            )

        else:

            if nearest["target"] > price:
                direction = "▲"
            else:
                direction = "▼"

            if nearest["move_pct"] is not None:

                pct = abs(
                    nearest["move_pct"]
                )

            else:

                pct = 0

            lines.append(
                "  ↳ Alvo mais próximo: "
                f"{format_price(ticker, nearest['target'])} "
                "| faltam "
                f"{format_price(ticker, nearest['distance'])} "
                f"({direction} {pct:.2f}%)"
            )

    if errors:

        lines.append("")

        lines.append(
            f"⚠️ {len(errors)} ativo(s) "
            f"sem cotação nesta execução:"
        )

        lines.append(
            ", ".join(
                sorted(errors)
            )
        )

    chunks = []
    current = ""

    for line in lines:

        if current:

            candidate = (
                f"{current}\n{line}"
            )

        else:

            candidate = line

        if len(candidate) > 3500:

            chunks.append(current)

            current = line

        else:

            current = candidate

    if current:

        chunks.append(current)

    for chunk in chunks:

        send_telegram(
            chunk,
            SUMMARY_CHAT_ID
        )


def send_test_message():

    now = datetime.now(BRT)

    send_telegram(
        (
            "✅ Bot de preços funcionando!\n"
            f"Teste realizado em "
            f"{now.strftime('%d/%m/%Y às %H:%M')} "
            "(Brasília).\n"
            "Resumo → chat principal\n"
            "Compras → grupo de compras\n"
            "Vendas → grupo de vendas "
            "quando configurado."
        ),
        SUMMARY_CHAT_ID
    )


def main():

    categories = load_alerts()

    mode = (
        os.getenv("BOT_MODE")
        or
        (
            sys.argv[1]
            if len(sys.argv) > 1
            else "alerts"
        )
    ).lower()

    if mode == "alerts":

        check_targets(categories)

    elif mode == "open":

        send_market_summary(
            categories,
            "Abertura do mercado"
        )

    elif mode == "close":

        send_market_summary(
            categories,
            "Fechamento do mercado"
        )

    elif mode == "test":

        send_test_message()

    else:

        raise ValueError(
            f"BOT_MODE inválido: {mode}"
        )


if __name__ == "__main__":
    main()
