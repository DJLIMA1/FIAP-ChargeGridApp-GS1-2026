"""Account-scoped, in-memory conversation with local guidance and read-only data.

No question is sent to a language model or a support service. Only explicit
requests for charging/reservation information read the existing account API.
"""

import asyncio
import unicodedata
from decimal import Decimal, InvalidOperation

import flet as ft

from ..api_client import ApiError
from ..ui import theme
from ..ui.components import date_time, field
from . import help as guidance

MAX_QUESTION_LENGTH = 500
ASSISTANT_BACKGROUND = '#252529'
_SESSION_LABELS = {
    'starting': 'Aguardando confirmação do equipamento', 'charging': 'Em recarga',
    'stopping': 'Parada pendente de confirmação', 'completed': 'Concluída',
    'failed': 'Falha confirmada', 'interrupted': 'Interrompida',
}
_RESERVATION_LABELS = {
    'pending_device': 'Aguardando confirmação do equipamento', 'confirmed': 'Confirmada',
    'cancelling': 'Cancelamento pendente de confirmação', 'cancelled': 'Cancelada',
    'expired': 'Expirada', 'consumed': 'Usada para iniciar uma recarga',
}
_SOURCE_LABELS = {'simulated': 'simulada', 'measured': 'medida pelo equipamento', 'estimated': 'estimada'}


def _normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold())
                   if not unicodedata.combining(c))


def _account(app):
    profile = getattr(app, 'profile', {}) or {}
    user = getattr(getattr(app.api, 'session', None), 'user', None) or {}
    return profile.get('id') or user.get('id'), bool(getattr(app.api, 'is_demo', False))


def _state(app):
    identity = _account(app)
    if getattr(app, '_chat_account_id', None) != identity:
        app.chat_messages = []
        app.chat_draft = ''
        app._chat_account_id = identity
        app._chat_pending = None
    if not hasattr(app, 'chat_messages'):
        app.chat_messages = []
    if not hasattr(app, 'chat_draft'):
        app.chat_draft = ''
    if not app.chat_messages:
        demo = ' Nesta conta, reservas, equipamentos e recargas são demonstrações.' if identity[1] else ''
        app.chat_messages.append({
            'role': 'assistant',
            'content': 'Olá! Posso orientar você nos próximos passos e consultar suas recargas e reservas.' + demo,
            'actions': [],
        })
    return identity, app.chat_messages


def _action(label, route, **data):
    return {'label': label, 'route': route, 'data': data}


