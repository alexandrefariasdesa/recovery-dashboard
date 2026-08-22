"""
components/pulso_tab.py
================================================================================
A página de operação: uma peça por cartão, e a régua da esquerda diz se ela
está de pé. Mesmo código de cor do resto do painel — verde-pix é "funcionando",
âmbar é "esperando/atenção", ardósia é "desligado de propósito", vermelho é erro.

O número grande de cada cartão é o **silêncio** (há quanto tempo aquela peça não
escreve), não o volume: volume alto com 9h de silêncio é uma peça caída, e o
cartão precisa gritar isso antes de mostrar quanto ela já rendeu.
"""
from datetime import datetime

import pandas as pd
import streamlit as st

from processors.pulso import _humano


_ROTULO_ESTADO = {
    "ok": "de pé",
    "atraso": "atrasado",
    "mudo": "sem dado",
    "erro": "erro",
}

_ESTADO_TIPO = {
    "ok": "chegando",
    "atraso": "atrasado",
    "parado": "parado (7d+)",
    "pouco dado": "pouco histórico",
    "mudo": "sem dado",
}

_FORA_LABEL = {
    "ativo": "ainda manda",
    "pausado": "pausado",
    "desconhecido": "não declarado",
}

_MODO_LABEL = {
    "off": ("desligado", "desligado"),
    "simulado": ("simulado · não manda nada", "espera"),
    "teste": ("teste · só a whitelist recebe", "espera"),
    "ligado": ("ligado · falando com o cliente", "ok"),
}


