# Deploy no Railway

O painel é um Streamlit. O Railway usa Nixpacks: detecta o `requirements.txt`,
instala e roda o `startCommand` do `railway.json` (o `Procfile` diz a mesma
coisa, pra quem preferir ler por ali).

Health check: `/_stcore/health`.

## Variáveis de ambiente

Tudo que hoje mora em `.streamlit/secrets.toml` vira variável no serviço. O
`config.py` lê `st.secrets` primeiro e cai pro ambiente — então as duas formas
funcionam, e não é preciso mexer em código.

| Variável | Pra quê | Obrigatória |
|---|---|---|
| `APP_PASSWORD` | Senha única de acesso. **Sem ela o painel abre pra qualquer um** — a URL do Railway é pública. | sim |
| `USE_POSTGRES` | `1` pra ler do Supabase em vez do Sheets. | sim |
| `PG_HOST` `PG_PORT` `PG_USER` `PG_PASSWORD` `PG_DBNAME` | Conexão com o Postgres do Supabase (pooler, porta 6543). | sim |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Conteúdo **inteiro** do `service_account.json`, numa linha só. Substitui o arquivo, que não existe no container. | só se alguma aba ainda ler do Sheets |
| `SPREADSHEET_ID` `COMPRADORES_SPREADSHEET_ID` `GRUPO_SPREADSHEET_ID` `COMPRADORES_TAB` | Planilhas das abas que ainda não migraram. | idem |
| `SENDFLOW_TOKEN` `SENDFLOW_BASE_URL` `SENDFLOW_ACCOUNT_ID` `SENDFLOW_GROUP_ID` | Integração SendFlow. | se usar |
| `LOW_TICKET_PRODUCT` | Nome do produto low ticket. | não (tem padrão) |

Os valores estão no `.env.supabase` e no `.streamlit/secrets.toml` — nenhum dos
dois vai pro git.

## Passo a passo

```bash
railway login                  # abre o navegador; roda você mesmo
railway link                   # escolhe o projeto que já existe
railway up                     # sobe o serviço
railway variables --set APP_PASSWORD=...   # e as demais
railway domain                 # gera a URL pública
```

Depois de subir, confirme no log que apareceu `You can now view your Streamlit
app` e abra a URL: deve pedir a senha antes de mostrar qualquer dado.

## Backup do banco (pendente)

O plano free do Supabase **não tem backup automático**, e a fila de recuperação
e o controle de quem recebeu o quê vivem lá. A saída barata é um cron job no
próprio Railway rodando `pg_dump` diário contra o Supabase e guardando o
arquivo. Não está montado ainda.
