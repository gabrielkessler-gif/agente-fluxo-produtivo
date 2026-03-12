import streamlit as st
import anthropic
from collections import defaultdict
import re

# ─── Configuração da página ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Agente de Fluxo Produtivo",
    page_icon="🏭",
    layout="wide"
)

# ─── Colunas padrão (fallback se não detectar automaticamente) ────────────────
# Formato original: ORDEM na col 0, etapas a partir da col 13, grupos de 7
ETAPAS_PADRAO = [
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

# ─── System Prompts ───────────────────────────────────────────────────────────
SYSTEM_GERAL = """Você é um especialista em otimização de fluxo produtivo industrial, com profundo conhecimento em manufatura farmacêutica e gestão de produção por Lead Time.

Você recebe um relatório analítico com dados históricos de ordens de produção, contendo:
- Rotas produtivas por SKU (quais etapas e equipamentos cada produto percorre)
- Lead Time real vs padrão por etapa e por produto
- Desvios acumulados por equipamento
- Casos extremos (melhores e piores ordens)

Sua análise deve ser estruturada nas seguintes seções:

## Rotas Identificadas
Descreva as rotas produtivas encontradas para cada SKU, destacando diferenças entre produtos similares.

## Gargalos Críticos
Identifique quais etapas e equipamentos concentram os maiores desvios. Seja específico: nome da etapa, equipamento, desvio médio vs esperado.

## Comparativo por Produto
Quais SKUs têm melhor e pior performance de lead time? Qual a relação entre rota e desvio?

## Recomendações de Otimização
Liste ações concretas e priorizadas. Cite os equipamentos e etapas pelo nome exato dos dados.

## Potencial de Melhoria
Estime o impacto das recomendações no lead time médio se implementadas.

## Plano de Ação
Liste as ações em ordem de prioridade, cada uma com:
- Ação específica a executar
- Etapa/equipamento afetado
- Redução estimada em dias de lead time
- Complexidade de implementação (baixa / média / alta)
- Responsável sugerido (operação / planejamento / manutenção / qualidade)

## Conclusão
Finalize com uma conclusão direta e objetiva. Se a análise levar a uma resposta do tipo sim/não, declare explicitamente:
- **Sim** ou **Não** em destaque, seguido da justificativa com números.
- Se for possível mas muito difícil: declare que **é possível, mas será extremamente desafiador**, e que só será viável se o plano de ação acima for seguido à risca, indicando quais etapas são inegociáveis.

Use linguagem direta e objetiva. Cite números específicos do relatório."""

SYSTEM_ESPECIFICO = """Você é um especialista em otimização de fluxo produtivo industrial com foco em manufatura farmacêutica.

Você tem acesso ao histórico de ordens de produção dos últimos 90 dias da fábrica, incluindo rotas por produto, lead times reais, desvios por etapa e equipamento.

Quando o usuário fizer uma pergunta específica sobre como melhorar o fluxo ou reduzir lead times, você DEVE avaliar TODAS as seguintes dimensões e indicar o potencial de cada uma:

### 1. Turnos Adicionais
Avalie se adicionar horas/turnos nas etapas gargalo reduziria o lead time. Estime quantas horas extras seriam necessárias e qual o impacto esperado em dias.

### 2. OEE - Eficiência dos Equipamentos
Analise o tempo de espera vs processo em cada etapa do produto em questão. Se a espera for muito maior que o processo, o gargalo é disponibilidade/fila, não capacidade. Se o processo estiver alto, ganhos de OEE ajudam diretamente. Estime o impacto de um aumento de OEE de 10-15% na etapa crítica.

### 3. Recalibração de Rota
Verifique se existem equipamentos alternativos usados por outros produtos na mesma etapa. Sugira redistribuição de carga se houver ociosidade em equipamentos alternativos. Cite os equipamentos pelo nome.

### 4. Tempos de Setup
Analise o tempo de espera nas etapas — parte relevante costuma ser setup/troca. Sugira agrupamento de ordens similares (por SKU ou por equipamento) para reduzir setups, e estime o ganho.

### 5. Ineficiências Pontuais
Identifique as ordens com maior desvio do produto em questão. Compare com as ordens de melhor performance. O que as separa? Cite ordens específicas como exemplo do melhor caso alcançável.

## Plano de Ação
Ao final da análise das dimensões, forneça um plano de ação numerado e priorizado, com as alavancas de maior impacto primeiro. Para cada ação, indique:
- Ação específica a executar
- Etapa/equipamento afetado
- Redução estimada em dias de lead time
- Complexidade de implementação (baixa / média / alta)
- Responsável sugerido (operação / planejamento / manutenção / qualidade)

## Conclusão
OBRIGATÓRIO: toda resposta deve terminar com uma conclusão direta. Siga estas regras:

1. Se a pergunta admite resposta SIM ou NÃO: comece a conclusão com **Sim.** ou **Não.** em negrito, seguido da justificativa em uma ou duas frases com números reais.

2. Se for possível mas muito difícil: escreva **É possível, mas será extremamente desafiador.** em negrito, e liste explicitamente as condições inegociáveis — "só será viável se os passos X, Y e Z do plano acima forem seguidos à risca."

3. Em todos os casos: termine indicando qual é a alavanca de maior impacto e qual o ganho máximo realista esperado.

Seja direto, use os dados disponíveis e cite números reais do histórico."""

SYSTEM_RELATORIO = """Você é um especialista em otimização de fluxo produtivo. Você recebe o histórico completo de uma discussão técnica entre o agente de análise e a equipe da fábrica.

REGRA ABSOLUTA: Antes de escrever qualquer coisa, identifique todas as restrições, limitações e condições estabelecidas pela equipe ao longo da discussão (ex: "não podemos fazer turnos adicionais", "o equipamento X está indisponível", "o orçamento é limitado"). Essas restrições são INEGOCIÁVEIS e devem ser rigorosamente respeitadas em todo o relatório — especialmente no Plano de Ação. Jamais inclua ações que violem restrições explicitamente declaradas pela equipe.

Sua tarefa é consolidar essa discussão em um relatório executivo profissional, estruturado nas seguintes seções:

## Contexto da Análise
Descreva brevemente o escopo analisado: período, quantidade de SKUs e ordens, unidade industrial.

## Aprendizados da Discussão
Liste os principais insights que emergiram do debate — pontos levantados pela equipe, questionamentos respondidos, nuances identificadas que não estavam no diagnóstico inicial.

## Plano de Ação Consolidado
Apresente o plano de ação final, incorporando os ajustes discutidos. Para cada ação, inclua:
- Ação específica
- Etapa/equipamento afetado
- Impacto esperado (redução de lead time ou ganho de throughput)
- Complexidade (baixa / média / alta)
- Responsável sugerido

## Decisões e Alinhamentos
Registre decisões tomadas, pontos de concordância e discordâncias resolvidas durante a discussão.

## Próximos Passos
Liste as ações imediatas acordadas, com prazo sugerido e responsável.

## Conclusão
Síntese direta do resultado da discussão: o que foi validado, o que mudou em relação ao diagnóstico inicial, e qual o ganho potencial se o plano for executado.

Use linguagem direta e objetiva. Cite números reais sempre que disponíveis. Este relatório será entregue à liderança da fábrica."""

# ─── Funções de parse ─────────────────────────────────────────────────────────
def parse_valor(val):
    if not val or str(val).strip() in ('', ' ', '-'):
        return 0.0
    try:
        return float(str(val).strip().replace(',', '.'))
    except:
        return 0.0

def detectar_separador(content):
    """Detecta automaticamente se o separador é ; ou ,"""
    for line in content.split('\n')[:15]:
        sc = line.count(';')
        co = line.count(',')
        if sc > 3 or co > 3:
            return ';' if sc >= co else ','
    return ';'

def encontrar_col_idx(col_map, *keywords, default=None):
    """
    Encontra o índice de coluna procurando substrings nos nomes dos cabeçalhos.
    Usa a PRIMEIRA ocorrência de cada match (importante para colunas com nomes repetidos).
    """
    for kw in keywords:
        kw_up = kw.upper()
        # Busca exata primeiro
        if kw_up in col_map:
            return col_map[kw_up]
        # Busca parcial
        for cn, idx in col_map.items():
            if kw_up in cn:
                return idx
    return default

def detectar_etapas_por_super_header(header_parts, super_header_parts):
    """
    Detecta etapas usando o super-header (linha acima do header de colunas).
    Procura por colunas EQUIPAMENTO e associa cada uma a um nome de etapa
    que aparece no super-header na mesma posição.
    Retorna lista de (nome, c_equip, c_espera, c_processo, c_desvio).
    """
    equip_cols = [
        i for i, h in enumerate(header_parts)
        if 'EQUIPAMENTO' in h.strip().upper() or 'EQUIP' in h.strip().upper()
    ]
    if not equip_cols:
        return None

    etapas = []
    for eq_col in equip_cols:
        # Procurar nome da etapa no super-header ao redor de eq_col
        nome_etapa = ''
        for offset in range(-3, 4):
            idx = eq_col + offset
            if 0 <= idx < len(super_header_parts) and super_header_parts[idx].strip():
                raw = super_header_parts[idx].strip()
                # Limpar prefixos comuns nos super-headers de relatórios SAP/ERP
                for prefix in [
                    'DESVIO DE LEAD TIME/', 'LEAD TIME/', 'LT/',
                    'TEMPO DE CICLO/', 'CICLO/', 'ETAPA/',
                ]:
                    raw = raw.replace(prefix, '').replace(prefix.upper(), '')
                nome_etapa = raw.strip()
                break

        if not nome_etapa:
            nome_etapa = f"Etapa {len(etapas) + 1}"

        # Estrutura padrão por grupo: EQUIP(+0), ESPERA(+1), PROCESSO(+2), DESVIO(+5)
        etapas.append((
            nome_etapa,
            eq_col,
            eq_col + 1,
            eq_col + 2,
            eq_col + 5,
        ))

    return etapas if etapas else None


def detectar_etapas_por_header(header_parts):
    """
    Fallback: tenta detectar etapas pelos nomes no próprio header de colunas,
    procurando keywords de etapas farmacêuticas conhecidas.
    """
    ETAPAS_KEYWORDS = {
        "Pesagem":                ["PESAGEM", "WEIGH"],
        "Manipulação de Sólidos": ["SOLIDO", "SÓLIDO", "SOLID", "MANIPUL"],
        "Mistura Final":          ["MISTURA", "MIXING", "BLEND"],
        "Compressão":             ["COMPRESS"],
        "Encapsulamento":         ["ENCAPSUL", "CAPSUL"],
        "Revestimento":           ["REVESTIM", "COATING"],
        "Emblistagem":            ["EMBLIST", "BLIST"],
        "Linha 5":                ["LINHA 5", "LINE 5", "LN5"],
        "Bulk":                   ["BULK"],
    }
    h_upper = [h.strip().upper() for h in header_parts]
    etapas_detectadas = []

    for nome_etapa, keywords in ETAPAS_KEYWORDS.items():
        cols_etapa = []
        for i, h in enumerate(h_upper):
            for kw in keywords:
                if kw in h:
                    cols_etapa.append(i)
                    break
        if len(cols_etapa) < 4:
            continue
        sorted_cols = sorted(cols_etapa)
        c_eq = c_esp = c_proc = c_desv = None
        for ci in sorted_cols:
            h = h_upper[ci]
            if any(kw in h for kw in ["EQUIP", "RECURSO", "MAQUINA", "MÁQUINA"]):
                c_eq = ci
            elif any(kw in h for kw in ["ESPERA", "WAIT", "FILA"]):
                c_esp = ci
            elif any(kw in h for kw in ["PROCESS", "EXECU", "PRODUT"]):
                c_proc = ci
            elif any(kw in h for kw in ["DESVIO", "DEVIA", "VARIA"]):
                c_desv = ci
        if c_eq   is None: c_eq   = sorted_cols[0]
        if c_esp  is None: c_esp  = sorted_cols[1] if len(sorted_cols) > 1 else sorted_cols[0]
        if c_proc is None: c_proc = sorted_cols[2] if len(sorted_cols) > 2 else sorted_cols[0]
        if c_desv is None: c_desv = sorted_cols[-1]
        etapas_detectadas.append((nome_etapa, c_eq, c_esp, c_proc, c_desv))

    return etapas_detectadas if len(etapas_detectadas) >= 3 else None


def parse_csv(file_bytes):
    """
    Retorna (ordens, col_map, etapas, info_deteccao, erro).
    Suporta dois formatos:
      - Formato A: ORDEM na col 0, sem super-header, etapas a partir col 13
      - Formato B: LOTE na col 0, super-header com nomes de etapas, colunas flexíveis
    """
    content = None
    for encoding in ['utf-8-sig', 'latin-1', 'cp1252', 'utf-8']:
        try:
            content = file_bytes.decode(encoding)
            break
        except:
            continue
    if content is None:
        return None, None, None, {}, "Não foi possível ler o arquivo. Verifique o encoding."

    sep = detectar_separador(content)
    lines = content.replace('\r\n', '\n').replace('\r', '\n').split('\n')

    # ── Detectar linha de cabeçalho (flexível: aceita ORDEM ou LOTE) ──────────
    header_idx = None
    for i, line in enumerate(lines):
        lu = line.upper()
        # Identificador de lote/ordem: LOTE, ORDEM, ORDER, BATCH
        has_identif = ('LOTE' in lu or 'ORDEM' in lu or
                       'ORDER' in lu or 'BATCH' in lu)
        # Produto/material obrigatório
        has_produto = ('SKU' in lu or 'PRODUTO' in lu or
                       'MATERIAL' in lu or 'DESCRI' in lu)
        if has_identif and has_produto:
            header_idx = i
            break

    if header_idx is None:
        return None, None, None, {}, (
            "Formato não reconhecido. O cabeçalho deve conter colunas de LOTE/ORDEM e SKU/PRODUTO."
        )

    header_parts = lines[header_idx].rstrip(sep).split(sep)

    # ── Construir col_map preservando PRIMEIRA ocorrência (evita sobrescrever) ─
    col_map = {}
    for i, h in enumerate(header_parts):
        key = h.strip().upper()
        if key and key not in col_map:
            col_map[key] = i

    # ── Detectar super-header (linha antes do header com nomes de etapas) ──────
    super_header_parts = None
    if header_idx > 0:
        prev = lines[header_idx - 1].split(sep)
        non_empty = [v.strip() for v in prev if v.strip()]
        # Super-header legítimo: múltiplas células com "/" (padrão de relatórios ERP)
        slash_count = sum(1 for v in non_empty if '/' in v)
        if slash_count >= 2 or len(non_empty) >= 4:
            super_header_parts = prev

    # ── Detectar etapas (3 métodos em cascata) ───────────────────────────────
    modo_etapas = "padrão (fallback)"
    etapas = None

    if super_header_parts is not None:
        etapas = detectar_etapas_por_super_header(header_parts, super_header_parts)
        if etapas:
            modo_etapas = f"super-header ({len(etapas)} etapas detectadas)"

    if etapas is None:
        etapas = detectar_etapas_por_header(header_parts)
        if etapas:
            modo_etapas = f"keywords no header ({len(etapas)} etapas)"

    if etapas is None:
        etapas = ETAPAS_PADRAO
        modo_etapas = "padrão fixo (fallback — colunas originais)"

    # ── Parse das linhas de dados ─────────────────────────────────────────────
    ordens = []
    for line in lines[header_idx + 1:]:
        if not line.strip():
            continue
        partes = line.rstrip(sep).split(sep)
        if len(partes) < 5:
            continue
        # Aceita identificadores numéricos e alfanuméricos (OP-1234, 26010499, etc.)
        first_val = partes[0].strip()
        if not first_val or not re.match(r'^[A-Z0-9]', first_val.upper()):
            continue
        min_cols = max(125, len(header_parts))
        while len(partes) < min_cols:
            partes.append('')
        ordens.append(partes)

    if not ordens:
        return None, None, None, {}, (
            f"Nenhuma ordem encontrada. Separador detectado: '{sep}'. "
            "Verifique se o arquivo tem linhas de dados após o cabeçalho."
        )

    info = {
        "separador": sep,
        "header_linha": header_idx,
        "total_colunas": len(header_parts),
        "modo_etapas": modo_etapas,
        "etapas": etapas,
        "col_map_sample": dict(list(col_map.items())[:25]),
    }
    return ordens, col_map, etapas, info, None


def extrair_dados(ordens, col_map, etapas):
    """Extrai dados usando col_map para campos básicos e etapas para rotas."""

    # Detectar colunas básicas com fallbacks para ambos os formatos
    c_ordem   = encontrar_col_idx(col_map,
                    'LOTE', 'ORDEM', 'ORDER', 'BATCH', default=0)
    c_sku     = encontrar_col_idx(col_map,
                    'SKU', 'CÓD. MATERIAL', 'COD. MATERIAL', 'MATERIAL', default=1)
    c_produto = encontrar_col_idx(col_map,
                    'PRODUTO', 'DESCRI', 'PRODUCT', 'NOME', default=2)
    c_lt_real = encontrar_col_idx(col_map,
                    'LEAD TIME TOTAL REAL', 'LT TOTAL REAL', 'LEAD TIME REAL', 'LT REAL', default=6)
    c_lt_pad  = encontrar_col_idx(col_map,
                    'LEAD TIME PADRÃO', 'LEAD TIME PADRAO', 'LT PADRÃO', 'LT PADRAO',
                    'LT PADR', 'LT STAND', default=7)
    c_desvio  = encontrar_col_idx(col_map,
                    'DESVIO DE LEAD TIME', 'DESVIO TOTAL', 'DESVIO', default=8)
    c_espera  = encontrar_col_idx(col_map,
                    'ESPERA TOTAL REAL', 'ESPERA TOTAL', 'TOTAL ESPERA', default=9)
    c_proc    = encontrar_col_idx(col_map,
                    'PROCESSO TOTAL REAL', 'PROCESSO TOTAL', 'PROCESS TOTAL', default=10)

    def get(row, idx, fallback=''):
        if idx is None or idx >= len(row):
            return fallback
        return row[idx].strip()

    produtos = defaultdict(list)
    for row in ordens:
        ordem   = get(row, c_ordem)
        sku     = get(row, c_sku)
        produto = get(row, c_produto)
        lt_real   = parse_valor(get(row, c_lt_real,   '0'))
        lt_padrao = parse_valor(get(row, c_lt_pad,    '0'))
        desvio    = parse_valor(get(row, c_desvio,    '0'))
        espera_t  = parse_valor(get(row, c_espera,    '0'))
        proc_t    = parse_valor(get(row, c_proc,      '0'))

        rota = []
        for nome_etapa, c_eq, c_esp, c_prc, c_dsv in etapas:
            equip = get(row, c_eq)
            esp   = parse_valor(get(row, c_esp,  '0'))
            proc  = parse_valor(get(row, c_prc,  '0'))
            desv  = parse_valor(get(row, c_dsv,  '0'))
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
                linhas.append(f"  -> {nome} ({equips}): desvio médio {avg_dev:.2f}d | máx {max_dev:.2f}d | espera média {avg_esp:.2f}d")
        piores   = sorted(ordens, key=lambda x: x['desvio'], reverse=True)[:3]
        melhores = sorted(ordens, key=lambda x: x['desvio'])[:3]
        linhas.append(f"  [!] Piores: ordens {', '.join(o['ordem'] for o in piores)} (desvios: {', '.join(str(round(o['desvio'],1))+'d' for o in piores)})")
        linhas.append(f"  [OK] Melhores: ordens {', '.join(o['ordem'] for o in melhores)} (desvios: {', '.join(str(round(o['desvio'],1))+'d' for o in melhores)})")
    return '\n'.join(linhas)

def chamar_claude(system_prompt, messages, api_key, model="claude-opus-4-6"):
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=3000,
        system=system_prompt,
        messages=messages
    )
    return msg.content[0].text

