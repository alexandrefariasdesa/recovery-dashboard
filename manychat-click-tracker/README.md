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

## 3. ManyChat — disparar no clique (receita à prova de erro)

Em **cada fluxo**, no botão do CTA (ex.: o "Verificar"), adicione a ação
**Solicitação externa** (External Request, Pro). O método que funciona sem
digitar JSON com tokens à mão:

1. **Tipo de Pedido:** `POST`
2. **Solicitar URL:** cole a URL do fluxo (tabela abaixo) — o `tipo` vai na
   própria URL como `&tipo=...`.
3. **Aba Corpo:** clique **"+ Adicionar Full Contact Data"** (1 clique). Isso
   manda `phone` e `id` do contato automaticamente — não precisa montar JSON.
4. **Cabeçalho:** não precisa (o Worker faz parse do JSON de qualquer jeito).
5. **Solicitação De Teste:** tem que voltar `200 OK` `{"ok":true,...}`.
6. **Salvar** → **Atualização** (publicar a automação).

URL por fluxo (token de `manychat-click-tracker/.dev.vars`):

| Fluxo no ManyChat | URL (cole inteira) |
|---|---|
| [PS] RECUPERAÇÃO DE CARRINHO | `…/click?token=SEU_TOKEN&tipo=carrinho_abandonado` |
| [PS] PIX E BOLETO GERADO | `…/click?token=SEU_TOKEN&tipo=pix_boleto_gerado` |
| [PS] PIX E BOLETO GERADO EXPIRADO | `…/click?token=SEU_TOKEN&tipo=pix_boleto_expirado` |
| (compra aprovada) | `…/click?token=SEU_TOKEN&tipo=compra_aprovada` |

Base: `https://manychat-click-tracker.alexandre-farias.workers.dev`

Tipos aceitos pelo Worker: `pix_boleto_gerado` · `pix_boleto_expirado` ·
`carrinho_abandonado` · `compra_aprovada` (+ os individuais pix/boleto, se um
dia separar os fluxos).

> O botão continua abrindo o link normalmente — a Solicitação externa é uma
> ação adicional no mesmo clique. Sem redirect.

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
