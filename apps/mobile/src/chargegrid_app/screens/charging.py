from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation

import flet as ft

from ..api_client import ApiError
from ..services.planning import estimate_text, intent_limits
from ..ui import theme
from ..ui.components import (
    button,
    card,
    date_time,
    disclosure_field,
    field,
    money,
    title,
)
from ..ui.point_summary import journey_summary, point_summary
from ..ui.point_summary import point_context as context_from_station

LABELS = {'starting':'Aguardando equipamento iniciar','charging':'Recarga confirmada','stopping':'Parada pendente no equipamento','completed':'Recarga concluída','failed':'Falha confirmada','interrupted':'Recarga interrompida'}
DEMO_LABELS = {'starting':'Aguardando início simulado','charging':'Recarga simulada em andamento','stopping':'Finalizando recarga simulada','completed':'Recarga simulada concluída','failed':'Falha simulada','interrupted':'Recarga simulada interrompida'}
SOURCE = {'simulated':'Simulada pelo equipamento','measured':'Medida','estimated':'Estimada'}
ACTIVE = {'starting','charging','stopping'}
END_REASONS = {'user_stop':'Parada solicitada', 'stop_requested':'Parada solicitada', 'duration_limit':'Limite de duração atingido', 'max_duration':'Limite de duração atingido', 'cost_limit':'Limite de custo atingido', 'max_cost':'Limite de custo atingido', 'disconnected':'Cabo desconectado', 'device_fault':'Falha no equipamento', 'reboot':'Equipamento reiniciado'}
END_REASONS.update(requested='Parada solicitada', communication_lost='Conexão perdida com o servidor',
                   device_reboot='Equipamento reiniciado', command_timeout='Equipamento não confirmou a operação')


def _progress(session):
    """Use received SoC or received timestamps; never advance a physical timer locally."""
    try:
        soc = float(session['soc_percent'])
        if 0 <= soc <= 100:
            return soc/100, f'Bateria: {soc:.0f}%'
    except (KeyError,TypeError,ValueError):
        pass
    try:
        start = datetime.fromisoformat(session['started_at'].replace('Z','+00:00'))
        recorded = session.get('ended_at') or session['last_measurement_at']
        end = datetime.fromisoformat(recorded.replace('Z','+00:00'))
        minutes = (end-start).total_seconds()/60
        limit = int(session['max_duration_minutes'])
        if limit > 0 and minutes >= 0:
            return min(1,minutes/limit), f'Tempo estimado: {minutes:.0f} de {limit} min'
    except (KeyError,AttributeError,TypeError,ValueError):
        pass
    return None, 'Bateria: não disponível'


def session_card(session, *, demo=False):
    progress, progress_label = _progress(session)
    if demo and progress_label.startswith('Bateria:'):
        progress_label = progress_label.replace('Bateria:','Bateria simulada:',1)
    labels = DEMO_LABELS if demo else LABELS
    controls = [ft.Text(labels.get(session['status'],session['status']),size=20,weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR),
                ft.Text(progress_label,size=28 if progress is not None else 13,
                        weight=ft.FontWeight.BOLD if progress is not None else ft.FontWeight.NORMAL,
                        color=theme.TEXT_COLOR if progress is not None else theme.GRAY_TEXT)]
    if progress is not None:
        controls.append(ft.ProgressBar(value=progress,color=theme.RED,bgcolor=theme.LIGHT_GRAY,bar_height=8))
    if progress_label.startswith('Tempo estimado:'):
        controls.append(ft.Text('Baseado nos horários recebidos, não no nível da bateria.',size=12,color=theme.GRAY_TEXT))
    controls += [ft.Text('Dados simulados nesta conta' if demo else SOURCE.get(session.get('source'),'Origem não informada'),size=12,color=theme.GRAY_TEXT),
                 ft.Divider(color=theme.LIGHT_GRAY),
                 ft.Text(f"Energia: {float(session.get('energy_wh') or 0)/1000:.3f} kWh".replace('.', ','),size=17,color=theme.TEXT_COLOR),
                 ft.Text('Custo estimado: '+money(session.get('cost_estimate')),size=17,color=theme.TEXT_COLOR),
                 ft.Text('Última medida: '+date_time(session.get('last_measurement_at')),size=12,color=theme.GRAY_TEXT)]
    if session['status'] in ACTIVE and not session.get('online'):
        controls.append(ft.Text('Equipamento simulado offline. Nenhum equipamento real é acionado.' if demo else
                                'Equipamento offline. Últimos dados mantidos; parada física não confirmada.',color=theme.ERROR))
    if session.get('end_reason'):
        controls.append(ft.Text('Encerramento: '+END_REASONS.get(session['end_reason'],session['end_reason']),size=12,color=theme.GRAY_TEXT))
    details = [ft.Text('Limite de duração: '+str(session['max_duration_minutes'])+' min',color=theme.GRAY_TEXT)]
    if session.get('max_cost') is not None:
        details.append(ft.Text('Limite de custo estimado: '+money(session['max_cost']),color=theme.GRAY_TEXT))
    if session.get('discount_percent'):
        details.append(ft.Text(f"Desconto aplicado: {session['discount_percent']}%",color=theme.GRAY_TEXT))
    controls.append(ft.ExpansionTile(title=ft.Text('Detalhes da recarga',color=theme.TEXT_COLOR,size=13),controls=details))
    return card(controls)


