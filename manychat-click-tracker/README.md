# manychat-click-tracker

Cloudflare Worker que registra o **clique nos botões das mensagens do ManyChat**
(compra aprovada, carrinho abandonado, pix expirado, pix gerado) numa aba do
Google Sheets. O dashboard lê essa aba e calcula CTR / efetividade por tipo.

```
Clique no botão (ManyChat)
  └─ ação "External Request" (POST)  →  este Worker  →  aba cliques_manychat
                                                          └─ dashboard cruza por telefone
```

## 1. Planilha — criar a aba

Na **mesma planilha** do `SPREADSHEET_ID` do dashboard, crie uma aba chamada
`cliques_manychat` com este cabeçalho na linha 1 (exatamente estes nomes):

| clicado_em | telefone | subscriber_id | tipo | url |
|------------|----------|---------------|------|-----|

E **compartilhe a planilha com o e-mail do service account** (o `client_email`
do `service_account.json`) como **Editor** — o dashboard só lê, mas o Worker
precisa escrever.

## 2. Deploy do Worker

```bash
cd manychat-click-tracker
npm install -g wrangler        # se ainda não tiver
wrangler login

# SHEET_ID pode ir no wrangler.toml [vars] OU como secret:
wrangler secret put SHEET_ID            # cole o id da planilha
wrangler secret put SA_EMAIL            # client_email do service_account.json
wrangler secret put SA_PRIVATE_KEY      # private_key do service_account.json (cole o bloco PEM inteiro)
wrangler secret put SHARED_TOKEN        # invente um segredo (ex.: uuid) — usado na URL

wrangler deploy
```

URL em produção: `https://manychat-click-tracker.alexandre-farias.workers.dev`.
Teste o health-check: `GET` nessa URL deve responder `{"ok":true,...}`.

> `SA_PRIVATE_KEY`: copie o valor de `"private_key"` do JSON. O Worker aceita
> tanto com `\n` escapado quanto com quebras de linha reais.

## 3. ManyChat — disparar no clique

Em **cada fluxo** (um por tipo de mensagem), no botão do CTA, adicione a ação
**External Request** (Pro):

- **Method:** `POST`
- **URL:** `https://manychat-click-tracker.alexandre-farias.workers.dev/click?token=SEU_SHARED_TOKEN`
  (o `SHARED_TOKEN` está em `manychat-click-tracker/.dev.vars`, fora do git)
- **Headers:** `Content-Type: application/json`
- **Body (JSON):**

```json
{
  "tipo": "pix_expirado",
  "telefone": "{{phone}}",
  "subscriber_id": "{{user_id}}",
  "url": ""
}
```

Troque o `"tipo"` conforme o fluxo. Valores aceitos:

`pix_gerado` · `pix_expirado` · `carrinho_abandonado` · `boleto_gerado` ·
`boleto_expirado` · `compra_aprovada`

> O botão continua abrindo o link normalmente (pix/checkout) — a External
> Request é uma ação adicional no mesmo clique. Não precisa de redirect.

## 4. Conferir

1. Clique num botão de teste no WhatsApp.
2. A aba `cliques_manychat` deve ganhar uma linha.
3. No dashboard, aba **📣 Efetividade ManyChat**, o clique aparece no período
   (botão 🔄 Atualizar limpa o cache de 5 min).

## Respostas do Worker

| status | significado |
|--------|-------------|
| `200`  | gravado (`{"ok":true,...}`) |
| `401`  | token errado/ausente |
| `400`  | tipo inválido ou sem telefone/subscriber_id |
| `502`  | falha ao gravar no Sheets (cheque compartilhamento/secrets) |