# ─── Funções de Export ────────────────────────────────────────────────────────
def limpar_texto(texto):
    """Remove/substitui caracteres fora do Latin-1 para compatibilidade com PDF."""
    substituicoes = {
        '—': ' - ', '–': '-',
        '\u2019': "'", '\u2018': "'", '\u201c': '"', '\u201d': '"',
        '→': '->', '⚠': '[!]', '✓': '[v]', '✅': '[OK]',
        '🗺️': '', '🔴': '>>>', '📊': '', '📈': '', '🏭': '',
        '💬': '', '💡': '', '🔍': '', '⚙️': '', '🔄': '',
        '⏱️': '', '🎯': '', '📂': '', '🗑️': '',
    }
    for simbolo, sub in substituicoes.items():
        texto = texto.replace(simbolo, sub)
    return re.sub(r'[^\x00-\xFF\n]', '', texto)

def gerar_pdf(texto, titulo="Diagnostico de Fluxo Produtivo"):
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    MARGIN_L, MARGIN_R, MARGIN_T = 15, 15, 22
    CONTENT_W = 210 - MARGIN_L - MARGIN_R  # 180mm (A4)
    INDENT = 5  # recuo para bullet points

    texto_limpo = limpar_texto(texto)

    class PDF(FPDF):
        def header(self):
            self.set_fill_color(31, 78, 121)
            self.set_text_color(255, 255, 255)
            self.set_font('Helvetica', 'B', 13)
            self.multi_cell(CONTENT_W, 12, titulo, fill=True,
                            new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
            self.set_text_color(0, 0, 0)
            self.ln(3)
        def footer(self):
            self.set_y(-15)
            self.set_font('Helvetica', 'I', 8)
            self.set_text_color(128, 128, 128)
            self.cell(0, 10, f'Pagina {self.page_no()}', align='C')

    pdf = PDF()
    pdf.set_margins(MARGIN_L, MARGIN_T, MARGIN_R)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    for linha in texto_limpo.split('\n'):
        linha = linha.rstrip()
        if not linha:
            pdf.ln(3); continue
        if linha.startswith('## '):
            pdf.set_font('Helvetica', 'B', 12)
            pdf.set_fill_color(214, 228, 240)
            pdf.set_text_color(31, 78, 121)
            pdf.multi_cell(CONTENT_W, 8, linha[3:], fill=True,
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0); pdf.ln(2)
        elif linha.startswith('### '):
            pdf.set_font('Helvetica', 'B', 11)
            pdf.set_text_color(46, 117, 182)
            pdf.multi_cell(CONTENT_W, 7, linha[4:],
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0)
        elif linha.startswith('- ') or linha.startswith('* '):
            pdf.set_font('Helvetica', '', 10)
            pdf.set_x(MARGIN_L + INDENT)
            pdf.multi_cell(CONTENT_W - INDENT, 6, '- ' + linha[2:],
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        else:
            pdf.set_font('Helvetica', '', 10)
            pdf.multi_cell(CONTENT_W, 6, linha,
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    return bytes(pdf.output())

def botoes_export(texto, prefixo="diagnostico", key_suffix=""):
    try:
        st.download_button(
            label="📄 Baixar PDF",
            data=gerar_pdf(texto),
            file_name=f"{prefixo}.pdf",
            mime="application/pdf",
            use_container_width=True,
            key=f"dl_{prefixo}_{key_suffix}"
        )
    except Exception as e:
        st.error(f"Erro ao gerar PDF: {e}")

# ─── Interface ────────────────────────────────────────────────────────────────
st.title("🏭 Agente de Otimização de Fluxo Produtivo")
st.caption("Carregue o Relatório de Lead Time (Analítico) e receba recomendações baseadas nas rotas históricas.")

if 'resumo_dados'       not in st.session_state: st.session_state.resumo_dados       = None
if 'historico_chat'     not in st.session_state: st.session_state.historico_chat     = []
if 'ultimo_diagnostico' not in st.session_state: st.session_state.ultimo_diagnostico = None
if 'relatorio_debate'   not in st.session_state: st.session_state.relatorio_debate   = None

with st.sidebar:
    st.header("⚙️ Configuração")
    api_key = st.text_input("API Key da Anthropic", type="password", placeholder="sk-ant-...")
    st.markdown("[👉 Obter API Key](https://console.anthropic.com)")
    st.divider()
    st.markdown("**Formato esperado:**")
    st.markdown("Relatório de Lead Time de Ordem/Lote (Analítico) — `.csv` separado por `;` ou `,`.")
    if st.session_state.resumo_dados:
        st.divider()
        st.success("✅ Dados carregados")
        if st.button("🗑️ Limpar dados e chat", use_container_width=True):
            st.session_state.resumo_dados       = None
            st.session_state.historico_chat     = []
            st.session_state.ultimo_diagnostico = None
            st.session_state.relatorio_debate   = None
            st.rerun()

# ─── Seção 1: Upload ──────────────────────────────────────────────────────────
st.subheader("📂 1. Carregar Relatório")
arquivo = st.file_uploader("Selecione o arquivo CSV", type=["csv"], label_visibility="collapsed")

if arquivo:
    file_bytes = arquivo.read()
    ordens, col_map, etapas, info, erro = parse_csv(file_bytes)
    if erro:
        st.error(f"❌ {erro}")
    else:
        produtos = extrair_dados(ordens, col_map, etapas)
        total_ordens = sum(len(v) for v in produtos.values())

        col1, col2, col3 = st.columns(3)
        col1.metric("Ordens encontradas", total_ordens)
        col2.metric("SKUs distintos", len(produtos))
        todos_lts = [o['lt_real'] for ords in produtos.values() for o in ords if o['lt_real'] > 0]
        lt_medio = sum(todos_lts) / len(todos_lts) if todos_lts else 0
        col3.metric("Lead Time médio geral", f"{lt_medio:.1f} dias")

        # Aviso se nenhuma rota foi detectada (etapas com problemas)
        ordens_com_rota = sum(1 for ords in produtos.values() for o in ords if o['rota'])
        if ordens_com_rota == 0 and total_ordens > 0:
            st.warning(
                "⚠️ **Dados de lead time carregados, mas nenhuma rota de etapas foi detectada.** "
                "Abra a aba '🔧 Debug' abaixo para ver quais colunas foram encontradas."
            )
        else:
            st.success(f"✅ {info.get('modo_etapas', '')} | {ordens_com_rota}/{total_ordens} ordens com rota")

        with st.expander("📋 Produtos encontrados"):
            for chave, ords in sorted(produtos.items()):
                lts  = [o['lt_real'] for o in ords if o['lt_real'] > 0]
                devs = [o['desvio']  for o in ords]
                avg_lt = sum(lts)/len(lts)   if lts  else 0
                avg_d  = sum(devs)/len(devs) if devs else 0
                st.markdown(f"**{chave}** — {len(ords)} ordens | LT médio: {avg_lt:.1f}d | Desvio médio: {avg_d:.1f}d")

        with st.expander("🔧 Debug — Colunas detectadas"):
            st.markdown(f"**Separador:** `{info.get('separador')}`")
            st.markdown(f"**Header na linha:** {info.get('header_linha')}")
            st.markdown(f"**Total de colunas:** {info.get('total_colunas')}")
            st.markdown(f"**Detecção de etapas:** {info.get('modo_etapas')}")
            st.markdown("**Etapas mapeadas:**")
            for e in etapas:
                st.text(f"  {e[0]}: equip={e[1]}, espera={e[2]}, proc={e[3]}, desvio={e[4]}")
            st.markdown("**Primeiras 20 colunas:**")
            for nome, idx in sorted(info.get('col_map_sample', {}).items(), key=lambda x: x[1]):
                st.text(f"  [{idx:3d}] {nome}")

        st.session_state.resumo_dados       = formatar_resumo(produtos)
        st.session_state.historico_chat     = []
        st.session_state.ultimo_diagnostico = None
        st.session_state.relatorio_debate   = None

st.divider()

# ─── Seções 2 e 3 ─────────────────────────────────────────────────────────────
if st.session_state.resumo_dados:
    if not api_key:
        st.warning("⚠️ Insira sua API Key na barra lateral para usar o agente.")
    else:
        st.subheader("📊 2. Diagnóstico Completo")
        if st.button("🔍 Gerar Diagnóstico Completo", type="primary", use_container_width=True):
            with st.spinner("Analisando rotas e padrões históricos..."):
                try:
                    resultado = chamar_claude(
                        SYSTEM_GERAL,
                        [{"role": "user", "content": st.session_state.resumo_dados}],
                        api_key
                    )
                    st.session_state.ultimo_diagnostico = resultado
                    st.session_state.historico_chat = [
                        {"role": "user",      "content": "Gere um diagnóstico completo do fluxo produtivo com base nos dados carregados."},
                        {"role": "assistant", "content": resultado, "exportavel": True},
                    ]
                except anthropic.AuthenticationError:
                    st.error("❌ API Key inválida.")
                except Exception as e:
                    st.error(f"❌ Erro: {str(e)}")

        if st.session_state.ultimo_diagnostico:
            st.markdown(st.session_state.ultimo_diagnostico)
            st.markdown("**Exportar diagnóstico:**")
            botoes_export(st.session_state.ultimo_diagnostico, prefixo="diagnostico_fluxo", key_suffix="diag")

        st.divider()

        st.subheader("💬 3. Debate & Perguntas")
        st.caption("Debata as sugestões do diagnóstico acima ou faça perguntas sobre produtos, metas, turnos, equipamentos ou qualquer cenário específico.")

        with st.expander("💡 Exemplos de perguntas"):
            st.markdown("""
- *Para atender a demanda desse mês preciso reduzir o lead time do Gripalce em 3 dias. O que posso fazer?*
- *Qual etapa está causando mais espera no Salicetil? Vale a pena um turno adicional?*
- *Se eu aumentar o OEE da Blisterflex em 10%, quanto isso reduz o lead time?*
- *Quais produtos poderiam ter a rota recalibrada para liberar capacidade no Bosch-46?*
- *Compare o desempenho do MN41-12 e MN41-68. Qual está com mais ineficiências?*
            """)

        for i, msg in enumerate(st.session_state.historico_chat):
            with st.chat_message(msg["role"], avatar="🧑" if msg["role"] == "user" else "🤖"):
                st.markdown(msg["content"])
                if msg["role"] == "assistant" and msg.get("exportavel"):
                    botoes_export(msg["content"], prefixo="resposta_agente", key_suffix=str(i))

        # ─── Botão "Discussão Concluída" ─────────────────────────────────────────
        # Aparece após pelo menos uma rodada de debate além do diagnóstico inicial
        if len(st.session_state.historico_chat) > 2:
            st.divider()
            if st.button("✅ Discussão Concluída — Gerar Relatório", use_container_width=True):
                contexto_debate = f"""Histórico de produção dos últimos 90 dias (base da análise):

{st.session_state.resumo_dados}

---
Histórico completo da discussão:

"""
                for msg in st.session_state.historico_chat:
                    papel = "Equipe da fábrica" if msg["role"] == "user" else "Agente de análise"
                    contexto_debate += f"**{papel}:**\n{msg['content']}\n\n"

                with st.spinner("Consolidando aprendizados e plano de ação..."):
                    try:
                        relatorio = chamar_claude(
                            SYSTEM_RELATORIO,
                            [{"role": "user", "content": contexto_debate}],
                            api_key
                        )
                        st.session_state.relatorio_debate = relatorio
                    except anthropic.AuthenticationError:
                        st.error("❌ API Key inválida.")
                    except Exception as e:
                        st.error(f"❌ Erro ao gerar relatório: {str(e)}")

        if st.session_state.relatorio_debate:
            st.divider()
            st.subheader("📋 Relatório da Discussão")
            st.markdown(st.session_state.relatorio_debate)
            st.markdown("**Exportar relatório:**")
            botoes_export(st.session_state.relatorio_debate, prefixo="relatorio_discussao", key_suffix="rel")
            st.divider()

        pergunta = st.chat_input("Faça sua pergunta sobre o fluxo produtivo...")
        if pergunta:
            with st.chat_message("user", avatar="🧑"):
                st.markdown(pergunta)

            # Contexto principal: diagnóstico gerado (comprimido) + índice de SKUs e
            # equipamentos extraído dos dados brutos (para matching de nomes parciais).
            # Fallback para dados brutos truncados se o diagnóstico ainda não existe.
            skus_ref = "\n".join(
                linha for linha in st.session_state.resumo_dados.split('\n')
                if linha.startswith('PRODUTO:') or linha.strip().startswith('->')
            )
            contexto_comprimido = (
                st.session_state.ultimo_diagnostico
                or st.session_state.resumo_dados[:6000]
            )
            contexto_inicial = f"""Você é um especialista em fluxo produtivo industrial. Abaixo está a análise dos dados de produção dos últimos 90 dias:

{contexto_comprimido}

---
ÍNDICE DE PRODUTOS E EQUIPAMENTOS DA BASE (use para identificar o produto mencionado pelo usuário, mesmo que o nome seja parcial ou aproximado):
{skus_ref}

---
Responda à pergunta do usuário com base nessa análise. Respeite todas as restrições mencionadas na conversa."""

            # Limita o histórico às últimas 10 mensagens para controlar o uso de tokens
            historico_recente = st.session_state.historico_chat[-10:]

            messages_para_claude = [
                {"role": "user",      "content": contexto_inicial},
                {"role": "assistant", "content": "Entendido. Tenho a análise carregada e estou pronto para responder."},
            ]
            for msg in historico_recente:
                messages_para_claude.append({"role": msg["role"], "content": msg["content"]})
            messages_para_claude.append({"role": "user", "content": pergunta})

            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("Analisando..."):
                    try:
                        resposta = chamar_claude(SYSTEM_ESPECIFICO, messages_para_claude, api_key, model="claude-sonnet-4-6")
                        st.markdown(resposta)
                        botoes_export(resposta, prefixo="resposta_agente", key_suffix="current")
                        st.session_state.historico_chat.append({"role": "user",      "content": pergunta})
                        st.session_state.historico_chat.append({"role": "assistant", "content": resposta, "exportavel": True})
                    except anthropic.AuthenticationError:
                        st.error("❌ API Key inválida.")
                    except Exception as e:
                        st.error(f"❌ Erro: {str(e)}")
else:
    st.info("👆 Carregue o arquivo CSV para habilitar o agente.")

st.divider()
st.caption("Beta v0.5 · Agente de Otimização de Fluxo Produtivo")
