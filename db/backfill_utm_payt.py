"""
db/backfill_utm_payt.py
================================================================================
Preenche a origem (`compras.utm`) das vendas anteriores à captura, a partir do
relatório de vendas exportado do painel da Payt.

Por que existe: o webhook só passou a guardar a origem em 31/08/2026. Tudo que
foi vendido antes disso está no banco sem `utm`, e sem origem não dá para dizer
quais vendas vieram do fluxo de boas-vindas do Instagram — que é a pergunta que
a página "Boas-vindas Instagram" existe para responder.

O relatório da Payt traz a coluna **"Source / Venda Manual"**, que é o mesmo
`src` que o webhook lê de `link.sources.src`. O casamento é pelo **"Código"** do
pedido, que é o `transaction_id` da nossa tabela.

Uso:
    python db/backfill_utm_payt.py caminho/vendas.xlsx           # DRY-RUN
    python db/backfill_utm_payt.py caminho/vendas.xlsx --apply   # grava

Só preenche linha com `utm` nulo — nunca sobrescreve o que o webhook capturou,
que é mais rico (traz utm_source, utm_campaign e companhia, não só o src).
Idempotente: rodar de novo com o mesmo arquivo não muda nada.
"""
import io
import sys

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

COL_CODIGO = "Código"
COL_SOURCE = "Source / Venda Manual"
# O pandas representa célula vazia de formas diferentes conforme o dtype da
# coluna (`nan`, `NaN`, `<NA>`, `None`). Descartar os nulos ANTES de converter
# para texto é o que resolve de verdade; a lista abaixo é só o cinto de
# segurança para quando a própria planilha traz a palavra escrita.
VAZIOS = {"", "nan", "none", "null", "<na>", "na", "-"}


def _credenciais() -> dict:
    env = {}
    for arquivo in (".env", ".env.supabase"):
        try:
            for linha in io.open(arquivo, encoding="utf-8"):
                linha = linha.strip()
                if linha and not linha.startswith("#") and "=" in linha:
                    chave, valor = linha.split("=", 1)
                    env[chave.strip()] = valor.strip()
        except FileNotFoundError:
            pass
    return env


def _conectar():
    env = _credenciais()
    return psycopg2.connect(
        host=env.get("PG_HOST", "aws-0-sa-east-1.pooler.supabase.com"),
        port=int(env.get("PG_PORT", 6543)),
        user=env["PG_USER"],
        password=env.get("PG_PASSWORD") or env["SUPABASE_DB_PASSWORD"],
        dbname=env.get("PG_DBNAME", "postgres"),
        connect_timeout=60,
    )


def ler_export(caminho: str) -> pd.DataFrame:
    df = (pd.read_excel(caminho, sheet_name="report")
          if caminho.lower().endswith((".xlsx", ".xls"))
          else pd.read_csv(caminho))
    df.columns = [str(c).strip() for c in df.columns]
    faltando = [c for c in (COL_CODIGO, COL_SOURCE) if c not in df.columns]
    if faltando:
        raise SystemExit(f"colunas ausentes no export: {faltando}\ntem: {list(df.columns)}")

    d = df[[COL_CODIGO, COL_SOURCE]].copy()
    d.columns = ["codigo", "src"]
    d = d.dropna(subset=["codigo", "src"])
    for col in ("codigo", "src"):
        d[col] = d[col].astype(str).str.strip()
    vazio = d["src"].str.lower().isin(VAZIOS) | d["codigo"].str.lower().isin(VAZIOS)
    d = d[~vazio]
    return d.drop_duplicates("codigo")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    caminho = sys.argv[1]
    aplicar = "--apply" in sys.argv

    d = ler_export(caminho)
    print(f"export: {len(d)} pedidos com origem preenchida")
    print(d["src"].value_counts().head(10).to_string())

    conn = _conectar()
    cur = conn.cursor()
    cur.execute("create temp table _src_export (codigo text primary key, src text)")
    execute_values(cur, "insert into _src_export (codigo, src) values %s on conflict do nothing",
                   list(d.itertuples(index=False, name=None)), page_size=1000)

    cur.execute("""
        select count(*) from compras c join _src_export e on c.transaction_id = e.codigo
        where c.utm is null
    """)
    alvo = cur.fetchone()[0]
    print(f"\ncompras no banco sem origem que casam com o export: {alvo}")

    if not aplicar:
        print("DRY-RUN — rode com --apply para gravar.")
        conn.rollback()
        return

    cur.execute("""
        update compras c set utm = jsonb_build_object('src', e.src)
        from _src_export e
        where c.transaction_id = e.codigo and c.utm is null
    """)
    print(f"linhas preenchidas: {cur.rowcount}")
    conn.commit()

    cur.execute("""
        select utm ->> 'src', count(*), round(sum(valor), 2)
        from compras where utm is not null group by 1 order by 2 desc limit 10
    """)
    print("\norigem            compras      receita")
    for src, n, receita in cur.fetchall():
        print(f"{(src or '—')[:20]:<20} {n:>6}  {float(receita or 0):>11.2f}")
    conn.close()


if __name__ == "__main__":
    main()
