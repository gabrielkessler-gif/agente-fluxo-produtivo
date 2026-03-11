import streamlit as st
import anthropic
from collections import defaultdict

# ─── Configuração da página ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Agente de Fluxo Produtivo",
    page_icon="🏭",
    layout="wide"
)

# ─── Mapeamento de etapas e colunas do CSV ────────────────────────────────────
ETAPAS = [
    ("Pesagem",                  13, 14, 15, 18),
    ("Manipulação de Sólidos",   20, 21, 22, 25),
    ("Mistura Final",            27, 28, 29, 32),
    ("Compressão",               34, 35, 36, 39),
    ("Encapsulamento",           41, 42, 43, 46),
    ("Revestimento",             48, 49, 50, 53),
    ("Emblistagem",              55, 56, 57, 60),
    ("Linha 5",                  62, 63, 64, 67),
    ("Bulk",                     69, 70, 71, 74),
]

# ─── System Prompt — Análise Geral ───────────────────────────────────────────
SYSTEM_GERAL = """Você é um especialista em otimização de fluxo produtivo industrial, com profundo conhecimento em manufatura farmacêutica e gestão de produção por Lead Time.

Você recebe um relatório analítico com dados históricos de ordens de produção, contendo:
- Rotas produtivas por SKU (quais etapas e equipamentos cada produto percorre)
- Lead Time real vs padrão por etapa e por produto
- Desvios acumulados por equipamento
- Casos extremos (melhores e piores ordens)

Sua análise deve ser estruturada nas seguintes seções:

## 🗺️ Rotas Identificadas
Descreva as rotas produtivas encontradas para cada SKU, destacando diferenças entre produtos similares.

## 🔴 Gargalos Críticos
Identifique quais etapas e equipamentos concentram os maiores desvios. Seja específico: nome da etapa, equipamento, desvio médio vs esperado.

## 📊 Comparativo por Produto
Quais SKUs têm melhor e pior performance de lead time? Qual a relação entre rota e desvio?

## ✅ Recomendações de Otimização
Liste ações concretas e priorizadas. Cite os equipamentos e etapas pelo nome exato dos dados.

## 📈 Potencial de Melhoria
Estime o impacto das recomendações no lead time médio se implementadas.

Use linguagem direta e objetiva. Cite números específicos do relatório."""

# ─── System Prompt — Perguntas Específicas ───────────────────────────────────
SYSTEM_ESPECIFICO = """Você é um especialista em otimização de fluxo produtivo industrial com foco em manufatura farmacêutica.

Você tem acesso ao histórico de ordens de produção dos últimos 90 dias da fábrica, incluindo rotas por produto, lead times reais, desvios por etapa e equipamento.

Quando o usuário fizer uma pergunta específica sobre como melhorar o fluxo ou reduzir lead times, você DEVE avaliar TODAS as seguintes dimensões e indicar o potencial de cada uma:

### 1. 🔄 Turnos Adicionais
Avalie se adicionar horas/turnos nas etapas gargalo reduziria o lead time. Estime quantas horas extras seriam necessárias e qual o impacto esperado em dias.

### 2. ⚙️ OEE — Eficiência dos Equipamentos
Analise o tempo de espera vs processo em cada etapa do produto em questão. Se a espera for muito maior que o processo, o gargalo é disponibilidade/fila, não capacidade. Se o processo estiver alto, ganhos de OEE ajudam diretamente. Estime o impacto de um aumento de OEE de 10-15% na etapa crítica.

### 3. 🗺️ Recalibração de Rota
Verifique se existem equipamentos alternativos usados por outros produtos na mesma etapa. Sugira redistribuição de carga se houver ociosidade em equipamentos alternativos. Cite os equipamentos pelo nome.

### 4. ⏱️ Tempos de Setup
Analise o tempo de espera nas etapas — parte relevante costuma ser setup/troca. Sugira agrupamento de ordens similares (por SKU ou por equipamento) para reduzir setups, e estime o ganho.

### 5. 🎯 Ineficiências Pontuais
Identifique as ordens com maior desvio do produto em questão. Compare com as ordens de melhor performance. O que as separa? Cite ordens específicas como exemplo do melhor caso alcançável.

Ao final, forneça um **plano de ação priorizado** com as alavancas de maior impacto primeiro, indicando:
- Ação específica
- Etapa/equipamento afetado
- Redução estimada em dias de lead time
- Complexidade de implementação (baixa / média / alta)

Seja direto, use os dados disponíveis e cite números reais do histórico."""

