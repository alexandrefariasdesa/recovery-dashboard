# recovery-flow-tracker

Cloudflare Worker que registra **cada etapa dentro do fluxo do ManyChat**
(recebeu → entrou → engajou) para os 4 fluxos da Luiza: PIX/Boleto Gerado,
PIX/Boleto Expirado, Carrinho Abandonado e Boas-vindas. Grava numa aba do
Google Sheets; o dashboard lê essa aba e calcula o funil por fluxo.

```
Cada etapa do fluxo (ManyChat)
  └─ ação "External Request" (POST)  →  este Worker  →  aba eventos_manychat
                                                          └─ dashboard calcula o funil
```

Isso é **complementar** à aba "📣 Efetividade ManyChat" que já existe (essa
mede clique→venda via `manychat-click-tracker`); a aba nova ("🧭 Funil de
Etapas ManyChat") mede só o quanto a pessoa avança dentro do próprio fluxo.

## 1. Planilha — aba já criada

A aba `eventos_manychat` já foi criada na mesma planilha do dashboard
(`SPREADSHEET_ID`), com o cabeçalho:

| ts | telefone | subscriber_id | fluxo | etapa |
|----|----------|----------------|-------|-------|

A planilha já está compartilhada com o service account como Editor (mesmo
usado pelo `manychat-click-tracker`) — nada a fazer aqui.

## 2. Deploy do Worker

```bash
cd recovery-flow-tracker
npm install -g wrangler        # se ainda não tiver
wrangler login
bash deploy.sh
```

O script lê `.dev.vars` (SHARED_TOKEN + SHEET_ID) e `../service_account.json`,
faz `wrangler deploy` e injeta os 4 secrets. URL esperada:
`https://recovery-flow-tracker.alexandre-farias.workers.dev`.

Teste o health-check: `GET` nessa URL deve responder `{"ok":true,...}`.

## 3. ManyChat — os 12 tijolos (4 fluxos × 3 etapas)

Em **cada um dos 4 fluxos**, adicione **3 tijolos de External Request (POST)**
— um em cada ponto do funil (recebimento da mensagem, botão de entrada, e o
clique/ação seguinte que conta como "engajou"):

1. **Tipo de Pedido:** `POST`
2. **Solicitar URL:** cole a URL da tabela abaixo (uma por etapa/fluxo).
3. **Aba Corpo:** clique **"+ Adicionar Full Contact Data"** (1 clique) —
   manda `phone`/`id` automaticamente, sem montar JSON.
4. **Cabeçalho:** não precisa.
5. **Solicitação De Teste:** tem que voltar `200 OK` `{"ok":true,...}`.
6. **Salvar** → **Atualização** (publicar a automação).

Base do Worker: `https://recovery-flow-tracker.alexandre-farias.workers.dev`
(token de `.dev.vars`, trocar `SEU_TOKEN` pelo valor real).

| Fluxo no ManyChat | Etapa | URL (cole inteira) |
|---|---|---|
| PIX/Boleto Gerado | recebeu | `…/event?token=SEU_TOKEN&fluxo=pix_boleto_gerado&etapa=recebeu` |
| PIX/Boleto Gerado | entrou | `…/event?token=SEU_TOKEN&fluxo=pix_boleto_gerado&etapa=entrou` |
| PIX/Boleto Gerado | engajou | `…/event?token=SEU_TOKEN&fluxo=pix_boleto_gerado&etapa=engajou` |
| PIX/Boleto Expirado | recebeu | `…/event?token=SEU_TOKEN&fluxo=pix_boleto_expirado&etapa=recebeu` |
| PIX/Boleto Expirado | entrou | `…/event?token=SEU_TOKEN&fluxo=pix_boleto_expirado&etapa=entrou` |
| PIX/Boleto Expirado | engajou | `…/event?token=SEU_TOKEN&fluxo=pix_boleto_expirado&etapa=engajou` |
| Carrinho Abandonado | recebeu | `…/event?token=SEU_TOKEN&fluxo=carrinho_abandonado&etapa=recebeu` |
| Carrinho Abandonado | entrou | `…/event?token=SEU_TOKEN&fluxo=carrinho_abandonado&etapa=entrou` |
| Carrinho Abandonado | engajou | `…/event?token=SEU_TOKEN&fluxo=carrinho_abandonado&etapa=engajou` |
| Boas-vindas | recebeu | `…/event?token=SEU_TOKEN&fluxo=boas_vindas&etapa=recebeu` |
| Boas-vindas | entrou | `…/event?token=SEU_TOKEN&fluxo=boas_vindas&etapa=entrou` |
| Boas-vindas | engajou | `…/event?token=SEU_TOKEN&fluxo=boas_vindas&etapa=engajou` |

Erro comum: esquecer de trocar `&fluxo=` ou `&etapa=` ao copiar o tijolo entre
etapas/fluxos.

> O botão continua funcionando normalmente — a Solicitação externa é uma ação
> adicional no mesmo clique/gatilho. Sem redirect.

## 4. Conferir

1. Dispare/clique num ponto de teste no WhatsApp (ou use "Solicitação De Teste").
2. A aba `eventos_manychat` deve ganhar uma linha por tijolo.
3. No dashboard, aba **🧭 Funil de Etapas ManyChat**, escolha o fluxo e veja o
   funil (botão 🔄 Atualizar limpa o cache de 5 min).

## Respostas do Worker

| status | significado |
|--------|-------------|
| `200`  | gravado (`{"ok":true,...}`) |
| `401`  | token errado/ausente |
| `400`  | `fluxo` ausente, `etapa` inválida ou sem telefone/subscriber_id |
| `502`  | falha ao gravar no Sheets (cheque compartilhamento/secrets) |