def _owner(app):
    user = getattr(getattr(app.api,'session',None),'user',None) or {}
    return str((getattr(app,'profile',{}) or {}).get('id') or user.get('id') or id(app.api))


def _metadata(app, data):
    app.data = data
    sync_back = getattr(app,'sync_back',None)
    if sync_back:
        sync_back()


def _route(draft, step):
    return {'public_code':draft['public_code'],'reservation_id':draft['reservation_id'],
            'point_context':draft['point_context'],'max_duration':draft['initial_duration'],'step':step,
            'pending_start':bool(draft['uncertain']),
            **({'station_search':deepcopy(draft['station_search'])} if draft.get('station_search') else {})}


def _code(draft):
    digits = (draft['presence_digits'] or '').strip()
    if len(digits) != 5 or not digits.isascii() or not digits.isdigit():
        raise ApiError('Digite os cinco números que aparecem após #F na tela do posto.')
    return '#F'+digits


def _point_limit(draft):
    return int((draft['point_context'].get('connector') or {}).get('max_duration_minutes') or 1440)


def _limits(draft):
    value_mode = draft['mode'] == 'value'
    try:
        minutes = int(draft['safety_minutes'] if value_mode else draft['duration_minutes'])
    except (TypeError,ValueError) as exc:
        raise ApiError('Informe a duração em minutos inteiros.') from exc
    if not 1 <= minutes <= _point_limit(draft):
        raise ApiError(f'Escolha uma duração de 1 a {_point_limit(draft)} minutos, dentro do limite do ponto.')
    body = {'max_duration_minutes':minutes}
    if value_mode:
        raw = (draft['max_cost'] or '').strip().replace(',','.')
        if not raw:
            raise ApiError('Informe o valor estimado para limitar a recarga ou selecione Por tempo.')
        price = (draft['point_context'].get('connector') or {}).get('price_per_kwh')
        if price is not None and Decimal(str(price)) == 0:
            raise ApiError('Este ponto tem tarifa gratuita. Selecione Por tempo para definir o limite da recarga.')
        try:
            amount = Decimal(raw)
            if not amount.is_finite() or not 0 < amount <= 100000:
                raise InvalidOperation
        except (InvalidOperation,ValueError) as exc:
            raise ApiError('Informe um limite de custo maior que zero e de até R$ 100.000.') from exc
        body['max_cost'] = format(amount,'f')
    return body


def _body(draft):
    body = {'presence_code':_code(draft),**_limits(draft)}
    for key in ('public_code','reservation_id'):
        if draft[key]:
            body[key] = draft[key]
    if (draft['coupon_code'] or '').strip():
        body['coupon_code'] = draft['coupon_code'].strip()
    return body


def _estimate(draft):
    connector = draft['point_context'].get('connector') or {}
    try:
        limits = _limits(draft)
        return estimate_text(connector, limits['max_duration_minutes'], limits.get('max_cost'))
    except (ApiError,TypeError,ValueError):
        return 'A estimativa depende da tarifa, potência e limites do ponto. Nenhuma cobrança real.'


