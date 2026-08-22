"""
components/visao_geral_tab.py
================================================================================
A primeira tela: seis funis, seis cartões, o dinheiro na frente.

O que cada cartão precisa entregar em dois segundos de leitura: quanto aquele
funil moveu, se está subindo ou caindo, e — quando o número não pode ser levado
a sério — por quê. A ressalva fica DENTRO do cartão, não num aviso solto no topo
da página: quem lê "R$ 157,90" no Grupo precisa ver ali mesmo que a fonte só
existe desde ontem, senão leva o número embora.

A variação some quando o cartão não está em estado `ok`. É de propósito: com
fonte parcial ou motor em simulado, a conta fecha aritmeticamente e mente
semanticamente.
"""
import pandas as pd
import streamlit as st


_TAG = {"espera": "parcial", "desligado": "desligado"}


def _reais(v):
    return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _br(v):
    return f"{int(v):,}".replace(",", ".")


def _valor(c):
    return _reais(c.valor) if c.formato == "dinheiro" else _br(c.valor)


def _cartao_html(c) -> str:
    var = c.variacao
    if var is None:
        var_html = ""
    else:
        sinal = "sobe" if var >= 0 else "desce"
        var_html = f"<span class='vg-var' data-sinal='{sinal}'>{var:+.0f}%</span>"

    tag = _TAG.get(c.estado, "")
    tag_html = f"<span class='vg-tag'>{tag}</span>" if tag else ""
    apoios = "".join(
        f"<span class='vg-apoio'>{rotulo} <b>{valor}</b></span>"
        for rotulo, valor in c.apoios
    )
    nota = f"<div class='vg-nota'>{c.nota}</div>" if c.nota else ""
    return (
        f"<div class='vg-cartao' data-estado='{c.estado}'>"
        f"<div class='vg-topo'><span class='vg-nome'>{c.titulo}</span>{tag_html}</div>"
        f"<div class='vg-valor'>{_valor(c)}{var_html}</div>"
        f"<div class='vg-legenda'>{c.legenda}</div>"
        f"<div class='vg-apoios'>{apoios}</div>"
        f"{nota}</div>"
    )


def render_visao_geral_tab(data: dict) -> None:
    cartoes = data.get("cartoes", [])
    ini, fim = data.get("periodo", (None, None))
    pini, pfim = data.get("anterior", (None, None))

    st.caption(
        f"Variação contra o período anterior de mesmo tamanho "
        f"(**{pini:%d/%m}** a **{pfim:%d/%m}**). Cartão com tarja âmbar tem "
        "ressalva na leitura; ardósia está desligado de propósito."
    )

    for erro in data.get("erros", []):
        st.warning(f"Um funil não pôde ser lido: `{erro}`")

    if not cartoes:
        st.info("Nada a mostrar no período.")
        return

    st.markdown(
        "<div class='vg-grade'>" + "".join(_cartao_html(c) for c in cartoes) + "</div>",
        unsafe_allow_html=True,
    )

    # ── Para onde ir a partir daqui ──────────────────────────────────────────
    # Link por `url_path` em vez de `st.page_link`: o app monta as páginas a
    # partir de FUNÇÕES em `st.navigation`, e page_link espera o objeto Page ou
    # um arquivo em pages/ — nenhum dos dois existe aqui. O link direto funciona
    # porque cada página declara seu url_path.
    st.divider()
    st.markdown("**Abrir o detalhe**")
    linha = " · ".join(f"[{c.titulo}](/{c.pagina})" for c in cartoes if c.pagina)
    st.markdown(linha)

    # Receita total fora do grid: não é um funil, é o resultado deles somados.
    # Recuperação não entra — o dinheiro dela JÁ está na aquisição (é a mesma
    # venda, só que resgatada), e somar contaria a compra duas vezes.
    receita = sum(float(c.valor) for c in cartoes
                  if c.chave in ("aquisicao", "upsell"))
    if receita:
        st.caption(
            f"Receita total no período: **{_reais(receita)}** "
            "(entrada + upsell). A recuperação não soma aqui: o dinheiro dela já "
            "está na aquisição — é a mesma venda, resgatada."
        )
