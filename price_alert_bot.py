import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


CONFIG_PATH = "alerts.json"

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

# Chat principal: abertura e fechamento
SUMMARY_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Grupo de compras
BUY_CHAT_ID = os.getenv("TELEGRAM_BUY_CHAT_ID") or SUMMARY_CHAT_ID

# Grupo de vendas será configurado depois.
# Enquanto não existir, usa o chat principal.
SELL_CHAT_ID = os.getenv("TELEGRAM_SELL_CHAT_ID") or SUMMARY_CHAT_ID

BRT = ZoneInfo("America/Sao_Paulo")


# =========================================================
# UTILIDADES
# =========================================================

def categories_only(data):
    """
    Retorna apenas as categorias que contêm listas de alertas.
    Permite adicionar metadados ao JSON futuramente sem quebrar o bot.
    """
    for category, alerts in data.items():
        if isinstance(alerts, list):
            yield category, alerts


def valid_market_value(value):
    """
    Remove valores inválidos vindos da API,
    principalmente 0, None, negativos etc.
    """
    if value is None:
        return False

    try:
        value = float(value)
    except (TypeError, ValueError):
        return False

    return value > 0


def sane_intraday_value(value, current_price):
    """
    Segunda proteção contra ticks absurdos da fonte de dados.

    Exemplo do problema encontrado:
    ITUB4 = R$ 49
    Yahoo retornou mínima = R$ 0,00

    Um valor intraday precisa ser positivo e razoavelmente
    relacionado ao preço atual.
    """
    if not valid_market_value(value):
        return False

    if not valid_market_value(current_price):
        return False

    value = float(value)
    current_price = float(current_price)

    # Proteção bastante ampla.
    # Aceita movimentos de até 80% para baixo
    # ou até 400% para cima no mesmo dia.
    minimum_reasonable = current_price * 0.20
    maximum_reasonable = current_price * 5.00

    return minimum_reasonable <= value <= maximum_reasonable


# =========================================================
# YAHOO FINANCE
# =========================================================

def get_quote(ticker, retries=3):
    """
    Busca:
    - preço atual
    - fechamento anterior
    - variação %
    - mínima do dia
    - máxima do dia

    Faz retry automático.
    """

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

            chart = data.get("chart") or {}
            results = chart.get("result") or []

            if not results:
                raise ValueError(
                    f"Yahoo não retornou dados para {ticker}"
                )

            result = results[0]
            meta = result.get("meta") or {}

            price = meta.get("regularMarketPrice")

            if not valid_market_value(price):
                raise ValueError(
                    f"Preço atual inválido para {ticker}: {price}"
                )

            price = float(price)

            previous_close = (
                meta.get("previousClose")
                or meta.get("chartPreviousClose")
            )

            if valid_market_value(previous_close):
                previous_close = float(previous_close)
            else:
                previous_close = None

            # -------------------------------------------------
            # PRIMEIRA OPÇÃO:
            # mínima/máxima oficial da sessão no metadata
            # -------------------------------------------------

            raw_day_low = meta.get("regularMarketDayLow")
            raw_day_high = meta.get("regularMarketDayHigh")

            day_low = None
            day_high = None

            if sane_intraday_value(raw_day_low, price):
                day_low = float(raw_day_low)

            if sane_intraday_value(raw_day_high, price):
                day_high = float(raw_day_high)

            # -------------------------------------------------
            # SEGUNDA OPÇÃO:
            # candles intraday de 5 minutos
            # -------------------------------------------------

            indicators = result.get("indicators") or {}
            quote_blocks = indicators.get("quote") or []

            if quote_blocks:

                quote_data = quote_blocks[0]

                raw_lows = quote_data.get("low") or []
                raw_highs = quote_data.get("high") or []

                # IMPORTANTE:
                # remove explicitamente zero, negativos, None
                # e qualquer valor absurdo.
                lows = []

                for value in raw_lows:

                    if sane_intraday_value(value, price):
                        lows.append(float(value))

                highs = []

                for value in raw_highs:

                    if sane_intraday_value(value, price):
                        highs.append(float(value))

                # Só usa candles caso metadata não tenha
                # uma mínima/máxima válida.
                if day_low is None and lows:
                    day_low = min(lows)

                if day_high is None and highs:
                    day_high = max(highs)

            # -------------------------------------------------
            # ÚLTIMA PROTEÇÃO
            # -------------------------------------------------

            if day_low is None:
                day_low = price

            if day_high is None:
                day_high = price

            # Nunca aceita 0 ou negativo.
            if day_low <= 0:
                day_low = price

            if day_high <= 0:
                day_high = price

            # Mínima não deve ser maior do que máxima.
            if day_low > day_high:
                print(
                    f"[AVISO] {ticker}: "
                    f"mínima/máxima inconsistentes. "
                    f"Usando preço atual."
                )

                day_low = price
                day_high = price

            change_pct = None

            if previous_close not in (None, 0):

                change_pct = (
                    (price - previous_close)
                    / previous_close
                ) * 100

            return {
                "price": price,
                "previous_close": previous_close,
                "change_pct": change_pct,
                "day_low": float(day_low),
                "day_high": float(day_high)
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
        f"Falha ao buscar {ticker} "
        f"após {retries} tentativas: {last_error}"
    )


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message, chat_id):
    """
    Envia mensagem ao Telegram.

    Só retorna sucesso caso a API confirme.
    """

    if not chat_id:
        raise ValueError(
            "Chat ID do Telegram não configurado."
        )

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
            f"Telegram não confirmou o envio: {result}"
        )

    return True


