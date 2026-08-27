# Novas funções do bot

O bot agora possui quatro modos:

- `alerts`: verifica seus preços-alvo e envia mensagem apenas quando um alvo é atingido.
- `open`: envia um resumo de abertura com cada ticker uma única vez.
- `close`: envia um resumo de fechamento com cada ticker uma única vez.
- `test`: envia imediatamente uma mensagem de teste para confirmar que Telegram Token e Chat ID estão funcionando.

## Testar no GitHub

1. Abra seu repositório.
2. Vá em **Actions**.
3. Abra **Verificar Alertas de Preço B3**.
4. Clique em **Run workflow**.
5. Em `mode`, escolha **test**.
6. Clique em **Run workflow** novamente.

Você deverá receber no Telegram:

`✅ Bot de preços funcionando!`

## Horários automáticos

- Alertas de preço: a cada 15 minutos durante o período configurado.
- Resumo de abertura: 10:10, horário de Brasília, de segunda a sexta.
- Resumo de fechamento: 17:55, horário de Brasília, de segunda a sexta.

> Observação: o GitHub Actions usa UTC, por isso os horários no arquivo YAML aparecem 3 horas à frente.
