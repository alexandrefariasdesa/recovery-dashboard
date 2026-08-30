# optout — bloquear / desbloquear disparo por API

Dois blocos no ManyChat: um joga a pessoa na base de bloqueio, o outro tira.
Quem está bloqueado **não recebe mais nenhuma mensagem disparada por API** —
nem recuperação (PIX, boleto, carrinho, boas-vindas) nem convite da aula.

Por que precisa de banco: quem manda essas mensagens não é um fluxo do
ManyChat, é a edge function chamando `sendFlow` de fora. Ela não lê custom
field do contato. O "não me mande mais nada" tem que morar num lugar que as
filas consultem — a tabela `public.optout` (migration `0018_optout.sql`).

## Montar no ManyChat

Um bloco de cada, dentro do fluxo que já fala com a pessoa (ex.: o botão
"não quero mais receber" da recuperação).

**BLOQUEAR** — ação **External Request**:

- Método: `POST`
- URL:
  `https://ztoghqjnctoreozoyvhh.supabase.co/functions/v1/optout?acao=bloquear&origem=recuperacao_pix&token=<OPTOUT_TOKEN>`
- Body: **Full Contact Data** (1 clique — traz telefone, id e nome)
- Response Mapping (opcional): campo `bloqueado` → custom field `optout` (Texto)

**DESBLOQUEAR** — o mesmo bloco, trocando **só** `acao=bloquear` por
`acao=desbloquear`.

`origem=` é livre e serve só pra saber de qual fluxo veio o toque (fica na
coluna `origem` e no `optout_log`). Copie o bloco entre fluxos trocando o slug.

Resposta:

```json
{ "ok": true, "bloqueado": "sim", "ja_estava": false, "telefone": "9294305962" }
```

`ja_estava` distingue o toque novo do repetido — dá pra usar numa Condition
pra responder "você já estava fora da lista" em vez de "pronto, bloqueei".

### Fail-closed (de propósito)

Se o banco estiver fora, o bloco devolve **502** e o ManyChat mostra erro. É o
contrário do `comprador-check`, que em caso de dúvida deixa passar: aqui é pior
a pessoa achar que bloqueou sem ter bloqueado. Se quiser tratar, ponha uma
Condition no `bloqueado` — vazio = não gravou, peça pra tocar de novo.

## O que muda no envio

| Onde | O que acontece com quem está bloqueado |
|---|---|
| `fila_recuperacao` | não aparece na fila (filtro direto) |
| `cancelar_recuperacoes_bloqueadas()` | os disparos já agendados viram `cancelado` / motivo `bloqueou`, visível no painel |
| `selecionar_convites_aula()` | não entra na base do dia da aula |
| `fila_convites_etapa()` | para de receber as etapas do dia (falta_1h, ao_vivo, comecamos) |

Desbloquear devolve o número pras filas. A linha **não é apagada** — fica
`bloqueado = false` com `desbloqueado_em`, e todo toque nos dois blocos vira
uma linha em `optout_log`. Isso é o que responde "recebeu mensagem depois de
ter bloqueado?" com data e hora.

O que já foi cancelado enquanto estava bloqueado **não volta**: desbloquear
libera dali pra frente, não ressuscita a fila antiga.

## Deploy

```bash
# 1) banco
psql "$PG_URL" -f db/migrations/0018_optout.sql

# 2) edge function (--no-verify-jwt: quem chama é o ManyChat, a auth é o ?token=)
npx supabase functions deploy optout --project-ref ztoghqjnctoreozoyvhh --no-verify-jwt

# 3) redeploy do disparo, que passou a chamar cancelar_recuperacoes_bloqueadas()
npx supabase functions deploy recuperacao-disparo --project-ref ztoghqjnctoreozoyvhh --no-verify-jwt
```

Secrets: usa `OPTOUT_TOKEN` se existir e cai pro `RECUP_TOKEN` / `CONVITE_TOKEN`
— dá pra subir sem criar segredo novo. Pra separar:

```bash
npx supabase secrets set OPTOUT_TOKEN=... --project-ref ztoghqjnctoreozoyvhh
```

Opcional — carimbar também um custom field no contato do ManyChat (pros fluxos
internos dele ramificarem sem consultar o banco):

```bash
npx supabase secrets set MC_OPTOUT_FIELD=optout --project-ref ztoghqjnctoreozoyvhh
```

Precisa do `MC_TOKEN` (já configurado) e do campo existindo na conta. Se falhar,
só vira log: o banco é a verdade, o campo é conveniência.

## Conferir / mexer na mão

```sql
select * from public.v_optout;                    -- quem está bloqueado agora
select * from public.optout_log order by id desc limit 20;   -- histórico

select public.optout_bloqueado('92994305962');    -- está bloqueado?
select public.optout_bloquear('92994305962', 'manual', 'pediu no direct');
select public.optout_desbloquear('92994305962', 'manual');
```

As funções normalizam o telefone com `phone_core` — pode passar com ou sem o
9, com ou sem o 55.