def _numeric(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _money(value):
    number = _numeric(value)
    return f'R$ {number:.2f}'.replace('.', ',') if number is not None else 'não informado'


def _point(record):
    connector = record.get('connector') or {}
    lines = []
    if record.get('station_name'):
        lines.append('Posto: ' + str(record['station_name']))
    if connector.get('public_code'):
        lines.append('Ponto: ' + str(connector['public_code']))
    if not lines:
        lines.append('A resposta não trouxe a identificação do ponto.')
    return lines


def _session_text(record, heading, demo=False):
    energy = _numeric(record.get('energy_wh'))
    lines = [heading, *_point(record),
             'Estado: ' + _SESSION_LABELS.get(record.get('status'), 'não informado'),
             'Energia: ' + (f'{energy / 1000:.3f} kWh' if energy is not None else 'não informada'),
             'Custo estimado: ' + _money(record.get('cost_estimate'))]
    if record.get('price_per_kwh') is not None:
        lines.append('Tarifa da sessão: ' + _money(record['price_per_kwh']) + '/kWh')
    duration = _numeric(record.get('max_duration_minutes'))
    if duration is not None:
        lines.append(f'Limite de duração: {duration:g} min')
    if record.get('max_cost') is not None:
        lines.append('Limite de custo estimado: ' + _money(record['max_cost']))
    soc = _numeric(record.get('soc_percent'))
    if soc is not None and soc <= 100:
        lines.append(f'Bateria: {soc:.0f}%')
    source = _SOURCE_LABELS.get(record.get('source'))
    if source:
        lines.append('Origem da energia: ' + source + '.')
    if record.get('last_measurement_at'):
        lines.append('Última medição: ' + date_time(record['last_measurement_at']))
    if record.get('status') in ('starting', 'charging', 'stopping') and record.get('online') is False:
        lines.append('Equipamento offline: estes são os últimos dados recebidos; parada física não confirmada.')
    if demo:
        lines.append('Dados da demonstração desta conta; nenhum equipamento real está envolvido.')
    lines.append('Os valores são estimativas, não comprovantes de pagamento.')
    return '\n'.join(lines)


def _local_answer(question, demo):
    heading, content = guidance.answer(question)
    actions = {
        'Iniciar uma recarga': [_action('Encontrar um ponto', 'stations')],
        'Reservar para chegar depois': [_action('Escolher ponto para reservar', 'stations'), _action('Minha reserva', 'reservations')],
        'Tempo, valor e cupons': [_action('Definir uma recarga', 'charging'), _action('Consultar cupons', 'coupons')],
        'Parar ou resolver uma falha': [_action('Abrir minha recarga', 'charging')],
        'Criar posto e vincular ponto': [_action('Abrir meus postos', 'operator')],
        'Conta, senha e histórico': [_action('Abrir minha conta', 'profile'), _action('Meu histórico', 'history')],
    }
    if demo:
        from ..demo import DEMO_PRESENCE_CODE
        overrides = {
            'Iniciar uma recarga': (
                'Escolha um ponto demonstrativo disponível. Em Confirmar ponto, use ' + DEMO_PRESENCE_CODE +
                ' (digite 12345). Continue para Definir limites, escolha tempo ou valor estimado e confira '
                'Revisar recarga. Somente Solicitar início cria a sessão simulada. A confirmação e a energia '
                'evoluem nesta conta; nenhum ESP32 é acionado.'),
            'Reservar para chegar depois': (
                'Escolha um ponto demonstrativo disponível e toque em Reservar. Aguarde a confirmação '
                'simulada e confira o prazo de 10 minutos em Minha reserva. Para iniciar, abra a reserva '
                'e use #F12345. Cancelar libera o ponto depois da confirmação simulada.'),
            'Parar ou resolver uma falha': (
                'Abra Minha recarga e solicite a parada. Aguarde a confirmação da sessão simulada. '
                'Você pode continuar navegando; sair da conta encerra esta demonstração e apaga seus dados locais. '
                'Nenhum equipamento real está conectado.'),
            'Criar posto e vincular ponto': (
                'No modo operador, abra Postos e escolha Adicionar equipamento simulado. Não é necessário '
                'QR real nem câmera. Posto é o endereço; ponto é o equipamento. Informe a localização e a tarifa, '
                'revise e publique. Você também pode adicionar outro ponto a um posto existente. Tudo fica nesta conta.'),
            'Conta, senha e histórico': (
                'A conta de demonstração permite alternar entre motorista e operador. Dados editados, cupons '
                'e histórico ficam somente nesta sessão. As credenciais públicas permanecem iguais. '
                'Ao sair e entrar novamente, a demonstração recomeça.'),
        }
        content = overrides.get(heading, content)
    if heading not in actions:
        content = ('Posso orientar sobre recarga, reserva, limites, cupons e cadastro de postos. '
                   'Também posso consultar sua recarga atual ou o resumo da última recarga. '
                   'Não realizo pagamentos nem abro chamados de suporte.')
    return {'content': content, 'actions': actions.get(heading, [])}


async def answer(app, question):
    """Answer locally, or read an explicitly requested account resource."""
    normalized = _normalized(question)
    demo = bool(getattr(app.api, 'is_demo', False))
    profile = getattr(app, 'profile', {}) or {}
    last = any(word in normalized for word in ('ultima recarga', 'ultima sessao', 'ultimo carregamento')) or (
        'resumo' in normalized and any(word in normalized for word in ('recarga', 'sessao', 'historico'))
    )
    if last:
        seller_intent = any(word in normalized for word in ('meus postos', 'dos postos', 'clientes', 'operador', 'vendedor'))
        personal_intent = any(word in normalized for word in ('minha ultima', 'pessoal', 'como motorista', 'como consumidor'))
        seller = seller_intent or (getattr(app, 'browsing_mode', 'consumer') == 'vendor' and not personal_intent)
        if seller and not profile.get('operator_enabled'):
            return {'content': 'O histórico dos seus postos fica disponível após vincular seu primeiro equipamento. '
                               'Para suas recargas pessoais, peça “minha última recarga como motorista”.',
                    'actions': [_action('Configurar meu primeiro ponto', 'operator')]}
        path = 'operator/charging-sessions' if seller else 'me/charging-sessions'
        result = await app.api.request('GET', path, params={'limit': 1, 'offset': 0})
        if not isinstance(result, dict) or not isinstance(result.get('items'), list):
            raise ApiError('Resposta inválida ao consultar histórico.')
        items = result.get('items') or []
        scope = 'dos seus postos' if seller else 'das suas recargas como motorista'
        if not items:
            return {'content': f'Ainda não há registros no histórico {scope}.',
                    'actions': [_action('Ver histórico dos postos' if seller else 'Ver meu histórico', 'history', **({'manage': True} if seller else {}))]}
        heading = 'Última recarga dos seus postos' if seller else 'Sua última recarga como motorista'
        if not isinstance(items[0], dict) or not items[0].get('id'):
            raise ApiError('Resposta inválida ao consultar histórico.')
        action = _action('Ver histórico dos postos', 'history', manage=True) if seller else _action('Ver detalhes da recarga', 'charging', session_id=items[0]['id'])
        return {'content': _session_text(items[0], heading, demo), 'actions': [action]}
    instructional = any(word in normalized for word in ('iniciar', 'comecar', 'parar', 'cancelar', 'reservar', 'definir'))
    if any(word in normalized for word in ('minha reserva', 'reserva atual', 'status da reserva')) and not instructional:
        reservation = await app.api.request('GET', 'reservations/current')
        if reservation is not None and not isinstance(reservation, dict):
            raise ApiError('Resposta inválida ao consultar reserva.')
        if not reservation:
            return {'content': 'Você não tem uma reserva ativa nesta conta.',
                    'actions': [_action('Escolher ponto para reservar', 'stations')]}
        lines = ['Sua reserva atual', *_point(reservation),
                 'Estado: ' + _RESERVATION_LABELS.get(reservation.get('status'), 'não informado')]
        if reservation.get('expires_at'):
            lines.append('Prazo para chegar: ' + date_time(reservation['expires_at']))
        elif reservation.get('status') == 'pending_device':
            lines.append('O prazo de chegada começa depois da confirmação do equipamento.')
        lines.append('Reserva simulada nesta conta.' if demo else 'No local, use o código #F do visor para iniciar.')
        return {'content': '\n'.join(lines), 'actions': [_action('Abrir minha reserva', 'reservations')]}
    if any(word in normalized for word in ('minha recarga', 'recarga atual', 'em andamento', 'esta carregando', 'quanto carregou', 'bateria')) and not instructional:
        session = await app.api.request('GET', 'charging-sessions/current')
        if session is not None and (not isinstance(session, dict) or not session.get('id')):
            raise ApiError('Resposta inválida ao consultar recarga.')
        if not session:
            return {'content': 'Você não tem uma recarga ativa nesta conta. Posso consultar sua última recarga no histórico.',
                    'actions': [_action('Encontrar um ponto', 'stations'), _action('Ver meu histórico', 'history')]}
        return {'content': _session_text(session, 'Sua recarga atual', demo),
                'actions': [_action('Abrir minha recarga', 'charging', session_id=session['id'])]}
    return _local_answer(question, demo)


async def build(app, question='', topic=None):
    identity, messages = _state(app)
    # Flet follows content on the client after layout. An off-screen bubble's
    # size event cannot reliably tell Python when the list is ready to scroll.
    chat_list = ft.ListView(expand=True, auto_scroll=True, auto_scroll_animation=0,
                            build_controls_on_demand=False,
                            spacing=12, padding=ft.Padding(top=8, bottom=12))
    composer = field('Mensagem', app.chat_draft)
    composer.label = None
    composer.hint_text = 'Digite sua mensagem'
    composer.fill_color = theme.WHITE
    composer.color = composer.cursor_color = theme.TEXT_COLOR
    composer.hint_style = ft.TextStyle(color=theme.GRAY_TEXT)
    composer.border = ft.OutlineInputBorder(side=ft.BorderSide(1, theme.GRAY_TEXT), border_radius=4)
    composer.counter = ''
    composer.max_length = MAX_QUESTION_LENGTH
    composer.expand = True
    composer.min_lines = 1
    composer.max_lines = 3
    composer.data = 'chat-draft'
    progress = ft.Text('Consultando os dados da sua conta…', color=theme.GRAY_TEXT, size=12, visible=False)
    send_button = ft.IconButton(icon=ft.Icons.SEND_ROUNDED, icon_color='#FFFFFF', bgcolor=theme.RED,
                               tooltip='Enviar mensagem', width=46, height=46,
                               style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=4)))

    def current():
        return _account(app) == identity and getattr(app, '_chat_account_id', None) == identity and app.chat_messages is messages

    def draw():
        if not current():
            return
        # Messages are immutable once added. Append new rows while preserving
        # the existing control IDs, accessible text and navigation actions.
        for index in range(len(chat_list.controls), len(messages)):
            message = messages[index]
            user = message['role'] == 'user'
            content = [ft.Text(message['content'], color='#FFFFFF', size=14,
                               semantics_label=('Você: ' if user else 'Assistente: ') + message['content'])]
            if message.get('actions'):
                content.append(ft.Row([
                    ft.Container(ft.Text(action['label'], color='#FFFFFF', size=12, weight=ft.FontWeight.BOLD),
                                 on_click=app.link(action['route'], **action.get('data', {})), ink=True,
                                 padding=ft.Padding.symmetric(horizontal=10, vertical=8), border_radius=8,
                                 border=ft.Border.all(1, '#77777C'))
                    for action in message['actions']
                ], wrap=True, spacing=8, run_spacing=8))
            bubble = ft.Container(ft.Column(content, spacing=10, tight=True),
                                  bgcolor=theme.RED if user else ASSISTANT_BACKGROUND, padding=14,
                                  border_radius=4, expand=7)
            spacer = ft.Container(expand=1)
            chat_list.controls.append(ft.Row([spacer, bubble] if user else [bubble, spacer], spacing=0,
                                             vertical_alignment=ft.CrossAxisAlignment.START))

    def changed(event=None):
        if current():
            app.chat_draft = composer.value or ''
            composer.error_text = None

    async def send(value=None):
        if not current() or getattr(app, '_chat_pending', None) is not None:
            return
        raw = composer.value if value is None else value
        text = (raw or '').strip()
        if not text:
            composer.error_text = 'Escreva uma pergunta antes de enviar.'
            app.page.update()
            return
        if len(text) > MAX_QUESTION_LENGTH:
            composer.error_text = f'Use até {MAX_QUESTION_LENGTH} caracteres por mensagem.'
            app.page.update()
            return
        original_draft = composer.value or ''
        app.chat_draft = original_draft
        composer.error_text = None
        pending = object()
        app._chat_pending = pending
        messages.append({'role': 'user', 'content': text, 'actions': []})
        send_button.disabled = True
        progress.visible = True
        draw()
        app.page.update()
        try:
            result = await answer(app, text)
        except ApiError:
            if current():
                messages.append({'role': 'assistant', 'content':
                    'Não consegui consultar os dados da sua conta agora. Nenhum resultado foi confirmado. '
                    'Confira sua conexão e tente novamente. As orientações sobre recarga, reserva e limites '
                    'continuam disponíveis aqui.', 'actions': []})
                if value is not None and not original_draft:
                    composer.value = app.chat_draft = text
        except asyncio.CancelledError:
            if current():
                messages.append({'role': 'assistant', 'content':
                    'A consulta foi interrompida antes de receber uma resposta. Você pode tentar novamente.', 'actions': []})
            raise
        else:
            if current():
                messages.append({'role': 'assistant', **result})
                # Do not discard a draft changed while a slow query was running,
                # or an existing draft when a suggested question is chosen.
                if value is None and (composer.value or '') == original_draft:
                    composer.value = app.chat_draft = ''
        finally:
            if getattr(app, '_chat_pending', None) is pending:
                app._chat_pending = None
            if current():
                send_button.disabled = False
                progress.visible = False
                draw()
                app.page.update()
        return True

    composer.on_change = changed
    submit = app.action(send)
    composer.on_submit = send_button.on_click = submit
    vendor = getattr(app, 'browsing_mode', 'consumer') == 'vendor' or topic == 'vendor'
    suggestions = (['Última recarga dos meus postos', 'Criar posto e vincular ponto', 'Tempo, valor e cupons'] if vendor else
                   ['Resumo da última recarga', 'Iniciar uma recarga', 'Reservar', 'Ajuda com limites'])
    if topic == 'reservations':
        suggestions = ['Minha reserva', 'Reservar', *suggestions[:2]]
    elif topic == 'charging':
        suggestions = ['Minha recarga', 'Iniciar uma recarga', 'Ajuda com limites', 'Parar ou resolver uma falha']
    chips = ft.Row([
        ft.Container(ft.Text(label, size=12, color=theme.TEXT_COLOR), padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                     border=ft.Border.all(1, theme.LIGHT_GRAY), border_radius=4, ink=True,
                     on_click=app.action(lambda label=label: send(label)))
        for label in suggestions
    ], wrap=True, spacing=6, run_spacing=6)
    contextual = []
    if question:
        suggested = str(question).strip()
        contextual.append(ft.Container(
            ft.Text('Perguntar: ' + suggested, size=13, color=theme.TEXT_COLOR),
            on_click=app.action(lambda: send(suggested)), ink=True, padding=12,
            border=ft.Border.all(1, theme.RED), border_radius=4,
        ))
    # Navigation offers context without speaking for the user or querying an
    # unmounted conversation. All sends use the already-mounted interaction.
    draw()
    return ft.Column([
        ft.Row([ft.Container(ft.Icon(ft.Icons.CHAT_BUBBLE_OUTLINE, color='#FFFFFF', size=21),
                             bgcolor=theme.RED, padding=10, border_radius=4),
                ft.Column([ft.Text('Chat', size=26, color=theme.TEXT_COLOR, weight=ft.FontWeight.BOLD,
                                   font_family='BarlowCondensed'),
                           ft.Text('Assistente do ChargeGrid · orientações automáticas', size=11, color=theme.GRAY_TEXT)],
                          spacing=2, expand=True)], spacing=12),
        chat_list, *contextual, chips, progress,
        ft.Row([composer, send_button], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Text('Conversa disponível só nesta sessão.', size=10, color=theme.GRAY_TEXT),
    ], expand=True, spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