# ─── Funções de parse ─────────────────────────────────────────────────────────
def parse_valor(val):
    if not val or str(val).strip() in ('', ' ', '-'):
        return 0.0
    try:
        return float(str(val).strip().replace(',', '.'))
    except:
        return 0.0

def parse_csv(file_bytes):
    content = None
    for encoding in ['utf-8-sig', 'latin-1', 'cp1252', 'utf-8']:
        try:
            content = file_bytes.decode(encoding)
            break
        except:
            continue

    if content is None:
        return None, "Não foi possível ler o arquivo."

    lines = content.replace('\r\n', '\n').replace('\r', '\n').split('\n')

    header_idx = None
    for i, line in enumerate(lines):
        if 'ORDEM' in line and 'LOTE' in line and 'SKU' in line:
            header_idx = i
            break

    if header_idx is None:
        return None, "Formato não reconhecido. Use o Relatório de Lead Time de Ordem (Analítico) em CSV."

    ordens = []
    for line in lines[header_idx + 1:]:
        if not line.strip():
            continue
        partes = line.rstrip(';').split(';')
        if len(partes) < 12 or not partes[0].strip().isdigit():
            continue
        while len(partes) < 75:
            partes.append('')
        ordens.append(partes)

    if not ordens:
        return None, "Nenhuma ordem encontrada no arquivo."

    return ordens, None

def extrair_dados(ordens):
    produtos = defaultdict(list)
    for row in ordens:
        ordem   = row[0].strip()
        sku     = row[2].strip()
        produto = row[3].strip()
        lt_real   = parse_valor(row[7])
        lt_padrao = parse_valor(row[8])
        desvio    = parse_valor(row[9])
        espera_t  = parse_valor(row[10])
        proc_t    = parse_valor(row[11])

        rota = []
        for nome_etapa, c_eq, c_esp, c_proc, c_desv in ETAPAS:
            equip = row[c_eq].strip() if c_eq < len(row) else ''
            esp   = parse_valor(row[c_esp])  if c_esp  < len(row) else 0.0
            proc  = parse_valor(row[c_proc]) if c_proc < len(row) else 0.0
            desv  = parse_valor(row[c_desv]) if c_desv < len(row) else 0.0
            if equip:
                rota.append({'etapa': nome_etapa, 'equipamento': equip,
                             'espera': esp, 'processo': proc, 'desvio': desv})

        chave = f"{sku} — {produto}"
        produtos[chave].append({
            'ordem': ordem, 'lt_real': lt_real, 'lt_padrao': lt_padrao,
            'desvio': desvio, 'espera_total': espera_t,
            'processo_total': proc_t, 'rota': rota
        })
    return produtos