def _br(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def _quando(ts) -> str:
    if ts is None or pd.isna(ts):
        return "nunca"
    ts = pd.Timestamp(ts)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("America/Sao_Paulo").tz_localize(None)
    return ts.strftime("%d/%m %H:%M")


def _cartao(titulo: str, silencio: str, estado: str, linhas: list[str]) -> str:
    corpo = "".join(f"<div class='op-peca-linha'>{l}</div>" for l in linhas)
    return (
        f"<div class='op-peca' data-estado='{estado}'>"
        f"<div class='op-peca-topo'>"
        f"<span class='op-peca-nome'>{titulo}</span>"
        f"<span class='op-peca-tag'>{_ROTULO_ESTADO.get(estado, estado)}</span>"
        f"</div>"
        f"<div class='op-peca-valor'>{silencio}</div>"
        f"{corpo}</div>"
    )


def render_pulso_tab(data: dict) -> None:
    fontes: pd.DataFrame = data["fontes"]
    motores: dict = data["motores"]
    crons: pd.DataFrame = data["crons"]
    disparos: pd.DataFrame = data["disparos"]
    mix: pd.DataFrame = data["mix_eventos"]

    st.caption(
        "O que está de pé **agora** — esta página ignora o período escolhido. "
        "Cada peça viva deixa rastro numa tabela; o número grande é há quanto "
        "tempo ela não escreve nada."
    )

    # ── Alertas ──────────────────────────────────────────────────────────────
    alertas = data.get("alertas") or []
    if alertas:
        for a in alertas:
            st.warning(a)
    else:
        st.success("Todas as fontes escreveram dentro do prazo esperado.")

    # ── Fontes ───────────────────────────────────────────────────────────────
    st.subheader("Fontes de dado")
    cartoes = []
    for _, f in fontes.iterrows():
        cartoes.append(_cartao(
            f["titulo"],
            _humano(f["horas"]) if f["estado"] != "mudo" else "—",
            f["estado"],
            [
                f"última <b>{_quando(f['ultima'])}</b>",
                f"<b>{_br(f['d1'])}</b> em 24h · <b>{_br(f['d7'])}</b> em 7d · "
                f"{_br(f['total'])} no total",
                f"<span class='op-peca-quem'>{f['quem']}</span>",
            ],
        ))
    st.markdown(f"<div class='op-pulso'>{''.join(cartoes)}</div>", unsafe_allow_html=True)

    # ── Um nível abaixo: o tipo dentro da tabela ─────────────────────────────
    # `recovery_events` é uma fonte só no cartão, mas quatro origens diferentes
    # por dentro. Como o pix_gerado sozinho segura o relógio da tabela, um tipo
    # inteiro pode parar sem o cartão mudar de cor — por isso o detalhe.
    tipos: pd.DataFrame = data.get("tipos", pd.DataFrame())
    if not tipos.empty:
        with st.expander("Eventos de recuperação, por tipo — quem ainda chega", expanded=False):
            vista = tipos.copy()
            vista["silencio"] = vista["horas"].map(_humano)
            vista["normal"] = vista["limite_h"].map(
                lambda h: f"até {_humano(h)}" if pd.notna(h) else "—")
            vista["ultima"] = vista["ultima"].map(_quando)
            vista["estado"] = vista["estado"].map(_ESTADO_TIPO)
            st.dataframe(
                vista[["tipo", "estado", "silencio", "normal", "ultima", "d1", "d7", "d30"]]
                .rename(columns={
                    "tipo": "Tipo", "estado": "Estado", "silencio": "Sem chegar há",
                    "normal": "Normal desta origem", "ultima": "Último",
                    "d1": "24h", "d7": "7d", "d30": "30d",
                }),
                hide_index=True, use_container_width=True,
            )
            st.caption(
                "*Normal desta origem* é o p99 dos intervalos dos últimos 30 dias — "
                "cada tipo é comparado com o próprio ritmo, não com um número fixo."
            )

    st.divider()

    # ── Motores ──────────────────────────────────────────────────────────────
    st.subheader("Motores")
    esq, dir_ = st.columns(2)

    with esq:
        st.markdown("**Recuperação** — o motor próprio, por tipo de evento")
        cfg: pd.DataFrame = motores.get("recuperacao", pd.DataFrame())
        if cfg.empty:
            st.caption("Sem configuração no banco.")
        else:
            vista = cfg.copy()
            vista["modo"] = vista["modo"].map(lambda m: _MODO_LABEL.get(m, (m, ""))[0])
            vista["desde"] = vista["desde"].map(_quando)
            colunas = {
                "tipo": "Tipo", "modo": "Modo aqui",
                "desde": "Nesse modo desde", "max_por_dia": "Teto/dia",
            }
            if "fora_estado" in vista.columns:
                # A migração é uma gangorra: o que importa é o par (aqui, lá).
                vista["fora_estado"] = vista.apply(
                    lambda r: _FORA_LABEL.get(r["fora_estado"], r["fora_estado"]), axis=1
                )
                vista = vista[["tipo", "modo", "fora_estado", "desde", "max_por_dia"]]
                colunas["fora_estado"] = "Lá fora (declarado)"
            st.dataframe(
                vista.rename(columns=colunas),
                hide_index=True, use_container_width=True,
            )
            ligados = cfg[cfg["modo"] == "ligado"]["tipo"].tolist()
            if ligados:
                st.warning(
                    "Disparando de verdade: " + ", ".join(f"`{t}`" for t in ligados)
                    + ". A coluna *Lá fora* é registro declarado, não leitura do "
                      "Make — confira na origem antes de ligar mais um tipo."
                )
            else:
                st.caption(
                    "Nenhum tipo em **ligado** — quem fala com o cliente ainda é o Make."
                )
            if "fora_onde" in cfg.columns:
                with st.expander("Quem manda hoje, por tipo"):
                    for _, r in cfg.iterrows():
                        st.markdown(
                            f"- `{r['tipo']}` → {r['fora_onde']}"
                            + (f" · desde {r['fora_desde']}" if r["fora_desde"] != "—" else "")
                        )

    with dir_:
        st.markdown("**Convite da aula** — grade do pg_cron")
        aula: dict = motores.get("aula") or {}
        if not aula:
            st.caption("Sem configuração no banco.")
        else:
            grade: pd.DataFrame = aula.get("grade", pd.DataFrame())
            if aula.get("ativo"):
                st.success(f"No ar · teto de {_br(aula.get('max_por_dia', 0))} convites/dia")
            else:
                st.info(
                    "Desligado em `convites_aula_config.ativo` — os crons continuam "
                    "batendo na hora certa, mas a edge function não manda nada."
                )
            if not grade.empty:
                horas = " · ".join(
                    f"{r['h']}{'' if r['ativo'] and r['flow_ns'] else ' (sem fluxo)'}"
                    for _, r in grade.iterrows()
                )
                st.markdown(f"<div class='op-grade'>{horas}</div>", unsafe_allow_html=True)
                st.caption("Horários em BRT. Etapa sem `flow_ns` daria erro se ligasse.")
            st.caption(f"Fila de convites hoje: **{_br(aula.get('convites', 0))}**.")

    # ── Disparos das últimas 24h ─────────────────────────────────────────────
    if not disparos.empty:
        st.markdown("**Fila do motor nas últimas 24h**")
        vista = disparos.copy()
        vista["ultimo"] = vista["ultimo"].map(_quando)
        st.dataframe(
            vista.rename(columns={
                "tipo": "Tipo", "etapa": "Etapa", "status": "Status",
                "n": "Disparos", "ultimo": "Último",
            }),
            hide_index=True, use_container_width=True,
        )

    st.divider()

    # ── Crons do Supabase ────────────────────────────────────────────────────
    st.subheader("Agendamentos no banco (pg_cron)")
    if crons.empty:
        st.caption(
            "Não consegui ler `cron.job` com este usuário — o bloco fica vazio "
            "em vez de chutar o estado dos agendamentos."
        )
    else:
        vista = crons.copy()
        vista["ultima"] = vista["ultima"].map(_quando)
        vista["active"] = vista["active"].map(lambda v: "sim" if v else "não")
        st.dataframe(
            vista[["jobname", "schedule", "active", "status", "ultima", "falhas_24h"]]
            .rename(columns={
                "jobname": "Job", "schedule": "Cron", "active": "Ativo",
                "status": "Última execução", "ultima": "Quando",
                "falhas_24h": "Falhas 24h",
            }),
            hide_index=True, use_container_width=True,
        )
        st.caption(
            f"{len(crons)} agendamentos · "
            f"{int((crons['active']).sum())} ativos · "
            f"{int(crons['falhas_24h'].sum())} falhas nas últimas 24h."
        )

    # ── Mix de eventos ───────────────────────────────────────────────────────
    if not mix.empty:
        st.subheader("Eventos do ManyChat por fluxo (7 dias)")
        total = int(mix["n"].sum())
        topo = mix.iloc[0]
        if total and topo["n"] / total > 0.9 and len(mix) > 1:
            st.warning(
                f"`{topo['fluxo']}` sozinho é **{topo['n'] / total:.0%}** dos eventos "
                f"({_br(topo['n'])} de {_br(total)}), vindos de "
                f"{_br(topo['pessoas'])} pessoas distintas. Vale conferir se é volume "
                "real ou o worker sendo chamado mais de uma vez por pessoa."
            )
        vista = mix.copy()
        vista["ultimo"] = vista["ultimo"].map(_quando)
        vista["por_pessoa"] = (vista["n"] / vista["pessoas"].replace(0, pd.NA)).round(1)
        st.dataframe(
            vista.rename(columns={
                "fluxo": "Fluxo", "n": "Eventos", "pessoas": "Pessoas",
                "por_pessoa": "Eventos/pessoa", "ultimo": "Último",
            }),
            hide_index=True, use_container_width=True,
        )

    st.divider()

    # ── Fora do banco ────────────────────────────────────────────────────────
    st.subheader("Automações fora do banco")
    st.caption(
        "O painel não consegue verificar estas daqui — é registro declarado, "
        "com a data em que mudou. Confira na origem antes de decidir por elas."
    )
    for e in data.get("externas", []):
        estado = "ok" if e["estado"] == "no ar" else "desligado"
        st.markdown(
            _cartao(
                e["titulo"],
                e["estado"],
                estado,
                [e["detalhe"], f"<b>{e['onde']}</b> · desde {e['desde']}",
                 f"<span class='op-peca-quem'>{e['nota']}</span>"],
            ),
            unsafe_allow_html=True,
        )

    lido = data.get("lido_em") or datetime.now()
    st.caption(f"Leitura de {lido.strftime('%d/%m %H:%M:%S')} · cache de 60s.")