# =========================================================
# ALERTS.JSON
# =========================================================

def load_alerts():

    with open(
        CONFIG_PATH,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(file)


def save_alerts(data):
    """
    Salva de maneira atômica.

    Evita corromper alerts.json caso o processo
    seja interrompido no meio da escrita.
    """

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


# =========================================================
# FORMATAÇÃO
# =========================================================

def format_price(ticker, value):

    if ticker.endswith("-USD"):
        return f"US$ {value:,.2f}"

    return f"R$ {value:,.2f}"


# =========================================================
# TICKERS
# =========================================================

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
    """
    Consulta cada ticker somente UMA vez por execução.

    Todos os níveis daquele ativo usam a mesma cotação.
    """

    cache = {}
    errors = {}

    for _, ticker in unique_tickers(categories):

        try:

            cache[ticker] = get_quote(ticker)

        except Exception as error:

            errors[ticker] = str(error)

            print(
                f"[ERRO FINAL] "
                f"{ticker}: {error}"
            )

    return cache, errors


# =========================================================
# ALVO MAIS PRÓXIMO
# =========================================================

def nearest_pending_target(
    categories,
    ticker,
    current_price
):

    candidates = []

    for _, alerts in categories_only(categories):

        for alert in alerts:

            if alert.get("ticker") != ticker:
                continue

            if alert.get("triggered"):
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


# =========================================================
# COMPRA / VENDA
# =========================================================

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


# =========================================================
# VERIFICAÇÃO DOS ALVOS
# =========================================================

def hit_details(alert, quote):
    """
    Determina se o alvo foi atingido.

    Para compra:
    preço atual OU mínima válida do dia <= alvo.

    Para venda:
    preço atual OU máxima válida do dia >= alvo.
    """

    target = float(
        alert["target_price"]
    )

    condition = alert["condition"]

    current_price = quote["price"]
    day_low = quote["day_low"]
    day_high = quote["day_high"]

    # Proteção adicional.
    if not sane_intraday_value(
        day_low,
        current_price
    ):
        print(
            f"[AVISO] Mínima inválida ignorada: "
            f"{day_low}"
        )

        day_low = current_price

    if not sane_intraday_value(
        day_high,
        current_price
    ):
        print(
            f"[AVISO] Máxima inválida ignorada: "
            f"{day_high}"
        )

        day_high = current_price

    if condition == "below":

        if current_price <= target:

            return (
                True,
                current_price,
                "preço atual"
            )

        if day_low <= target:

            return (
                True,
                day_low,
                "mínima do dia"
            )

        return (
            False,
            day_low,
            "mínima do dia"
        )

    elif condition == "above":

        if current_price >= target:

            return (
                True,
                current_price,
                "preço atual"
            )

        if day_high >= target:

            return (
                True,
                day_high,
                "máxima do dia"
            )

        return (
            False,
            day_high,
            "máxima do dia"
        )

    else:

        raise ValueError(
            f"Condição inválida: {condition}"
        )


# =========================================================
# CHECK DOS ALERTAS
# =========================================================

def check_targets(categories):

    quote_cache, errors = build_quote_cache(
        categories
    )

    checked_alerts = 0
    sent_alerts = 0

    for category, alerts in categories_only(categories):

        for alert in alerts:

            # Já enviado anteriormente.
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
                    f"[ERRO] "
                    f"{ticker}: {error}"
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

                # Primeiro envia.
                send_telegram(
                    message,
                    alert_chat_id(alert)
                )

                # SOMENTE depois da confirmação
                # marca como disparado.
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

                # Salva imediatamente.
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


# =========================================================
# RESUMO DE ABERTURA / FECHAMENTO
# =========================================================

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

            if current:
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


# =========================================================
# TESTE
# =========================================================

def send_test_message():

    now = datetime.now(BRT)

    # Testa chat principal.
    send_telegram(
        (
            "✅ TESTE — CHAT PRINCIPAL\n"
            f"{now.strftime('%d/%m/%Y às %H:%M')} "
            "(Brasília)\n"
            "Este chat receberá abertura "
            "e fechamento."
        ),
        SUMMARY_CHAT_ID
    )

    # Testa grupo de compras.
    send_telegram(
        (
            "🟢 TESTE — ALERTAS DE COMPRA\n"
            f"{now.strftime('%d/%m/%Y às %H:%M')} "
            "(Brasília)\n"
            "Este grupo receberá os "
            "alertas de compra."
        ),
        BUY_CHAT_ID
    )


# =========================================================
# MAIN
# =========================================================

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