def formatar_resumo(produtos):
    total = sum(len(v) for v in produtos.values())
    linhas = [f"RELATÓRIO DE FLUXO PRODUTIVO — {len(produtos)} SKUs | {total} ordens", "=" * 70]

    for chave, ordens in sorted(produtos.items()):
        lts   = [o['lt_real']   for o in ordens if o['lt_real']   > 0]
        pads  = [o['lt_padrao'] for o in ordens if o['lt_padrao'] > 0]
        desvs = [o['desvio']    for o in ordens]

        avg_lt  = sum(lts)  / len(lts)  if lts  else 0
        avg_pad = sum(pads) / len(pads) if pads else 0
        avg_d   = sum(desvs) / len(desvs) if desvs else 0
        max_d   = max(desvs)              if desvs else 0

        linhas.append(f"\nPRODUTO: {chave}")
        linhas.append(f"Ordens: {len(ordens)} | LT médio real: {avg_lt:.1f}d | Padrão: {avg_pad:.1f}d | Desvio médio: {avg_d:.1f}d | Desvio máximo: {max_d:.1f}d")

        dev_etapa = defaultdict(list)
        eq_etapa  = defaultdict(set)
        esp_etapa = defaultdict(list)
        for o in ordens:
            for e in o['rota']:
                dev_etapa[e['etapa']].append(e['desvio'])
                eq_etapa[e['etapa']].add(e['equipamento'])
                esp_etapa[e['etapa']].append(e['espera'])

        if dev_etapa:
            linhas.append("Rota e desvios por etapa:")
            for nome, devs in dev_etapa.items():
                equips  = ' | '.join(sorted(eq_etapa[nome]))
                avg_dev = sum(devs) / len(devs)
                max_dev = max(devs)
                avg_esp = sum(esp_etapa[nome]) / len(esp_etapa[nome])
                linhas.append(f"  → {nome} ({equips}): desvio médio {avg_dev:.2f}d | máx {max_dev:.2f}d | espera média {avg_esp:.2f}d")

        piores   = sorted(ordens, key=lambda x: x['desvio'], reverse=True)[:3]
        melhores = sorted(ordens, key=lambda x: x['desvio'])[:3]
        desvios_piores   = ', '.join(str(round(o['desvio'], 1)) + 'd' for o in piores)
        desvios_melhores = ', '.join(str(round(o['desvio'], 1)) + 'd' for o in melhores)
        ordens_piores    = ', '.join(o['ordem'] for o in piores)
        ordens_melhores  = ', '.join(o['ordem'] for o in melhores)
        linhas.append(f"  ⚠ Piores: ordens {ordens_piores} (desvios: {desvios_piores})")
        linhas.append(f"  ✓ Melhores: ordens {ordens_melhores} (desvios: {desvios_melhores})")

    return '\n'.join(linhas)

def chamar_claude(system_prompt, messages, api_key):
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=3000,
        system=system_prompt,
        messages=messages
    )
    return msg.content[0].text

# ─── Interface ────────────────────────────────────────────────────────────────
st.title("🏭 Agente de Otimização de Fluxo Produtivo")
st.caption("Carregue o Relatório de Lead Time (Analítico) e receba recomendações baseadas nas rotas históricas.")

# Inicializa session state
if 'resumo_dados' not in st.session_state:
    st.session_state.resumo_dados = None
if 'historico_chat' not in st.session_state:
    st.session_state.historico_chat = []

with st.sidebar:
    st.header("⚙️ Configuração")
    api_key = st.text_input("API Key da Anthropic", type="password", placeholder="sk-ant-...")
    st.markdown("[👉 Obter API Key](https://console.anthropic.com)")
    st.divider()
    st.markdown("**Formato esperado:**")
    st.markdown("Relatório de Lead Time de Ordem (Analítico) — arquivo `.csv` separado por ponto-e-vírgula.")
    if st.session_state.resumo_dados:
        st.divider()
        st.success("✅ Dados carregados")
        if st.button("🗑️ Limpar dados e chat", use_container_width=True):
            st.session_state.resumo_dados = None
            st.session_state.historico_chat = []
            st.rerun()

# ─── Seção 1: Upload ──────────────────────────────────────────────────────────
st.subheader("📂 1. Carregar Relatório")
arquivo = st.file_uploader("Selecione o arquivo CSV", type=["csv"], label_visibility="collapsed")

if arquivo:
    file_bytes = arquivo.read()
    ordens, erro = parse_csv(file_bytes)

    if erro:
        st.error(f"❌ {erro}")
    else:
        produtos = extrair_dados(ordens)
        total_ordens = sum(len(v) for v in produtos.values())

        col1, col2, col3 = st.columns(3)
        col1.metric("Ordens encontradas", total_ordens)
        col2.metric("SKUs distintos", len(produtos))
        todos_lts = [o['lt_real'] for ords in produtos.values() for o in ords if o['lt_real'] > 0]
        lt_medio = sum(todos_lts) / len(todos_lts) if todos_lts else 0
        col3.metric("Lead Time médio geral", f"{lt_medio:.1f} dias")

        with st.expander("📋 Produtos encontrados"):
            for chave, ords in sorted(produtos.items()):
                lts  = [o['lt_real'] for o in ords if o['lt_real'] > 0]
                devs = [o['desvio']  for o in ords]
                avg_lt = sum(lts) / len(lts)   if lts  else 0
                avg_d  = sum(devs) / len(devs) if devs else 0
                st.markdown(f"**{chave}** — {len(ords)} ordens | LT médio: {avg_lt:.1f}d | Desvio médio: {avg_d:.1f}d")

        # Salva resumo no session state
        st.session_state.resumo_dados = formatar_resumo(produtos)
        st.session_state.historico_chat = []

