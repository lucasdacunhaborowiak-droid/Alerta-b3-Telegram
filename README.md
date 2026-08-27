# Alerta de Preço B3 → Telegram (grátis e sem limite de alertas)

Este projeto verifica os preços de ativos da B3 (via Yahoo Finance) e te avisa
no Telegram quando um preço-alvo é atingido. Roda automaticamente na nuvem
pelo GitHub Actions — você não precisa deixar nenhum computador ligado.

## Passo 1 — Criar o bot no Telegram

1. Abra o Telegram e procure por **@BotFather**.
2. Envie `/start`, depois `/newbot`.
3. Escolha um nome e um username (precisa terminar em `bot`, ex: `MeuAlertaB3Bot`).
4. O BotFather vai te dar um **token** (algo como `123456789:ABCdefGhIJKlmNoPQRstuVwxYZ`).
   Guarde esse token.

## Passo 2 — Descobrir seu Chat ID

1. Procure pelo bot que você acabou de criar (pelo username) e envie qualquer
   mensagem para ele (ex: "oi").
2. No navegador, acesse (troque `SEU_TOKEN` pelo token do passo 1):
   `https://api.telegram.org/botSEU_TOKEN/getUpdates`
3. Procure no resultado por `"chat":{"id":` — o número depois disso é o seu
   **Chat ID**.

## Passo 3 — Criar o repositório no GitHub

1. Crie uma conta grátis em https://github.com (se ainda não tiver).
2. Crie um novo repositório (pode ser privado).
3. Suba estes arquivos para o repositório (pelo site mesmo, arrastando os
   arquivos em "Add file → Upload files", ou via git).

## Passo 4 — Configurar os segredos (token e chat id)

1. No repositório, vá em **Settings → Secrets and variables → Actions**.
2. Clique em **New repository secret** e crie:
   - Nome: `TELEGRAM_TOKEN` — valor: o token do Passo 1
   - Nome: `TELEGRAM_CHAT_ID` — valor: o chat id do Passo 2

Esses valores ficam criptografados, ninguém mais tem acesso.

## Passo 5 — Editar seus alertas

O arquivo `alerts.json` é organizado por **categorias** (seções). Cada
categoria é uma chave, e dentro dela fica a lista de alertas daquele grupo.
Exemplo:

```json
{
  "Acoes Brasil": [
    {
      "ticker": "PETR4.SA",
      "target_price": 40.00,
      "condition": "above",
      "triggered": false
    }
  ],
  "Crypto": [
    {
      "ticker": "BTC-USD",
      "target_price": 60000,
      "condition": "below",
      "triggered": false
    }
  ]
}
```

- **Nome da categoria** (ex: `"Acoes Brasil"`, `"Crypto"`, `"FIIs"`): pode ser
  qualquer texto — esse nome aparece na mensagem do Telegram quando o alerta
  dispara.
- `ticker`: código do ativo + `.SA` para ativos da B3 (ex: `PETR4.SA`,
  `VALE3.SA`, `BOVA11.SA`, `ITUB4.SA`) — ou `BTC-USD` para Bitcoin (formato
  do Yahoo Finance para cripto).
- `target_price`: preço-alvo.
- `condition`: `"above"` (avisa quando o preço subir até esse valor ou mais)
  ou `"below"` (avisa quando cair até esse valor ou menos).
- `triggered`: sempre comece com `false`. O robô muda para `true` sozinho
  depois de disparar, para não te avisar toda hora repetindo o mesmo alerta.
  Se quiser reativar um alerta, volte o valor para `false`.

Para criar uma nova categoria, é só copiar um bloco `"Nome da Categoria": [ ... ]`
inteiro e colar com os dados novos. Dentro de cada categoria, você pode ter
quantos alertas quiser, sem limite nenhum.

## Passo 6 — Ativar e testar

1. Vá na aba **Actions** do repositório.
2. Se aparecer um aviso pedindo para habilitar workflows, clique para habilitar.
3. Clique no workflow **"Verificar Alertas de Preço B3"** → **Run workflow**
   (botão manual) para testar na hora, sem esperar o agendamento.
4. Se tudo estiver certo, você recebe a mensagem no Telegram assim que um
   alvo for atingido.

Depois disso, ele roda sozinho a cada 15 minutos, de segunda a sexta, das
10h às 18h (horário de Brasília) — cobrindo o pregão da B3.

## Dúvidas comuns

- **Preciso pagar algo?** Não. GitHub Actions e Telegram Bot API são
  gratuitos para esse uso.
- **Posso rodar fora do horário do pregão?** Sim, edite o `cron` no arquivo
  `.github/workflows/check_alerts.yml`.
- **Não sei mexer em git, como subo os arquivos?** Pelo próprio site do
  GitHub: abra o repositório → "Add file" → "Upload files" → arraste os
  arquivos → "Commit changes".
