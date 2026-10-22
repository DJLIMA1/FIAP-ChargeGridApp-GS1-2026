"""PDF do recibo na conta demo, gerado no aparelho com Pillow (sem ReportLab no app).

Lê o mesmo recibo ``chargegrid.receipt`` que a tela mostra (com os textos neutros de ``ui.wording``) e
desenha uma página A4 simples, marcada só "Documento sem valor fiscal". Como na tela do motorista, mostra só o preço travado por
kWh (sem tarifa base nem ajuste por demanda, que são dados do vendedor).
"""

import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from chargegrid_core.formatting import brl, duration, kwh

from .ui.wording import clean_receipt

MARK = 'Documento sem valor fiscal'
WIDTH, HEIGHT, MARGIN = 1240, 1754, 96  # A4 a 150 dpi
FONT_DIR = Path(__file__).resolve().parents[2] / 'assets'
INK, MUTED, LINE = (20, 20, 20), (105, 105, 105), (215, 215, 215)
PAYMENT_METHODS = {'card': 'Cartão', 'pix': 'Pix', 'wallet': 'Saldo', 'balance': 'Saldo'}


def _font(weight, size):
    from PIL import ImageFont

    try:
        return ImageFont.truetype(str(FONT_DIR / f'Inter-{weight}.ttf'), size)
    except OSError:  # fontes fora do pacote: a fonte padrão do Pillow (com FreeType) também serve
        return ImageFont.load_default(size)


def _dec(value):
    try:
        return None if value in (None, '') else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _money(value):
    number = _dec(value)
    return brl(number) if number is not None else '—'


def _stamp(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone().strftime('%d/%m/%Y %H:%M')
    except (TypeError, ValueError):
        return '—'


def _price(value):
    number = _dec(value)
    if number is None:
        return '—'
    if number == number.quantize(Decimal('0.01')):
        return brl(number) + '/kWh'
    return 'R$ ' + f'{number.quantize(Decimal("0.0001")):.4f}'.replace('.', ',') + '/kWh'


def rows(receipt):
    """Seções do PDF: ``[(título, [(rótulo, valor), ...]), ...]`` (também usadas pelos testes)."""
    receipt = clean_receipt(receipt)
    station, point, times = receipt.get('station') or {}, receipt.get('point') or {}, receipt.get('times') or {}
    energy, charges, price = receipt.get('energy') or {}, receipt.get('charges') or {}, receipt.get('price') or {}
    payment = receipt.get('payment') or {}
    minutes = _dec(times.get('duration_minutes'))
    place = [('Posto', station.get('name') or '—'), ('Endereço', station.get('address') or '—'),
             ('Ponto', ' · '.join(str(part) for part in (point.get('public_code'), point.get('connector_type'))
                                 if part) or '—')]
    session = [('Início', _stamp(times.get('started_at') or times.get('created_at'))),
               ('Fim', _stamp(times.get('ended_at')) if times.get('ended_at') else '—'),
               ('Duração', duration(minutes) if minutes is not None else '—'),
               ('Situação', times.get('status_label') or times.get('status') or '—')]
    if times.get('end_reason_label'):
        session.append(('Término', times['end_reason_label']))
    session.append(('Energia', kwh(_dec(energy.get('kwh')) or 0, 2)))
    if energy.get('soc_end'):
        start = f"{_dec(energy['soc_start']):.0f}% → " if energy.get('soc_start') else ''
        session.append(('Bateria', f"{start}{_dec(energy['soc_end']):.0f}%"))
    costs = [('Preço travado', _price(price.get('price_per_kwh')))]
    discount = _dec(charges.get('discount')) or Decimal(0)
    if discount:
        code = (price.get('coupon') or {}).get('code')
        costs += [('Energia antes do cupom', _money(charges.get('energy_gross'))),
                  (f'Desconto do cupom {code}' if code else 'Desconto do cupom', '− ' + _money(discount))]
    costs.append(('Energia', _money(charges.get('energy_total'))))
    if charges.get('overstay') is not None:
        costs.append(('Permanência', _money(charges['overstay'])))
    costs.append(('Total', _money(charges.get('total'))))
    if charges.get('revenue_basis') == 'paid' and charges.get('paid_total') is not None:
        costs.append(('Valor pago (líquido)', _money(charges['paid_total'])))
    if payment.get('authorized_amount') is not None:
        paid = [('Forma', PAYMENT_METHODS.get(payment.get('method'), payment.get('method') or '—')),
                ('Autorizado', _money(payment.get('authorized_amount')))]
        if payment.get('captured_amount') is not None:
            paid.append(('Capturado', _money(payment['captured_amount'])))
        if payment.get('refunded_amount') is not None:
            paid.append(('Devolvido', _money(payment['refunded_amount'])))
        if payment.get('provider_reference'):
            paid.append(('Referência', str(payment['provider_reference'])))
    else:
        paid = [('Pagamento', 'Sem pagamento registrado: nenhum valor foi cobrado.')]
    return [('Estação e carregador', place), ('Sessão', session), ('Custos', costs), ('Pagamento', paid)]


def _wrap(draw, text, font, width):
    words, lines, line = str(text).split(), [], ''
    for word in words:
        candidate = f'{line} {word}'.strip()
        if draw.textlength(candidate, font=font) <= width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    return [*lines, line] if line else lines or ['']


def receipt_pdf(receipt):
    """Bytes do PDF (uma página A4) do recibo da conta demo."""
    from PIL import Image, ImageDraw

    receipt = clean_receipt(receipt)

    page = Image.new('RGB', (WIDTH, HEIGHT), 'white')
    draw = ImageDraw.Draw(page)
    title, bold, regular, small = _font('Bold', 40), _font('Bold', 24), _font('Regular', 24), _font('Regular', 20)
    y = MARGIN
    draw.text((MARGIN, y), 'ChargeGrid', font=bold, fill=INK)
    y += 48
    draw.text((MARGIN, y), f"Recibo de recarga nº {receipt.get('number') or '—'}", font=title, fill=INK)
    y += 62
    draw.text((MARGIN, y), MARK, font=regular, fill=MUTED)
    y += 52
    column = WIDTH - 2 * MARGIN
    for heading, items in rows(receipt):
        draw.line((MARGIN, y, WIDTH - MARGIN, y), fill=LINE, width=2)
        y += 18
        draw.text((MARGIN, y), heading, font=bold, fill=INK)
        y += 40
        for label, value in items:
            strong = label in ('Total', 'Preço travado', 'Valor pago (líquido)')
            lines = _wrap(draw, value, bold if strong else regular, column * 0.6)
            draw.text((MARGIN, y), label, font=regular, fill=MUTED)
            for index, line in enumerate(lines):
                font = bold if strong else regular
                draw.text((WIDTH - MARGIN - draw.textlength(line, font=font), y + index * 32), line, font=font,
                          fill=INK)
            y += 32 * len(lines) + 8
        y += 16
    notes = [note for note in (receipt.get('labels') or {}).get('notes', []) if note.rstrip('.') != MARK]
    notes.append(f"Sessão {receipt.get('session_id') or '—'}.")
    for note in notes:
        for line in _wrap(draw, note, small, column):
            if y > HEIGHT - MARGIN:
                break
            draw.text((MARGIN, y), line, font=small, fill=MUTED)
            y += 28
    buffer = io.BytesIO()
    page.save(buffer, 'PDF', resolution=150.0, title=f"Recibo {receipt.get('number') or ''}".strip(),
              author='ChargeGrid', subject=MARK)
    return buffer.getvalue()