st.divider()

# ─── Seção 2 e 3 só aparecem se dados estiverem carregados ───────────────────
if st.session_state.resumo_dados:

    if not api_key:
        st.warning("⚠️ Insira sua API Key na barra lateral para usar o agente.")
    else:
        # ── Análise Geral ──────────────────────────────────────────────────────
        st.subheader("📊 2. Análise Geral")
        if st.button("🔍 Gerar Diagnóstico Completo", type="primary", use_container_width=True):
            with st.spinner("Analisando rotas e padrões históricos..."):
                try:
                    resultado = chamar_claude(
                        SYSTEM_GERAL,
                        [{"role": "user", "content": st.session_state.resumo_dados}],
                        api_key
                    )
                    st.markdown(resultado)
                except anthropic.AuthenticationError:
                    st.error("❌ API Key inválida.")
                except Exception as e:
                    st.error(f"❌ Erro: {str(e)}")

        st.divider()

        # ── Perguntas Específicas ──────────────────────────────────────────────
        st.subheader("💬 3. Perguntas Específicas")
        st.caption("Faça perguntas sobre produtos, metas de lead time, turnos, equipamentos ou qualquer cenário específico.")

        # Exemplos de perguntas
        with st.expander("💡 Exemplos de perguntas"):
            st.markdown("""
- *Para atender a demanda desse mês preciso reduzir o lead time do Gripalce em 3 dias, o que posso fazer?*
- *Qual etapa está causando mais espera no Salicetil? Vale a pena um turno adicional?*
- *Se eu aumentar o OEE da Blisterflex em 10%, quanto isso reduz o lead time do Salicetil C/500?*
- *Quais produtos poderiam ter sua rota recalibrada para liberar capacidade no Bosch-46?*
- *Compare o desempenho do MN41-12 e MN41-68. Qual está com mais ineficiências?*
            """)

        # Histórico do chat
        for msg in st.session_state.historico_chat:
            with st.chat_message(msg["role"], avatar="🧑" if msg["role"] == "user" else "🤖"):
                st.markdown(msg["content"])

        # Input de pergunta
        pergunta = st.chat_input("Faça sua pergunta sobre o fluxo produtivo...")

        if pergunta:
            # Mostra a pergunta do usuário
            with st.chat_message("user", avatar="🧑"):
                st.markdown(pergunta)

            # Monta o histórico + contexto dos dados
            contexto_inicial = f"""Você tem acesso ao seguinte histórico de produção dos últimos 90 dias:

{st.session_state.resumo_dados}

---
Responda à pergunta do usuário com base nesses dados."""

            messages_para_claude = [
                {"role": "user", "content": contexto_inicial},
                {"role": "assistant", "content": "Entendido. Tenho os dados históricos de produção carregados e estou pronto para responder perguntas específicas sobre o fluxo produtivo."},
            ]

            # Adiciona histórico anterior (sem o contexto inicial para não repetir)
            for msg in st.session_state.historico_chat:
                messages_para_claude.append({"role": msg["role"], "content": msg["content"]})

            # Adiciona a nova pergunta
            messages_para_claude.append({"role": "user", "content": pergunta})

            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("Analisando..."):
                    try:
                        resposta = chamar_claude(SYSTEM_ESPECIFICO, messages_para_claude, api_key)
                        st.markdown(resposta)

                        # Salva no histórico
                        st.session_state.historico_chat.append({"role": "user",      "content": pergunta})
                        st.session_state.historico_chat.append({"role": "assistant", "content": resposta})

                    except anthropic.AuthenticationError:
                        st.error("❌ API Key inválida.")
                    except Exception as e:
                        st.error(f"❌ Erro: {str(e)}")

else:
    st.info("👆 Carregue o arquivo CSV para habilitar o agente.")

st.divider()
st.caption("Beta v0.3 · Agente de Otimização de Fluxo Produtivo")
