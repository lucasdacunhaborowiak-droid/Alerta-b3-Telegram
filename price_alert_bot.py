

def send_market_summary(categories, label):
    now = datetime.now(BRT)
    lines = [f"📊 {label} — {now.strftime('%d/%m/%Y às %H:%M')}"]

    quote_cache, errors = build_quote_cache(categories)

    current_category = None

    for category, ticker in unique_tickers(categories):
        if category != current_category:
            lines.append("")
            lines.append(category)
            current_category = category

        quote = quote_cache.get(ticker)

        if quote is None:
            lines.append(f"• {ticker}: indisponível")
            continue

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
                f"  ↳ Alvo pendente já atingido/ultrapassado: "
                f"{format_price(ticker, nearest['target'])}"
            )
        else:
            direction = "▲" if nearest["target"] > price else "▼"
            pct = abs(nearest["move_pct"]) if nearest["move_pct"] is not None else 0
            lines.append(
                f"  ↳ Alvo mais próximo: {format_price(ticker, nearest['target'])} "
                f"| faltam {format_price(ticker, nearest['distance'])} "
                f"({direction} {pct:.2f}%)"
            )

    if errors:
        lines.append("")
        lines.append(f"⚠️ {len(errors)} ativo(s) sem cotação nesta execução:")
        lines.append(", ".join(sorted(errors)))

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
        send_telegram(chunk, SUMMARY_CHAT_ID)


def send_test_message():
    now = datetime.now(BRT)

    send_telegram(
        "✅ Bot de preços funcionando!\n"
        f"Teste realizado em {now.strftime('%d/%m/%Y às %H:%M')} (Brasília).\n"
        "Resumo → chat principal\n"
        "Compras → grupo de compras\n"
        "Vendas → grupo de vendas quando configurado.",
        SUMMARY_CHAT_ID,
    )


def main():
    categories = load_alerts()
    mode = (
        os.getenv("BOT_MODE")
        or (sys.argv[1] if len(sys.argv) > 1 else "alerts")
    ).lower()

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