def _header(step):
    return ft.Column([
        ft.Text(f'INICIAR RECARGA · ETAPA {step} DE 3',size=11,weight=ft.FontWeight.BOLD,color=theme.ACCENT),
        ft.Row([ft.Container(height=5,expand=True,bgcolor=theme.RED if index<=step else theme.LIGHT_GRAY,border_radius=3)
                for index in range(1,4)],spacing=5),
        title(('Confirmar ponto','Definir limites','Revisar recarga')[step-1]),
    ],spacing=10)


def _review(draft):
    context = draft['point_context']
    point = context.get('connector') or {}
    body = draft.get('pending_body') if draft.get('uncertain') else _body(draft)
    rows = [('Ponto',context.get('station_name') or 'Identificado pelo código #F'),
            ('Endereço',context.get('station_address')),
            ('Conector',' · '.join(str(point[key]) for key in ('public_code','connector_type') if point.get(key))),
            ('Código de presença',body['presence_code']),
            ('Limite de tempo',f"{body['max_duration_minutes']} min"),
            ('Limite de valor',money(body['max_cost']) if body.get('max_cost') else None),
            ('Tarifa',f"{money(point['price_per_kwh'])}/kWh" if point.get('price_per_kwh') is not None else None),
            ('Cupom',body.get('coupon_code'))]
    controls = [ft.Text('RESUMO DA RECARGA',size=11,weight=ft.FontWeight.BOLD,color=theme.RED)]
    for label,value in rows:
        if value:
            controls.append(ft.Row([ft.Text(label,size=12,color='#62666B',width=104),
                                    ft.Text(str(value),size=14,color=theme.INPUT_TEXT,weight=ft.FontWeight.BOLD,expand=True)],
                                   vertical_alignment=ft.CrossAxisAlignment.START,spacing=12))
    return ft.Container(ft.Column(controls,spacing=12,horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                        bgcolor=theme.INPUT_BG,border_radius=4,padding=18)


async def build(app, public_code='', reservation_id=None, session_id=None, max_duration=30, point_context=None, step=None, pending_start=False, planning_intent=None, station_search=None):
    demo = getattr(app.api,'is_demo',False) is True
    draft = getattr(app,'charging_draft',None)
    if draft and draft.get('owner') != _owner(app):
        app.charging_draft = draft = None
    explicit_target = bool(public_code or reservation_id)
    if draft:
        same_target = ((not public_code or public_code == draft['public_code']) and
                       (not reservation_id or reservation_id == draft['reservation_id']))
        if draft.get('uncertain') or not explicit_target or same_target:
            public_code,reservation_id,point_context = draft['public_code'],draft['reservation_id'],draft['point_context']
            max_duration = draft['initial_duration']
            if draft.get('uncertain'):
                # Viewing an older session must not discard an unresolved start.
                session_id = None
        else:
            draft = None

    session = await app.api.request('GET',f'charging-sessions/{session_id}' if session_id else 'charging-sessions/current')
    if session:
        # Inspecting an old result is not abandoning a separate start draft.
        # Active/current sessions and show_result() resolve that preparation.
        if not session_id or session['status'] in ACTIVE:
            app.charging_draft = None
        _metadata(app,{'session_id':session['id']})
        key = app.api.new_key()
        async def stop():
            await app.api.request('POST',f"charging-sessions/{session['id']}/stop",key=key)
            await app.go('charging',session_id=session['id'])
        state = ft.Container(session_card(session,demo=demo))
        journey = ft.Container(journey_summary(session, demo=demo))
        controls = [title('Minha recarga'),state,journey,point_summary(session)]
        async def update():
            current = await app.api.request('GET',f"charging-sessions/{session['id']}")
            if current['status'] != session['status']:
                await app.go('charging',session_id=session['id'])
                return
            state.content = session_card(current,demo=demo)
            journey.content = journey_summary(current, demo=demo)
            app.page.update()
        if session['status'] in ACTIVE:
            app.set_poll(update,5)
        else:
            if getattr(app,'charging_draft',None):
                controls.append(button('Retomar preparação da recarga',app.link('charging')))
            async def again():
                app.api.clear_operation('charging-sessions')
                app.charging_draft = None
                await app.go('charging')
            controls.append(button('Iniciar outra recarga',app.action(again)))
        if session['status'] in ('starting','charging'):
            controls.insert(2,button('Solicitar parada',app.action(stop)))
        controls.append(ft.Text(
            'Atualiza a cada 5 s. A evolução é simulada nesta conta; nenhum equipamento real recebe comandos.'
            if demo and session['status'] in ACTIVE else
            'Atualiza a cada 5 s. Fechar o app ou sair da conta mantém a sessão física e seus limites.'
            if session['status'] in ACTIVE else 'Sessão encerrada. Os dados também estão disponíveis no histórico.',
            size=12,color=theme.GRAY_TEXT))
        return ft.Column(controls,spacing=15,scroll=ft.ScrollMode.AUTO,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    reservation = await app.api.request('GET','reservations/current')
    if reservation and reservation.get('status') in ('cancelled','expired','consumed'):
        reservation = None
    # A lost response may already have consumed a reservation. Recover the exact
    # original POST before allowing edits or requiring that reservation again.
    uncertain = bool(draft and draft.get('uncertain'))
    _metadata(app,{'public_code':public_code,'reservation_id':reservation_id,'point_context':point_context,'step':1})
    if not uncertain:
        if reservation_id and (not reservation or reservation['id'] != reservation_id):
            # A finished reservation must not permanently trap a resumable draft.
            # Keep its selected point and limits, but require a fresh presence
            # confirmation. An uncertain POST never enters this branch.
            context = point_context or {}
            public_code = public_code or (context.get('connector') or {}).get('public_code') or ''
            if draft:
                draft.update(reservation_id=None,public_code=public_code,step=1,furthest=1,
                             presence_digits='12345' if demo else '')
                app.charging_draft = draft
                route = _route(draft,1)
            else:
                route = {'public_code':public_code,'point_context':context,'max_duration':max_duration,'step':1}
            _metadata(app,route)
            controls = [title('Reserva não está mais ativa','Confira sua reserva ou confirme novamente o código #F no ponto selecionado.'),
                        button('Ver minha reserva',app.link('reservations'))]
            if not reservation:
                controls.append(button('Continuar sem reserva',app.link('charging',**route),secondary=True))
            return ft.Column(controls,spacing=15,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        if reservation:
            reserved_point = reservation.get('connector') or {}
            different_point = public_code and reserved_point.get('public_code') != public_code
            if reservation['status'] != 'confirmed' or different_point:
                explanation = ('Você já tem uma reserva em outro ponto. Use ou cancele essa reserva antes de escolher outro.'
                               if different_point else 'Aguarde a liberação do ponto antes de solicitar outra recarga.'
                               if reservation['status'] == 'cancelling' else 'Aguarde a confirmação da reserva no equipamento antes de iniciar.')
                return ft.Column([title('Confira sua reserva',explanation),point_summary(reservation,'Ponto reservado'),
                                               button('Ver minha reserva',app.link('reservations'))],spacing=15)
            reservation_id,point_context = reservation['id'],reservation
        elif not explicit_target and not session_id and app.api.last_session_id and not draft:
            return await build(app,session_id=app.api.last_session_id)

    context = point_context or {}
    connector = context.get('connector') or {}
    if public_code and connector.get('public_code') and connector['public_code'] != public_code:
        raise ApiError('O ponto selecionado mudou. Volte à lista e selecione o ponto novamente.')
    point_limit = int(connector.get('max_duration_minutes') or 1440)
    initial_duration = min(max(1,int(max_duration)),point_limit)
    if draft is None:
        presence_digits = ''
        if demo:
            from ..demo import DEMO_PRESENCE_CODE
            presence_digits = DEMO_PRESENCE_CODE[2:]
        draft = {'owner':_owner(app),'public_code':public_code,'reservation_id':reservation_id,
                 'point_context':deepcopy(context),'initial_duration':initial_duration,
                 'presence_digits':presence_digits,'duration_minutes':str(initial_duration),
                 'safety_minutes':str(point_limit if connector.get('max_duration_minutes') else initial_duration),
                 'mode':'time','max_cost':'','coupon_code':'','step':1,'furthest':1,
                 'key':app.api.new_key(),'last_body':None,'pending_body':None,'uncertain':False}
        saved_intent = getattr(app, 'planning_intent', None) or {}
        draft['station_search'] = deepcopy(station_search or (
            saved_intent.get('station_search') if connector.get('id') == saved_intent.get('connector_id') else {}) or {})
        intention = planning_intent
        if not intention and connector.get('id') == saved_intent.get('connector_id'):
            intention = saved_intent.get('intent')
        if intention:
            limits = intent_limits(connector, intention)
            draft['duration_minutes'] = draft['safety_minutes'] = str(limits['minutes'])
            if limits.get('max_cost'):
                draft.update(mode='value', max_cost=limits['max_cost'])
        if connector.get('id') == saved_intent.get('connector_id'):
            app.planning_intent = None
    elif not uncertain:
        draft.update(public_code=public_code,reservation_id=reservation_id,point_context=deepcopy(context))
    app.charging_draft = draft
    try:
        step = min(max(1,int(step if step is not None else draft['step'])),draft['furthest'],3)
    except (TypeError,ValueError):
        step = 1
    if uncertain:
        step = 3
    else:
        try:
            if step >= 2:
                _code(draft)
        except ApiError:
            step = draft['furthest'] = 1
        try:
            if step == 3:
                _limits(draft)
        except ApiError:
            step = draft['furthest'] = 2
    draft['step'] = step
    _metadata(app,_route(draft,step))

    def saved():
        mark_saved = getattr(app,'mark_saved',None)
        if mark_saved:
            mark_saved()

    async def navigate(next_step):
        draft['step'] = next_step
        saved()
        await app.go('charging',**_route(draft,next_step))

    controls = [_header(step)]
    if step == 1:
        presence = field('Código temporário do posto',draft['presence_digits'])
        presence.prefix,presence.max_length = '#F',5
        presence.counter = ''
        presence.width = None
        presence.keyboard_type = ft.KeyboardType.NUMBER
        presence.input_filter = ft.InputFilter(regex_string=r'[0-9]')
        async def capture_code(event=None):
            draft['presence_digits'] = presence.value or ''
            draft['furthest'] = 1
            presence.error_text = None
            saved()
        presence.on_change = capture_code
        async def continue_code():
            await capture_code()
            try:
                _code(draft)
            except ApiError as exc:
                presence.error_text = str(exc)
                app.page.update()
                raise
            draft['furthest'] = 2
            await navigate(2)
        controls += [point_summary(context,'Ponto reservado' if reservation_id else 'Ponto selecionado'),
                     ft.Text('Use #F12345 na conta demo; não é necessário um ESP32.' if demo else
                             'No local, leia os cinco números atuais após #F na tela do equipamento. O código muda periodicamente e é conferido pela API ao solicitar o início.',
                             size=13,color=theme.GRAY_TEXT),presence,button('Continuar',app.action(continue_code))]
        if not context:
            controls.append(button('Prefiro escolher o ponto na lista',app.link('stations'),secondary=True))
    elif step == 2:
        duration = field('Duração máxima (min)',draft['duration_minutes'])
        cost = field('Limite de custo estimado (R$)',draft['max_cost'])
        safety = field('Tempo máximo de segurança (min)',draft['safety_minutes'])
        coupon = field('Cupom (opcional)',draft['coupon_code'])
        for control in (duration,cost,safety,coupon):
            control.width = None
        duration.keyboard_type = cost.keyboard_type = safety.keyboard_type = ft.KeyboardType.NUMBER
        time_panel = ft.Column([duration],visible=draft['mode']=='time',horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        safety_section,safety_summary = disclosure_field('Ajustar tempo máximo','',[
            safety,ft.Text('A recarga para ao atingir o valor ou o tempo máximo, o que acontecer primeiro.',size=12,color=theme.GRAY_TEXT)],
            expanded=draft.get('safety_expanded',False),on_toggle=lambda value:draft.update(safety_expanded=value),on_update=app.page.update)
        coupon_section,coupon_summary = disclosure_field('Cupom de desconto','Opcional',[
            coupon,ft.Text('O código será validado ao solicitar o início. Informar um cupom não confirma o desconto.',size=12,color=theme.GRAY_TEXT)],
            expanded=draft.get('coupon_expanded',bool(draft['coupon_code'])),on_toggle=lambda value:draft.update(coupon_expanded=value),on_update=app.page.update)
        value_panel = ft.Column([cost,safety_section],
                               spacing=12,visible=draft['mode']=='value',horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        estimate = ft.Text(size=13,color=theme.GRAY_TEXT)
        time_button = button('Por tempo',None,secondary=draft['mode']!='time')
        value_button = button('Por valor',None,secondary=draft['mode']!='value')
        time_button.expand = value_button.expand = True

        def capture_limits():
            draft.update(duration_minutes=duration.value or '',max_cost=cost.value or '',
                         safety_minutes=safety.value or '',coupon_code=coupon.value or '',furthest=2)
            saved()

        def refresh_mode():
            value_mode = draft['mode']=='value'
            time_panel.visible,value_panel.visible = not value_mode,value_mode
            for control,selected in ((time_button,not value_mode),(value_button,value_mode)):
                control.style.bgcolor = theme.RED if selected else theme.LIGHT_GRAY
                control.content.color = '#FFFFFF' if selected else theme.TEXT_COLOR
            safety_summary.value = f"Limite de segurança: {draft['safety_minutes']} min"
            coupon_summary.value = 'Código informado · validação no início' if draft['coupon_code'].strip() else 'Opcional · adicionar código'
            estimate.value = _estimate(draft)

        async def changed(event=None):
            capture_limits()
            for control in (duration,cost,safety,coupon):
                control.error_text = None
            refresh_mode()
            app.page.update()

        async def select_mode(value):
            capture_limits()
            draft['mode'] = value
            refresh_mode()
            app.page.update()

        time_button.on_click = app.action(lambda:select_mode('time'))
        value_button.on_click = app.action(lambda:select_mode('value'))
        duration.on_change = cost.on_change = safety.on_change = coupon.on_change = changed
        refresh_mode()
        async def continue_limits():
            capture_limits()
            try:
                _limits(draft)
            except ApiError as exc:
                target = duration if draft['mode']=='time' else safety if 'duração' in str(exc) else cost
                target.error_text = str(exc)
                app.page.update()
                raise
            draft['furthest'] = 3
            await navigate(3)
        async def back():
            capture_limits()
            await navigate(1)
        controls += [ft.Container(ft.Row([time_button,value_button],spacing=3),padding=3,bgcolor=theme.LIGHT_GRAY,border_radius=4),
                     time_panel,value_panel,estimate,
                     coupon_section,
                     button('Continuar',app.action(continue_limits)),button('Voltar',app.action(back),secondary=True)]
    else:
        pending_message = ft.Text('A resposta do pedido anterior não chegou. Confira o estado ou repita o mesmo pedido; os limites ficam protegidos até confirmar o resultado.',
                                  size=13,color=theme.ERROR,visible=uncertain)
        edit_code = button('Editar código',app.action(lambda:navigate(1)),secondary=True)
        edit_limits = button('Voltar aos limites',app.action(lambda:navigate(2)),secondary=True)
        submit = button('Solicitar início',None)

        async def show_result(result):
            if not isinstance(result,dict) or not result.get('id'):
                raise ApiError('Não foi possível confirmar o resultado. Verifique o estado antes de repetir.')
            app.charging_draft = None
            await app.go('charging',session_id=result['id'])

        async def recover():
            current = await app.api.request('GET','charging-sessions/current')
            if current:
                await show_result(current)
                return True
            known_id = app.api.last_session_id
            if draft.get('uncertain') and known_id and known_id != draft.get('before_session_id'):
                result = await app.api.request('GET',f'charging-sessions/{known_id}')
                if result:
                    await show_result(result)
                    return True
            return False

        async def check_only():
            if not await recover():
                app.notice('Ainda não há confirmação. Repetir usará o mesmo pedido, sem criar outro com limites diferentes.')

        verify = button('Verificar estado',app.action(check_only),secondary=True)

        def sync_pending():
            locked = draft['uncertain']
            pending_message.visible = verify.visible = locked
            edit_code.disabled = edit_limits.disabled = locked
            submit.content.value = 'Repetir mesmo pedido' if locked else 'Solicitar início'
            _metadata(app,_route(draft,3))

        async def start():
            if await recover():
                return
            was_uncertain = draft['uncertain']
            if was_uncertain:
                body = deepcopy(draft['pending_body'])
            else:
                current_reservation = await app.api.request('GET','reservations/current')
                if current_reservation and current_reservation.get('status') in ('cancelled','expired','consumed'):
                    current_reservation = None
                if draft['reservation_id']:
                    if (not current_reservation or current_reservation['id'] != draft['reservation_id'] or
                            current_reservation['status'] != 'confirmed'):
                        raise ApiError('Sua reserva não está confirmada ou expirou. Confira Minha reserva antes de iniciar.')
                elif current_reservation:
                    raise ApiError('Há uma reserva ativa. Abra Minha reserva antes de solicitar o início.')
                station_id = draft['point_context'].get('station_id')
                if station_id:
                    station = await app.api.request('GET', f'stations/{station_id}')
                    old_point = draft['point_context'].get('connector') or {}
                    current_point = next((point for point in station.get('connectors', [])
                                          if (old_point.get('id') and point.get('id') == old_point['id']) or
                                          (not old_point.get('id') and point.get('public_code') == draft['public_code'])), None)
                    if current_point is None:
                        raise ApiError('O ponto selecionado não está mais disponível. Volte à lista para escolher outro.')
                    terms = ('price_per_kwh', 'power_kw', 'max_duration_minutes')
                    changed_terms = any(Decimal(str(old_point.get(key))) != Decimal(str(current_point.get(key)))
                                        for key in terms if old_point.get(key) is not None and current_point.get(key) is not None)
                    draft['point_context'] = context_from_station(station, current_point)
                    if changed_terms:
                        draft['furthest'] = 2
                        await navigate(2)
                        app.notice('As condições do ponto mudaram. Confira a nova tarifa, potência e limite antes de revisar novamente.')
                        return
                    if station.get('active') is False or current_point.get('active') is False or current_point.get('retired'):
                        raise ApiError('Este ponto foi desativado. Volte à lista para escolher outro.')
                body = _body(draft)
                if draft['last_body'] is not None and body != draft['last_body']:
                    draft['key'] = app.api.new_key()
                draft['before_session_id'] = app.api.last_session_id
                draft['pending_body'] = deepcopy(body)
                draft['last_body'] = deepcopy(body)
            # Set before awaiting: cancellation or a transport error must retain
            # the exact request, even when the screen or connection disappears.
            draft['uncertain'] = True
            sync_pending()
            app.page.update()
            try:
                result = await app.api.request('POST','charging-sessions',body,key=draft['key'])
            except ApiError as exc:
                # These validation responses prove this serialized start was
                # rejected. Auth/rate-limit errors on a retry do not prove that.
                definite = exc.status in (400,404,409,422) or (not was_uncertain and 400 <= exc.status < 500)
                if definite:
                    draft['uncertain'] = False
                    draft['pending_body'] = None
                sync_pending()
                app.page.update()
                if definite and exc.code == 'invalid_presence_code':
                    draft['furthest'] = 1
                    await navigate(1)
                    app.notice(str(exc))
                    return
                raise
            await show_result(result)

        submit.on_click = app.action(start)
        sync_pending()
        controls += [_review(draft),ft.Text(_estimate(draft),size=13,color=theme.GRAY_TEXT),pending_message,
                     ft.Text('O simulador confirmará o início. Nenhum equipamento ou pagamento real.' if demo else
                             'O equipamento ainda não foi acionado. O início depende da confirmação dele. Nenhuma cobrança real.',size=12,color=theme.GRAY_TEXT),
                     submit,verify,edit_limits,edit_code]
    return ft.Column(controls,spacing=15,scroll=ft.ScrollMode.AUTO,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
