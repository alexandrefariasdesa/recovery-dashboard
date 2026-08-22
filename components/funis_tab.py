"""
components/funis_tab.py
================================================================================
As telas de Aquisição, Boas-vindas e Grupo.

Mesma gramática nas três, pra o painel não parecer três produtos: uma faixa de
números no topo (o que aconteceu), um gráfico de ritmo (quando aconteceu), um
corte por categoria (onde aconteceu) e a base no fim (quem). Quem aprende a ler
uma, lê as outras.

Cor: verde-pix é o que deu certo, ardósia é o que não aconteceu — a mesma
convenção do resto do painel, definida em components/theme.py.
"""
import pandas as pd
import plotly.express as px
import streamlit as st

from components.theme import ARDOSIA, PIX

_GRUPO_DESDE = pd.Timestamp("2026-08-22 13:16")


def _reais(v):
    return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _br(v):
    return f"{int(v):,}".replace(",", ".")


def _layout(fig, altura=280):
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=altura,
                      legend_title_text="")
    return fig


# ── Aquisição ────────────────────────────────────────────────────────────────

def render_aquisicao(data: dict) -> None:
    df = data["base"]
    st.caption(
        "Venda de entrada (`tipo = front`). O upsell tem página própria — somar "
        "os dois aqui faria a mesma cliente contar duas vezes."
    )
    if df is None or df.empty:
        st.info("Nenhuma compra de entrada no período.")
        return

    receita, n = data["receita"], data["compradoras"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Receita", _reais(receita))
    c2.metric("Compradoras", _br(n))
    c3.metric("Ticket médio", _reais(receita / n) if n else "—")

    diario = data["diario"]
    if not diario.empty:
        esq, dir_ = st.columns(2)
        with esq:
            st.subheader("Receita por dia")
            st.plotly_chart(_layout(px.bar(
                diario, x="dia", y="receita", text_auto=".2s",
                labels={"dia": "", "receita": "R$"},
                color_discrete_sequence=[PIX])), use_container_width=True)
        with dir_:
            st.subheader("Ticket médio por dia")
            st.plotly_chart(_layout(px.line(
                diario, x="dia", y="ticket", markers=True,
                labels={"dia": "", "ticket": "R$"},
                color_discrete_sequence=[PIX])), use_container_width=True)

    faixas = data["faixas"]
    if not faixas.empty:
        st.subheader("Distribuição por valor pago")
        st.caption(
            "O valor da compra já vem com o order bump embutido (a Payt manda o "
            "total), então esta é a leitura mais próxima do mix de bump que existe "
            "no banco hoje."
        )
        vista = faixas.head(12).copy()
        vista["valor"] = vista["valor"].map(_reais)
        st.dataframe(vista.rename(columns={"valor": "Valor pago",
                                           "compradoras": "Compradoras"}),
                     hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("Base de compras")
    vista = df[["compra_em", "nome", "email", "telefone", "valor", "produto"]].copy()
    vista["valor"] = vista["valor"].map(_reais)
    st.dataframe(vista.rename(columns={
        "compra_em": "Compra", "nome": "Nome", "email": "E-mail",
        "telefone": "Telefone", "valor": "Valor", "produto": "Produto"}),
        hide_index=True, use_container_width=True)


# ── Boas-vindas ──────────────────────────────────────────────────────────────

def render_boas_vindas(data: dict) -> None:
    df, cfg = data["base"], data["config"]
    st.caption(
        "O que o motor fez com cada compra aprovada. Enquanto o modo for "
        "`simulado`, ele registra o que mandaria e quem fala com a cliente "
        "continua sendo o cenário de compra aprovada no Make."
    )

    if not cfg.empty:
        modos = " · ".join(f"`{r['tipo']}` **{r['modo']}**" for _, r in cfg.iterrows())
        st.markdown(modos)

    if df is None or df.empty:
        st.info("Nenhuma compra atendida pelo motor no período.")
        return

    enviados = int((df["status"] == "enviado").sum())
    simulados = int((df["status"] == "simulado").sum())
    erros = int((df["status"] == "erro").sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Compras atendidas", _br(len(df)))
    c2.metric("Enviadas de verdade", _br(enviados))
    c3.metric("Simuladas", _br(simulados))
    c4.metric("Erros", _br(erros))

    if erros == 0 and enviados == 0:
        st.info(
            "Zero envio real e zero erro é o resultado esperado do modo simulado: "
            "a cadeia inteira roda (agenda, casa o produto, renderiza), só não "
            "entrega. É o que permite comparar com o Make antes de virar a chave."
        )

    quadro = data["quadro"]
    if not quadro.empty:
        st.subheader("Por tipo e status")
        st.dataframe(quadro, hide_index=True, use_container_width=True)

    diario = data["diario"]
    if not diario.empty:
        st.subheader("Ritmo por dia")
        st.plotly_chart(_layout(px.bar(
            diario, x="dia", y="n", color="status", text_auto=True,
            labels={"dia": "", "n": "disparos"},
            color_discrete_map={"enviado": PIX, "simulado": "#B87400",
                                "cancelado": ARDOSIA, "erro": "#C5303A"})),
            use_container_width=True)

    atraso = df["atraso_min"].dropna()
    if not atraso.empty:
        st.caption(
            f"Atraso entre a hora marcada e o disparo: mediana de "
            f"**{atraso.median():.1f} min**, máximo de **{atraso.max():.1f} min**. "
            "O cron drena de 2 em 2 minutos, então o atraso configurado é um piso."
        )

    st.divider()
    st.subheader("Base")
    vista = df[["criado_em", "tipo", "status", "motivo", "nome", "produto", "valor"]].copy()
    st.dataframe(vista.rename(columns={
        "criado_em": "Criado", "tipo": "Tipo", "status": "Status",
        "motivo": "Motivo", "nome": "Nome", "produto": "Produto", "valor": "Valor"}),
        hide_index=True, use_container_width=True)


# ── Grupo ────────────────────────────────────────────────────────────────────

def render_grupo(data: dict) -> None:
    entradas = data["entradas"]
    compradoras = data["compradoras"]

    st.caption(
        "Entrada nos grupos de WhatsApp, vinda do endpoint `/grupo` (SendFlow → "
        "worker → banco). A planilha antiga saiu de cena: ela parou de receber "
        "em 15/07/2026 e fazia todo mundo aparecer como *não entrou*."
    )

    if not compradoras.empty and compradoras["compra_em"].min() < _GRUPO_DESDE:
        st.warning(
            f"Taxa **subestimada** neste período: o registro só existe a partir de "
            f"{_GRUPO_DESDE:%d/%m/%Y %H:%M}. Compras anteriores contam como *não "
            "entrou* por falta de registro, não por falta de entrada."
        )

    total_entradas = 0 if entradas is None or entradas.empty else len(entradas)
    if compradoras is None or compradoras.empty:
        n_compradoras = entraram = 0
    else:
        n_compradoras = len(compradoras)
        entraram = int(compradoras["entrou"].sum())
    taxa = entraram / n_compradoras * 100 if n_compradoras else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Entradas no período", _br(total_entradas))
    c2.metric("Compradoras", _br(n_compradoras))
    c3.metric("Entraram no grupo", _br(entraram))
    c4.metric("Taxa de entrada", f"{taxa:.1f}%")

    if total_entradas == 0:
        st.info(
            "Nenhuma entrada registrada no período. Se o SendFlow estiver "
            "disparando, confira o webhook do evento `group.updated.members.added`."
        )

    por_campanha = data["por_campanha"]
    if not por_campanha.empty:
        st.subheader("Entradas por campanha e grupo")
        st.caption(
            "A campanha é a que o SendFlow reporta na entrada — responde *qual "
            "campanha encheu o grupo*, não qual campanha vendeu."
        )
        st.dataframe(por_campanha.rename(columns={
            "campanha": "Campanha", "grupo": "Grupo", "entradas": "Entradas"}),
            hide_index=True, use_container_width=True)

    taxa_diaria = data["taxa_diaria"]
    if not taxa_diaria.empty:
        esq, dir_ = st.columns(2)
        with esq:
            st.subheader("Compradoras por dia")
            empilhado = taxa_diaria.melt(
                id_vars="dia", value_vars=["entraram", "compradoras"],
                var_name="serie", value_name="n")
            st.plotly_chart(_layout(px.bar(
                empilhado, x="dia", y="n", color="serie", barmode="overlay",
                labels={"dia": "", "n": ""},
                color_discrete_map={"entraram": PIX, "compradoras": ARDOSIA})),
                use_container_width=True)
        with dir_:
            st.subheader("Taxa de entrada por dia")
            st.plotly_chart(_layout(px.line(
                taxa_diaria, x="dia", y="taxa", markers=True,
                labels={"dia": "", "taxa": "%"},
                color_discrete_sequence=[PIX])), use_container_width=True)

    if not entradas.empty:
        st.divider()
        st.subheader("Entradas registradas")
        vista = entradas[["entrou_em", "campanha", "grupo", "telefone"]].copy()
        st.dataframe(vista.rename(columns={
            "entrou_em": "Entrou em", "campanha": "Campanha",
            "grupo": "Grupo", "telefone": "Telefone"}),
            hide_index=True, use_container_width=True)
