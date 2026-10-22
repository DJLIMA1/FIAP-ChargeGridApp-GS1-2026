"""PDFs do recibo, do resultado do dono e do histórico do motorista (ReportLab).

O ReportLab é importado só dentro das funções: as outras rotas não pagam o import no cold
start da função serverless. Os documentos recebem os mesmos dicionários já serializados
pela API (recibo v1, relatório de margem, histórico) e não recalculam nenhum valor.

Fonte Helvetica (WinAnsi): acentos do pt-BR funcionam; caracteres fora da tabela são
trocados por equivalentes (``−`` vira ``-``). Todo PDF leva "Documento sem valor fiscal".
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal

from chargegrid_core.analytics import local, parse_time
from chargegrid_core.formatting import brl, kwh

COMPRESS = True  # os testes desligam para procurar texto no PDF
MAX_DETAIL_ROWS = 1000
_REPLACE = {"−": "-", "→": "->", "≠": "!=", "≥": ">=", "≤": "<=", "✓": "OK", " ": " ", " ": " "}
GREEN = "#1F7A4D"
AMBER_BG = "#FFF4DA"
AMBER_FG = "#7A4B00"
GRAY = "#5F6368"
LINE = "#D9DCE1"


def safe(text) -> str:
    """Texto compatível com a fonte padrão (cp1252)."""
    value = "" if text is None else str(text)
    out = []
    for char in value:
        char = _REPLACE.get(char, char)
        try:
            char.encode("cp1252")
        except UnicodeEncodeError:
            char = "?"
        out.append(char)
    return "".join(out)


def when(value, fmt="%d/%m/%Y %H:%M") -> str:
    moment = parse_time(value)
    return local(moment).strftime(fmt) if moment else "—"


def money(value) -> str:
    return brl(value) if value is not None else "—"


def per_kwh(value) -> str:
    return brl(value) + "/kWh" if value is not None else "—"


def _kwh(value, digits=3) -> str:
    return kwh(value, digits) if value is not None else "—"


def _number(value, digits=2) -> str:
    if value is None:
        return "—"
    return f"{Decimal(str(value)):.{digits}f}".replace(".", ",")


class _Kit:
    """Peças do ReportLab carregadas sob demanda."""

    def __init__(self):
        from reportlab.graphics.charts.lineplots import LinePlot
        from reportlab.graphics.shapes import Drawing, String
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        self.colors, self.mm, self.A4, self.landscape = colors, mm, A4, landscape
        self.Paragraph, self.Spacer, self.Table, self.TableStyle = Paragraph, Spacer, Table, TableStyle
        self.KeepTogether, self.SimpleDocTemplate = KeepTogether, SimpleDocTemplate
        self.Drawing, self.String, self.LinePlot = Drawing, String, LinePlot
        base = getSampleStyleSheet()
        self.styles = {
            "title": ParagraphStyle("t", parent=base["Title"], fontName="Helvetica-Bold", fontSize=17,
                                    alignment=TA_LEFT, spaceAfter=2, textColor=colors.HexColor("#111111")),
            "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11.5,
                                 spaceBefore=9, spaceAfter=4, textColor=colors.HexColor(GREEN)),
            "body": ParagraphStyle("b", parent=base["BodyText"], fontName="Helvetica", fontSize=9, leading=12),
            "small": ParagraphStyle("s", parent=base["BodyText"], fontName="Helvetica", fontSize=7.8, leading=10,
                                    textColor=colors.HexColor(GRAY)),
            "cell": ParagraphStyle("c", parent=base["BodyText"], fontName="Helvetica", fontSize=7.6, leading=9.4),
            "banner": ParagraphStyle("w", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=8.8,
                                     leading=11.5, textColor=colors.HexColor(AMBER_FG)),
        }

    def p(self, text, style="body"):
        from xml.sax.saxutils import escape

        return self.Paragraph(escape(safe(text)), self.styles[style])

    def banner(self, lines):
        content = [[self.p(line, "banner")] for line in lines]
        table = self.Table(content, colWidths=["100%"])
        table.setStyle(self.TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), self.colors.HexColor(AMBER_BG)),
            ("BOX", (0, 0), (-1, -1), 0.6, self.colors.HexColor("#E5B74C")),
            ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]))
        return table

    def pairs(self, items, widths=None):
        """Tabela rótulo → valor (duas colunas)."""
        data = [[self.p(label, "small"), self.p(value)] for label, value in items]
        table = self.Table(data, colWidths=widths or [48 * self.mm, None], hAlign="LEFT")
        table.setStyle(self.TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, self.colors.HexColor(LINE)),
            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        return table

    def grid(self, header, rows, widths=None, numeric_from=None, bold_last=False):
        data = [[self.p(cell, "cell") for cell in header]] + [[self.p(cell, "cell") for cell in row] for row in rows]
        table = self.Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), self.colors.HexColor("#EEF2F0")),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, self.colors.HexColor(LINE)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]
        if bold_last and rows:
            style.append(("BACKGROUND", (0, len(rows)), (-1, len(rows)), self.colors.HexColor("#F4F6F5")))
        table.setStyle(self.TableStyle(style))
        return table

    def build(self, story, title, *, wide=False, generated_at=None) -> bytes:
        buffer = io.BytesIO()
        size = self.landscape(self.A4) if wide else self.A4
        stamp = when(generated_at or datetime.now().astimezone().isoformat())
        doc = self.SimpleDocTemplate(buffer, pagesize=size, title=safe(title), author="ChargeGrid",
                                     leftMargin=14 * self.mm, rightMargin=14 * self.mm, topMargin=16 * self.mm,
                                     bottomMargin=15 * self.mm, invariant=1, pageCompression=1 if COMPRESS else 0)
        colors, mm = self.colors, self.mm

        def frame(canvas, document):
            canvas.saveState()
            canvas.setFillColor(colors.HexColor(GREEN))
            canvas.setFont("Helvetica-Bold", 9)
            canvas.drawString(14 * mm, size[1] - 10 * mm, "ChargeGrid")
            canvas.setFillColor(colors.HexColor(GRAY))
            canvas.setFont("Helvetica", 7.5)
            canvas.drawRightString(size[0] - 14 * mm, size[1] - 10 * mm, safe(title))
            canvas.drawString(14 * mm, 8 * mm, safe(f"Gerado em {stamp} (horário de São Paulo) · "
                                                   "Documento sem valor fiscal"))
            canvas.drawRightString(size[0] - 14 * mm, 8 * mm, f"Página {document.page}")
            canvas.restoreState()

        doc.build(story, onFirstPage=frame, onLaterPages=frame)
        return buffer.getvalue()


# ------------------------------------------------------------------- recibo

def _power_chart(kit, samples, width):
    points = []
    first = parse_time(samples[0]["t"])
    for sample in samples:
        moment = parse_time(sample["t"])
        points.append(((moment - first).total_seconds() / 60, float(Decimal(sample["kw"]))))
    height = 46 * kit.mm
    drawing = kit.Drawing(width, height)
    plot = kit.LinePlot()
    plot.x, plot.y, plot.width, plot.height = 28, 16, width - 40, height - 26
    plot.data = [points]
    plot.lines[0].strokeColor = kit.colors.HexColor(GREEN)
    plot.lines[0].strokeWidth = 1.4
    top = max(kw for _, kw in points) or 1
    plot.yValueAxis.valueMin, plot.yValueAxis.valueMax = 0, top * 1.15
    plot.xValueAxis.valueMin = 0
    plot.xValueAxis.valueMax = max(points[-1][0], 1)
    for axis in (plot.xValueAxis, plot.yValueAxis):
        axis.labels.fontName, axis.labels.fontSize = "Helvetica", 6.5
    plot.yValueAxis.labelTextFormat = lambda value: f"{value:.1f}".replace(".", ",")
    plot.xValueAxis.labelTextFormat = lambda value: f"{value:.0f}"
    drawing.add(plot)
    drawing.add(kit.String(0, height - 8, "kW", fontName="Helvetica", fontSize=6.5))
    drawing.add(kit.String(width - 60, 2, "minutos desde o início", fontName="Helvetica", fontSize=6.5))
    return drawing


DRIVER_PRICE_KEYS = ("power_tier", "locked_price", "coupon")


def _driver_price(price: dict) -> tuple[list, list]:
    """Preço do recibo do MOTORISTA: velocidade, preço travado e cupom. Ajuste por demanda e tarifa
    base/do horário não aparecem para o motorista (o dono vê tudo nas exportações dele)."""
    rows = []
    for line in price["lines"]:
        if line.get("key") not in DRIVER_PRICE_KEYS:
            continue
        unit = line.get("unit")
        if line["key"] == "locked_price":
            rows.append(("Preço por kWh", per_kwh(line["value"])))
        elif unit == "%":
            rows.append((line["label"], f"{line['value']}%"))
        else:
            rows.append((line["label"], str(line["value"])))
    moment = "na reserva" if price.get("locked_by") == "reservation" else "no início da recarga"
    explanation = [f"Preço de {per_kwh(price.get('price_per_kwh'))} travado {moment} "
                   f"({when(price.get('locked_at'), '%d/%m %H:%M')}); não muda durante a recarga."]
    coupon = price.get("coupon") or {}
    if coupon.get("discount_percent"):
        label = f"Cupom {coupon['code']}" if coupon.get("code") else "Cupom"
        explanation.append(f"{label}: −{coupon['discount_percent']}% sobre a energia.")
    return rows, explanation


def receipt_pdf(receipt: dict) -> bytes:
    kit = _Kit()
    labels, times, price = receipt["labels"], receipt["times"], receipt["price"]
    energy, charges, power = receipt["energy"], receipt["charges"], receipt["power"]
    title = f"Recibo de recarga nº {receipt['number']}"
    story = [kit.p(title, "title"),
             kit.p("Provisório: recarga em andamento." if not receipt["final"] else "Recibo final da recarga.",
                   "small"),
             kit.Spacer(1, 4), kit.banner(labels["notes"]), kit.Spacer(1, 2)]
    point = receipt["point"]
    story += [kit.p("Onde e quando", "h2"), kit.pairs([
        ("Posto", receipt["station"]["name"]), ("Endereço", receipt["station"].get("address") or "—"),
        ("Ponto", " · ".join(str(v) for v in (point.get("public_code"), point.get("connector_type")) if v) or "—"),
        ("Início", when(times["started_at"])), ("Fim", when(times["ended_at"])),
        ("Duração", f"{_number(times['duration_minutes'], 0)} min" if times["duration_minutes"] else "—"),
        ("Situação", times.get("status_label") or "—"),
        ("Motivo de término", times.get("end_reason_label") or "—"),
    ])]
    rows, explanation = _driver_price(price)
    story += [kit.p("Preço aceito", "h2"), kit.pairs(rows)]
    story += [kit.p(text, "small") for text in explanation]
    story += [kit.p("Energia", "h2"), kit.pairs([
        ("Energia", _kwh(energy["kwh"])), ("Origem", energy["source_label"]), ("Confirmação", energy["note"]),
        ("Bateria", f"{_number(energy['soc_start'], 0)}% → {_number(energy['soc_end'], 0)}%"
         if energy.get("soc_start") and energy.get("soc_end") else "—"),
    ])]
    value_rows = [("Energia antes do cupom", money(charges["energy_gross"])),
                  ("Desconto do cupom", "- " + money(charges["discount"])),
                  ("Energia", money(charges["energy_total"]))]
    if charges.get("overstay") is not None:
        value_rows.append(("Taxa de permanência", money(charges["overstay"])))
    if charges.get("paid_total") is not None:
        # Pagamento acertado: o capturado manda; a diferença para o calculado aparece linha a linha.
        value_rows.append(("Calculado pela energia", money(charges.get("calculated_total") or charges["total"])))
        value_rows += [(line["label"], money(line["amount"])) for line in charges.get("adjustments") or []]
        value_rows.append(("Total pago (confirmado)", money(charges["paid_total"])))
    else:
        value_rows.append(("Total", money(charges["total"])))
    story += [kit.p("Valores", "h2"), kit.pairs(value_rows)]
    if charges.get("note"):
        story.append(kit.p(charges["note"], "small"))
    payment = receipt["payment"]
    story.append(kit.p("Pagamento", "h2"))
    if payment.get("status") == "available":
        story.append(kit.pairs([
            ("Provedor", payment.get("provider") or "—"),
            ("Identificador", payment.get("provider_reference") or "—"),
            ("Situação", payment.get("status_label") or payment.get("payment_status") or "—"),
            ("Autorizado", money(payment.get("authorized_amount"))),
            ("Consumido", money(payment.get("captured_amount"))),
            ("Devolvido", money(payment.get("refunded_amount"))),
        ]))
    else:
        story.append(kit.p(payment.get("note") or "Sem pagamento registrado.", "small"))
    overstay = receipt["overstay"]
    if overstay.get("status") == "available":
        story += [kit.p("Permanência após a recarga", "h2"), kit.pairs([
            ("Minutos cobrados", str(overstay.get("billable_minutes") or "—")),
            ("Valor", money(overstay.get("amount"))),
        ])]
    width = kit.A4[0] - 28 * kit.mm
    chart = _power_chart(kit, power["samples"], width) if power["samples"] else \
        kit.p(power.get("note") or "Sem amostras de potência.", "small")
    story.append(kit.KeepTogether([kit.p("Potência ao longo da recarga", "h2"), chart]))
    if power["changes"]:
        story.append(kit.grid(["Horário", "Potência aplicada", "Situação", "Motivo"], [
            [when(change.get("at"), "%H:%M:%S"),
             f"{_number(change.get('applied_kw'), 1)} kW" if change.get("applied_kw") else
             (f"pedido {_number(change.get('requested_kw'), 1)} kW" if change.get("requested_kw") else "—"),
             {"applied": "Confirmada pelo equipamento", "requested": "Solicitada", "failed": "Falhou"}
             .get(change.get("status"), change.get("status") or "—"),
             change.get("reason_label") or "—"] for change in power["changes"]
        ], widths=[24 * kit.mm, 30 * kit.mm, 42 * kit.mm, None]))
    if receipt["timeline"]:
        story += [kit.p("Linha do tempo", "h2"), kit.grid(["Horário", "Fato", "Origem"], [
            [when(event["observed_at"], "%d/%m %H:%M:%S"), event["label"], event["source_label"]]
            for event in receipt["timeline"]], widths=[30 * kit.mm, None, 45 * kit.mm])]
    story.append(kit.Spacer(1, 6))
    story.append(kit.p(f"Sessão {receipt['session_id']} · recibo {receipt['schema']} v{receipt['schema_version']}",
                       "small"))
    return kit.build(story, title, generated_at=receipt.get("generated_at"))


# ------------------------------------------------------------------ margem

def _period(period) -> str:
    start, end = parse_time(period["from"]), parse_time(period["to"])
    return f"{when(start, '%d/%m/%Y %H:%M')} a {when(end, '%d/%m/%Y %H:%M')}"


def _channel(item) -> str:
    """Canal e método (totem 0.8.0), ex.: "Totem · Sem cobrança"; "—" em relatórios sem a informação."""
    parts = [item.get("payment_channel"), item.get("payment_method")]
    return " · ".join(part for part in parts if part) or "—"


def margin_pdf(report: dict, station_name: str | None = None) -> bytes:
    """``report``: ``economics.serialize(margin_report)`` — os mesmos números da tela."""
    kit = _Kit()
    totals = report["totals"]
    title = "Resultado do dono do posto"
    scope = station_name or "Todos os postos"
    story = [kit.p(title, "title"), kit.p(f"{scope} · {_period(report['period'])} · "
                                          f"{totals['sessions']} recarga(s) encerrada(s)", "small"),
             kit.Spacer(1, 4),
             kit.banner(["Receita bruta não é lucro: da receita saem a comissão da plataforma, a tarifa do "
                         "provedor de pagamento e o custo da energia.", *report["warnings"]]),
             kit.p("Da receita à margem", "h2")]
    cascade = [["Receita bruta (antes do cupom)", money(totals["gross"])],
               ["- Cupons", money(totals["discount"])],
               ["= Receita da energia", money(totals["revenue"])]]
    if totals.get("overstay_revenue") is not None:
        cascade.append(["+ Taxa de permanência", money(totals["overstay_revenue"])])
    adjustment = Decimal(str(totals.get("payment_adjustment") or 0))
    if adjustment:
        cascade.append(["± Ajuste do pagamento (perdoado/não cobrado)", money(adjustment)])
    cascade.append(["= Receita cobrada", money(totals["revenue_total"])])
    cascade.append(["- Comissão da plataforma", money(totals["platform_fee"])])
    if totals.get("provider_fee") is not None:
        cascade.append(["- Tarifa do provedor de pagamento", money(totals["provider_fee"])])
    rent = totals.get("central_rent")
    cascade.append(["= Repasse das recargas", money(totals["owner_net"])])
    if rent is not None:
        cascade += [[f"- Aluguel das centrais ({totals.get('centrals') or 0})", money(rent)],
                    ["= Repasse líquido (descontado da folha)", money(totals["owner_net_after_rent"])]]
    cascade.append(["- Custo estimado da energia", money(totals["energy_cost"])])
    if totals["margin"] is not None:
        margin = money(totals["margin"]) + (f" ({_number(totals['margin_percent'], 1)}% da receita)"
                                            if totals.get("margin_percent") is not None else "")
    else:
        coverage = totals["coverage"]
        margin = (f"não calculada: {coverage['missing_energy_cost']} de {coverage['sessions']} sessões sem custo "
                  f"da energia (margem das cobertas: {money(totals['margin_covered'])})")
    if rent is None:
        cascade.append(["= Margem estimada", margin])
    else:
        result = money(totals["result"]) + (f" ({_number(totals['result_percent'], 1)}% da receita)"
                                            if totals.get("result_percent") is not None else "") \
            if totals.get("result") is not None else "não calculado (custo da energia não informado)"
        cascade.append(["Margem de contribuição (antes do aluguel)", margin])
        cascade.append(["= Resultado estimado (após o aluguel)", result])
    story.append(kit.grid(["Linha", "Valor"], cascade, widths=[80 * kit.mm, None], bold_last=True))
    dynamic, coupons = report["dynamic_pricing"], report["coupons"]
    effects = [f"Preço dinâmico (demanda): {money(dynamic['demand_effect'])} em "
               f"{dynamic['sessions_with_increase']} recarga(s)"
               + (f", multiplicador médio {_number(dynamic['average_multiplier'])}×"
                  if dynamic.get("average_multiplier") else "") + "."]
    if dynamic.get("schedule_effect") is not None:
        effects.append(f"Tarifa por horário: {money(dynamic['schedule_effect'])} em relação à base dos conectores.")
    if dynamic.get("speed_effect") is not None:
        effects.append(f"Velocidade escolhida: {money(dynamic['speed_effect'])} em relação à base dos conectores.")
    effects.append(f"Cupons: {money(coupons['discount'])} de desconto em {coupons['sessions']} recarga(s).")
    story += [kit.p("Efeito do preço dinâmico e dos cupons", "h2"), *[kit.p(text) for text in effects]]
    rent_block = report.get("central_rent")
    if rent_block:
        story += [kit.p("Aluguel das centrais", "h2"),
                  kit.p("Valor mensal por central rateado pelos dias de vínculo no mês (horário de São Paulo); "
                        "descontado do repasse.", "small"),
                  kit.grid(["Posto", "Central", "Mês", "Dias", "Mensal", "Valor"],
                           [[line["station_name"], line["central"] or "—", line["month"],
                             f"{line['days']}/{line['days_in_month']}", money(line["monthly_amount"]),
                             money(line["amount"])] for line in rent_block["lines"]]
                           + [["Total", "", "", "", "", money(rent_block["total"])]],
                           bold_last=True)]
    if len(report["by_station"]) > 1 or not station_name:
        header = ["Posto", "Recargas", "kWh", "Receita cobrada", "Comissão", "Repasse", "Custo energia", "Margem"]
        if rent_block:
            header += ["Aluguel", "Resultado"]
        story += [kit.p("Por posto", "h2"), kit.grid(header, [
            [item["station_name"], str(item["sessions"]), _number(item["energy_kwh"], 3),
             money(item["revenue_total"]), money(item["platform_fee"]), money(item["owner_net"]),
             money(item["energy_cost"]), money(item["margin"])]
            + ([money(item.get("central_rent")), money(item.get("result"))] if rent_block else [])
            for item in report["by_station"]])]
    items = report["items"]
    story.append(kit.p("Recargas", "h2"))
    if len(items) > MAX_DETAIL_ROWS:
        story.append(kit.p(f"Mostrando as {MAX_DETAIL_ROWS} recargas mais recentes de {len(items)}. Os totais acima "
                           "incluem todas; o detalhe completo está no CSV.", "small"))
    story.append(kit.grid(
        ["Fim", "Posto", "Ponto", "kWh", "Preço", "Demanda", "Cupom", "Receita", "Comissão", "Repasse", "Custo",
         "Margem", "Canal"],
        [[when(item["ended_at"], "%d/%m %H:%M"), item["station_name"], item["public_code"],
          _number(item["energy_kwh"], 3), per_kwh(item["price_per_kwh"]),
          _number(item["demand_multiplier"]) + "×", f"{item['discount_percent']}%" if item["discount_percent"] else "—",
          money(item["revenue_total"]), money(item["platform_fee"]), money(item["owner_net"]),
          money(item["energy_cost"]), money(item["margin"]), _channel(item)] for item in items[:MAX_DETAIL_ROWS]],
        widths=[21 * kit.mm, None, 18 * kit.mm, 16 * kit.mm, 23 * kit.mm, 16 * kit.mm, 14 * kit.mm, 20 * kit.mm,
                20 * kit.mm, 20 * kit.mm, 20 * kit.mm, 20 * kit.mm, 24 * kit.mm]))
    story += [kit.p("Método", "h2"), *[kit.p(text, "small") for text in report["methodology"]]]
    return kit.build(story, title, wide=True, generated_at=report.get("generated_at"))


# --------------------------------------------------------------- histórico

def history_pdf(report: dict) -> bytes:
    kit = _Kit()
    totals = report["totals"]
    title = "Histórico de recargas"
    notes = ["Valor de cada recarga igual ao do recibo: energia e taxa de permanência ou, com pagamento "
             "confirmado, o valor cobrado."]
    if totals["sources"].get("simulated"):
        notes.insert(0, "Há recargas com energia calculada pelo equipamento, sem medidor.")
    story = [kit.p(title, "title"), kit.p(_period(report["period"]), "small"), kit.Spacer(1, 4), kit.banner(notes),
             kit.p("Resumo", "h2"), kit.pairs([
                 ("Recargas encerradas com energia", str(totals["sessions"])),
                 ("Energia", _kwh(totals["energy_kwh"])), ("Total", money(totals["total"]))])]
    items = report["items"]
    story.append(kit.p("Recargas", "h2"))
    if len(items) > MAX_DETAIL_ROWS:
        story.append(kit.p(f"Mostrando as {MAX_DETAIL_ROWS} mais recentes de {len(items)}; o CSV traz todas.", "small"))
    story.append(kit.grid(
        ["Fim", "Posto", "Ponto", "kWh", "Preço", "Desc.", "Valor", "Origem", "Situação"],
        [[when(item["ended_at"], "%d/%m/%Y %H:%M"), item["station_name"], item["public_code"],
          _number(item["energy_kwh"], 3), per_kwh(item["price_per_kwh"]),
          f"{item['discount_percent']}%" if item["discount_percent"] else "—", money(item["total"]),
          {"simulated": "Calculada", "measured": "Medida", "estimated": "Estimada"}.get(item["source"], "—"),
          item.get("status_label") or "—"] for item in items[:MAX_DETAIL_ROWS]],
        widths=[27 * kit.mm, None, 18 * kit.mm, 15 * kit.mm, 23 * kit.mm, 12 * kit.mm, 19 * kit.mm, 17 * kit.mm,
                27 * kit.mm]))
    story.append(kit.p("Totais: recargas concluídas ou interrompidas com energia, pela data de término (horário de "
                       "São Paulo). Valor de cada recarga arredondado ao centavo.", "small"))
    return kit.build(story, title, generated_at=report.get("generated_at"))
