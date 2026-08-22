import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import config


# A entrada em grupo passou a vir do endpoint /grupo (worker → `grupo_entradas`)
# em 22/08/2026. Antes disso não existe registro no banco: a planilha antiga
# parou em 15/07 e não foi importada. Sem essa data à vista, um período anterior
# mostraria 0% e pareceria que ninguém entra em grupo.
_GRUPO_DESDE = pd.Timestamp("2026-08-22 13:16")


def render_upsell_tab(df: pd.DataFrame) -> None:
    st.caption(
        f"Produto rastreado: **{config.LOW_TICKET_PRODUCT}** · entrada em grupo e "
        "upsell vêm do banco (endpoint `/grupo` e webhook da Payt)."
    )

    if df is None or df.empty:
        st.info(f"Nenhum comprador encontrado para '{config.LOW_TICKET_PRODUCT}' no período selecionado.")
        return

    total_compradores = len(df)
    entradas_grupo = int(df["entrou_no_grupo"].sum())
    nao_entrou = total_compradores - entradas_grupo
    taxa_conversao = (entradas_grupo / total_compradores * 100) if total_compradores > 0 else 0.0
    receita_low = df["valor"].sum()

    # ── Métricas principais ──────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Compradores", total_compradores)
    c2.metric("Entraram no Grupo", entradas_grupo)
    c3.metric("Não Entraram", nao_entrou)
    c4.metric("Taxa de Entrada no Grupo", f"{taxa_conversao:.1f}%")

    # Taxa baixa pode ser "pouca gente entrou" ou "a fonte ainda não cobria esse
    # período". São coisas muito diferentes pra deixar o painel calado — e o
    # segundo caso vale pra QUALQUER período que comece antes da virada, não só
    # pros que deram zero.
    if df["compra_em"].min() < _GRUPO_DESDE:
        st.warning(
            "Taxa **subestimada** neste período: a entrada em grupo só é "
            f"registrada no banco a partir de {_GRUPO_DESDE:%d/%m/%Y %H:%M}, "
            "quando o SendFlow passou a postar no endpoint `/grupo`. Compras "
            "anteriores aparecem como *não entrou* por falta de registro, não "
            "por falta de entrada — a planilha antiga parou em 15/07 e não foi "
            "importada. Para uma leitura limpa, escolha um período que comece "
            "depois dessa data."
        )

    # ── Upsell ───────────────────────────────────────────────────────────────
    if "upsells" in df.columns:
        com_upsell = int((df["upsells"] > 0).sum())
        take_rate = (com_upsell / total_compradores * 100) if total_compradores else 0.0
        receita_upsell = float(df["valor_upsell"].sum())
        ticket_medio = float(df["ticket_total"].mean())
        u1, u2, u3, u4 = st.columns(4)
        u1.metric("Levaram Upsell", com_upsell)
        u2.metric("Take-rate de Upsell", f"{take_rate:.1f}%")
        u3.metric("Receita de Upsell", f"R$ {receita_upsell:,.2f}")
        u4.metric("Ticket Médio Real", f"R$ {ticket_medio:,.2f}",
                  help="Compra de entrada + upsells dos 7 dias seguintes.")
        if receita_upsell == 0:
            st.caption(
                "Nenhum upsell no período. Só entra aqui a oferta que tiver a URL "
                "`&evento=aprovado&venda=upsell` cadastrada na Payt."
            )

    st.divider()

    col_left, col_right = st.columns(2)

    # ── Funil ────────────────────────────────────────────────────────────────
    with col_left:
        st.subheader("Funil de Entrada no Grupo")
        fig_funnel = go.Figure(go.Funnel(
            y=["Compradores", "Entraram no Grupo"],
            x=[total_compradores, entradas_grupo],
            textinfo="value+percent initial",
            marker={"color": ["#64748B", "#00A98F"]},
        ))
        fig_funnel.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300)
        st.plotly_chart(fig_funnel, use_container_width=True)

    # ── Pizza entrada vs não entrou ──────────────────────────────────────────
    with col_right:
        st.subheader("Entradas no Grupo")
        pie_df = pd.DataFrame({
            "Status": ["Entraram no Grupo", "Não Entraram"],
            "Quantidade": [entradas_grupo, nao_entrou],
        })
        fig_pie = px.pie(
            pie_df,
            names="Status",
            values="Quantidade",
            hole=0.4,
            color="Status",
            color_discrete_map={"Entraram no Grupo": "#00A98F", "Não Entraram": "#64748B"},
        )
        fig_pie.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300)
        st.plotly_chart(fig_pie, use_container_width=True)

    # ── Evolução diária ──────────────────────────────────────────────────────
    if "compra_em" in df.columns and df["compra_em"].notna().any():
        try:
            df_time = df.copy()
            df_time["compra_em"] = pd.to_datetime(df_time["compra_em"], errors="coerce")
            df_time = df_time.dropna(subset=["compra_em"])
            df_time["data"] = df_time["compra_em"].dt.date

            daily_agg = (
                df_time.groupby("data")
                .agg(total=("entrou_no_grupo", "count"), entrou=("entrou_no_grupo", "sum"))
                .reset_index()
            )
            daily_agg["taxa"] = (daily_agg["entrou"] / daily_agg["total"] * 100).round(1)

            col_bar, col_rate = st.columns(2)

            with col_bar:
                st.subheader("Compradores por Dia")
                daily_stack = (
                    df_time.groupby(["data", "entrou_no_grupo"])
                    .size()
                    .reset_index(name="count")
                )
                daily_stack["status"] = daily_stack["entrou_no_grupo"].map(
                    {True: "Entrou no Grupo", False: "Não Entrou"}
                )
                fig_bar = px.bar(
                    daily_stack,
                    x="data",
                    y="count",
                    color="status",
                    color_discrete_map={"Entrou no Grupo": "#00A98F", "Não Entrou": "#64748B"},
                    labels={"data": "Data", "count": "Quantidade", "status": ""},
                    text_auto=True,
                )
                fig_bar.update_layout(legend_title_text="")
                st.plotly_chart(fig_bar, use_container_width=True)

            with col_rate:
                st.subheader("Taxa de Entrada no Grupo por Dia")
                fig_rate = px.line(
                    daily_agg,
                    x="data",
                    y="taxa",
                    markers=True,
                    labels={"data": "Data", "taxa": "Taxa (%)"},
                    text="taxa",
                )
                fig_rate.update_traces(
                    line_color="#00A98F",
                    texttemplate="%{text}%",
                    textposition="top center",
                )
                fig_rate.update_layout(yaxis_ticksuffix="%", yaxis_range=[0, 100])
                st.plotly_chart(fig_rate, use_container_width=True)

        except Exception:
            pass

    # ── Por campanha ─────────────────────────────────────────────────────────
    # A campanha vem de quem ENTROU no grupo (é o SendFlow que a conhece), então
    # esta tabela responde "qual campanha encheu o grupo", não "qual campanha
    # vendeu" — para isso falta o UTM da compra, que ainda não é gravado.
    if "campanha" in df.columns and df["campanha"].notna().any():
        st.subheader("Entradas por Campanha")
        por_campanha = (
            df[df["entrou_no_grupo"]]
            .groupby(["campanha", "grupo"], dropna=False)
            .agg(entradas=("entrou_no_grupo", "size"))
            .reset_index()
            .sort_values("entradas", ascending=False)
        )
        por_campanha["% das entradas"] = (
            por_campanha["entradas"] / max(entradas_grupo, 1) * 100
        ).round(1)
        st.dataframe(
            por_campanha.rename(columns={"campanha": "Campanha", "grupo": "Grupo",
                                         "entradas": "Entradas"}),
            hide_index=True, use_container_width=True,
        )

    st.divider()

    # ── Tabela detalhada ─────────────────────────────────────────────────────
    st.subheader("Base de Compradores")

    display = df.copy()
    display["Status Grupo"] = display["entrou_no_grupo"].map(
        {True: "✅ Entrou", False: "❌ Não entrou"}
    )
    display["Valor"] = display["valor"].apply(lambda x: f"R$ {x:,.2f}")

    col_map = {
        "nome": "Nome",
        "email": "Email",
        "telefone": "Telefone",
        "Valor": "Valor",
        "compra_em": "Data Compra",
        "payment_method": "Pagamento",
        "Status Grupo": "Entrou no Grupo",
        "data_entrada_grupo": "Data Entrada no Grupo",
        "campanha": "Campanha",
        "upsells": "Upsells",
    }
    cols = [c for c in col_map if c in display.columns]
    st.dataframe(
        display[cols].rename(columns=col_map),
        use_container_width=True,
        hide_index=True,
    )
