from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation

import flet as ft

from ..api_client import ApiError
from ..services import booking as rules
from ..services import prepaid, vehicle_state
from ..services.planning import estimate_text, intent_limits
from ..ui import design as d
from ..ui import theme
from ..ui.components import (
    card,
    date_time,
    disclosure_field,
    field,
    money,
)
from ..ui.point_summary import event_disclosure, journey_summary, point_summary
from ..ui.point_summary import point_context as context_from_station
from .reservations import btn, recharge_detail, when_text


def title(text, subtitle=''):
    controls = [d.txt(text, 18, 'bold')]
    if subtitle:
        controls.append(d.txt(subtitle, 12, 'regular', theme.GRAY_TEXT))
    return ft.Column(controls, spacing=4)


def button(text, action, secondary=False):
    return btn(text, action, 'secondary' if secondary else 'primary', height=55)

LABELS = {'starting':'Aguardando equipamento iniciar','charging':'Recarga confirmada','stopping':'Parada pendente no equipamento','completed':'Recarga concluída','failed':'Falha confirmada','interrupted':'Recarga interrompida'}
DEMO_LABELS = {'starting':'Aguardando início simulado','charging':'Recarga simulada em andamento','stopping':'Finalizando recarga simulada','completed':'Recarga simulada concluída','failed':'Falha simulada','interrupted':'Recarga simulada interrompida'}
SOURCE = {'simulated':'Simulada pelo equipamento','measured':'Medida','estimated':'Estimada'}
ACTIVE = {'starting','charging','stopping'}
END_REASONS = {'user_stop':'Parada solicitada', 'stop_requested':'Parada solicitada', 'duration_limit':'Limite de duração atingido', 'max_duration':'Limite de duração atingido', 'cost_limit':'Limite de custo atingido', 'max_cost':'Limite de custo atingido', 'disconnected':'Cabo desconectado', 'device_fault':'Falha no equipamento', 'reboot':'Equipamento reiniciado'}
END_REASONS.update(requested='Parada solicitada', communication_lost='Conexão perdida com o servidor',
                   device_reboot='Equipamento reiniciado', command_timeout='Equipamento não confirmou a operação',
                   battery_full='Bateria cheia (100%)')
MODES = [('time','Por tempo'),('value','Por valor'),('autonomy','Por autonomia')]
DEFAULT_CAR = {'name':'BYD Dolphin','usable_kwh':44.9,'consumption':14.0,'soc':vehicle_state.SOC_MIN,'source':'simulated'}


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


TITLES = {'completed':'Recarga concluída','failed':'Recarga com falha','interrupted':'Recarga interrompida'}


def screen_title(session):
    if session.get('end_reason') == 'battery_full':  # já vem em 'stopping' (parada a 100 %)
        return 'Bateria cheia'
    return TITLES.get(session.get('status'),'Recarga em andamento')


def credit_notice(amount):
    """Linha do fim da recarga quando a sobra do pré-pagamento voltou ao saldo."""
    text = f"{money(amount)} voltou como crédito"
    return ft.Container(ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE,size=20,color=theme.SUCCESS),
                                ft.Column([d.txt(text,13,'bold'),
                                           d.txt('Crédito de recarga não utilizada, já disponível no seu saldo.',11,
                                                 'regular',theme.GRAY_TEXT)],spacing=2,expand=True)],
                               spacing=10,vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        bgcolor=theme.CARD,border_radius=d.RADIUS_BTN,padding=ft.Padding(left=14,right=14,top=12,bottom=12),
                        data='prepaid-credit')


async def push_phone_soc(app, session):
    """Modo apresentação: envia a bateria do celular para a API; devolve a sessão atualizada (ou ``session``)."""
    if session.get('status') not in ('starting','charging') or not vehicle_state.presentation_mode(app):
        return session
    level = await vehicle_state.phone_battery(app)
    if level is None:
        return session
    try:
        result = await app.api.request('POST',f"charging-sessions/{session['id']}/soc",{'soc_percent':level})
    except ApiError:
        return session  # a próxima leitura tenta de novo; o equipamento segue com o último valor
    return result if isinstance(result,dict) and result.get('id') == session['id'] else session


def _metrics(session):
    """(gauge, custo, potência, tempo restante) para o painel; só dados recebidos, nunca um relógio local."""
    progress,label = _progress(session)
    percent = f'{progress*100:.0f}%' if progress is not None and label.startswith('Bateria') else '-%'
    cost = money(session.get('cost_estimate')) if session.get('cost_estimate') is not None else '-'
    power_kw = (session.get('connector') or {}).get('power_kw')
    power = f"{float(power_kw):g} kW".replace('.',',') if session.get('status') == 'charging' and power_kw is not None else '- kW'
    remaining = '- minutos'
    if session.get('status') in ACTIVE:
        try:
            start = datetime.fromisoformat(session['started_at'].replace('Z','+00:00'))
            seen = datetime.fromisoformat(session['last_measurement_at'].replace('Z','+00:00'))
            left = max(0,int(session['max_duration_minutes'])-int((seen-start).total_seconds()//60))
            remaining = f"{left} {'minuto' if left == 1 else 'minutos'}"
        except (KeyError,AttributeError,TypeError,ValueError):
            pass
    return percent,cost,power,remaining


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
    controls.append(ft.ExpansionTile(title=ft.Text('Detalhes da recarga',color=theme.TEXT_COLOR,size=13),
        expanded_cross_axis_alignment=ft.CrossAxisAlignment.START,controls=details))
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


def _car(draft):
    return draft.get('car') or DEFAULT_CAR


def _autonomy(draft):
    """Resultado de ``rules.autonomy_limits`` para o rascunho (levanta ``ApiError`` com a explicação)."""
    connector = draft['point_context'].get('connector') or {}
    try:
        km = rules.parse_km(draft.get('autonomy_km'))
        return rules.autonomy_limits(km,_car(draft),connector.get('power_kw'),connector.get('price_per_kwh') or 0,
                                     _point_limit(draft))
    except (ValueError,ArithmeticError) as exc:
        raise ApiError(str(exc) or 'Informe a autonomia em km inteiros (ex.: 120).') from exc


def _limits(draft):
    if draft['mode'] == 'autonomy':
        result = _autonomy(draft)
        body = {'max_duration_minutes':result['max_duration_minutes']}
        if result.get('max_cost') is not None:
            body['max_cost'] = format(result['max_cost'],'f')
        return body
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
    if draft['mode'] == 'autonomy':
        try:
            result = _autonomy(draft)
        except ApiError as exc:
            return str(exc)
        energy = f"{result['energy_kwh']:.2f}".replace('.',',')
        return (f"Cerca de {energy} kWh para ~{result['km']} km com o {_car(draft)['name']} "
                f"(até {result['max_duration_minutes']} min). O consumo real varia.")
    try:
        limits = _limits(draft)
        return estimate_text(connector, limits['max_duration_minutes'], limits.get('max_cost'))
    except (ApiError,TypeError,ValueError):
        return 'A estimativa depende da tarifa, potência e limites do ponto. Nenhuma cobrança real.'


def _header(app, step):
    return ft.Column([
        d.progress_bar(3, step),
        d.page_title(('Confirmar ponto','Definir limites','Revisar recarga')[step-1], getattr(app,'back',None), size=18),
    ],spacing=10)


def _review(draft):
    context = draft['point_context']
    point = context.get('connector') or {}
    body = draft.get('pending_body') if draft.get('uncertain') else _body(draft)
    rows = [('Ponto',context.get('station_name') or 'Identificado pelo código #F'),
            ('Endereço',context.get('station_address')),
            ('Conector',' · '.join(str(point[key]) for key in ('public_code','connector_type') if point.get(key))),
            ('Código de presença',body['presence_code']),
            ('Autonomia desejada',f"{draft.get('autonomy_km')} km" if draft['mode'] == 'autonomy' else None),
            ('Limite de tempo',f"{body['max_duration_minutes']} min"),
            ('Limite de valor',money(body['max_cost']) if body.get('max_cost') else None),
            ('Tarifa',f"{money(point['price_per_kwh'])}/kWh" if point.get('price_per_kwh') is not None else None),
            ('Cupom',body.get('coupon_code'))]
    controls = [d.txt('RESUMO DA RECARGA',11,'bold',theme.GRAY_TEXT)]
    for label,value in rows:
        if value:
            controls.append(ft.Row([d.txt(label,11,'regular',theme.GRAY_TEXT,width=104),
                                    d.txt(str(value),12.5,'semibold',expand=True)],
                                   vertical_alignment=ft.CrossAxisAlignment.START,spacing=12))
    return d.card_box(ft.Column(controls,spacing=12,horizontal_alignment=ft.CrossAxisAlignment.STRETCH),padding=18)


async def build(app, public_code='', reservation_id=None, session_id=None, max_duration=30, point_context=None, step=None, pending_start=False, planning_intent=None, station_search=None, demo_seed=None, **_):
    demo = getattr(app.api,'is_demo',False) is True
    from .reservations import seed_demo
    await seed_demo(app, demo_seed)
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
        live = {}
        async def update():
            current = await app.api.request('GET',f"charging-sessions/{session['id']}")
            current = await push_phone_soc(app,current)
            if current['status'] != session['status']:
                await app.go('charging',session_id=session['id'])
                return
            state.content = session_card(current,demo=demo)
            journey.content = journey_summary(current, demo=demo)
            for name,value in zip(('percent','cost','power','remaining'),_metrics(current)):
                if name in live:
                    live[name].value = value
            app.page.update()
        extra = [state,journey,point_summary(session)]
        extra.extend(event_disclosure(app, session['id']))
        if session['status'] in ACTIVE:
            app.set_poll(update,5)
        else:
            # Fim da recarga: o carro fica com o SoC final e a sobra paga antes volta como crédito (uma vez).
            vehicle_state.record_session_end(app,session)
            credited = prepaid.settle(app,session)
            if credited:
                extra.insert(0,credit_notice(credited))
            async def again():
                app.api.clear_operation('charging-sessions')
                app.charging_draft = None
                await app.go('charging')
            if getattr(app,'charging_draft',None):
                extra.insert(0,button('Retomar preparação da recarga',app.link('charging'),secondary=True))
            action = btn('Iniciar outra recarga',app.action(again))
        if session['status'] in ('starting','charging'):
            action = btn('Encerrar recarga',app.action(stop),'danger')
        elif session['status'] == 'stopping':
            action = btn('Encerrando recarga...',None,'secondary')
        extra.append(ft.Text(
            'Atualiza a cada 5 s. A evolução é simulada nesta conta; nenhum equipamento real recebe comandos.'
            if demo and session['status'] in ACTIVE else
            'Atualiza a cada 5 s. Fechar o app ou sair da conta mantém a sessão física e seus limites.'
            if session['status'] in ACTIVE else 'Sessão encerrada. Os dados também estão disponíveis no histórico.',
            size=12,color=theme.GRAY_TEXT))
        percent,cost,power,remaining = _metrics(session)
        return recharge_detail(
            app,screen_title(session),
            when=when_text(session.get('started_at') or session.get('created_at')),
            address=session.get('station_address'),percent=percent,cost=cost,power=power,remaining=remaining,
            action=action,on_back=app.link('reservations'),extra=extra,live=live)

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
                        button('Ver minha reserva',app.link('reservations',detail=True))]
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
                                               button('Ver minha reserva',app.link('reservations',detail=True))],spacing=15)
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
                 'mode':'time','max_cost':'','autonomy_km':'','car':None,'coupon_code':'','step':1,'furthest':1,
                 'key':app.api.new_key(),'last_body':None,'pending_body':None,'uncertain':False}
        saved_intent = getattr(app, 'planning_intent', None) or {}
        draft['station_search'] = deepcopy(station_search or (
            saved_intent.get('station_search') if connector.get('id') == saved_intent.get('connector_id') else {}) or {})
        intention = planning_intent
        if not intention and connector.get('id') == saved_intent.get('connector_id'):
            intention = saved_intent.get('intent')
        if intention and intention.get('mode') == 'autonomy':
            draft.update(mode='autonomy', autonomy_km=str(intention.get('km') or ''))
        elif intention:
            limits = intent_limits(connector, intention)
            draft['duration_minutes'] = draft['safety_minutes'] = str(limits['minutes'])
            if limits.get('max_cost'):
                draft.update(mode='value', max_cost=limits['max_cost'])
        if connector.get('id') == saved_intent.get('connector_id'):
            app.planning_intent = None
    elif not uncertain:
        draft.update(public_code=public_code,reservation_id=reservation_id,point_context=deepcopy(context))
    app.charging_draft = draft
    if draft['mode'] == 'autonomy' and not draft.get('car') and not uncertain:
        # Carro do perfil + SoC escondido: convertem "Por autonomia" em limites (nunca exibidos como número).
        draft['car'] = await vehicle_state.snapshot(app)
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

    controls = [_header(app,step)]
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
                     ft.Text('Use #F12345 na conta demo; não é necessário um equipamento real.' if demo else
                             'No local, leia os cinco números atuais após #F na tela do equipamento. O código muda periodicamente e é conferido pela API ao solicitar o início.',
                             size=13,color=theme.GRAY_TEXT),presence,button('Continuar',app.action(continue_code))]
        if not context:
            controls.append(button('Prefiro escolher o ponto na lista',app.link('stations'),secondary=True))
    elif step == 2:
        duration = field('Duração máxima (min)',draft['duration_minutes'])
        cost = field('Limite de custo estimado (R$)',draft['max_cost'])
        autonomy = field('Autonomia desejada (km)',draft.get('autonomy_km',''))
        safety = field('Tempo máximo de segurança (min)',draft['safety_minutes'])
        coupon = field('Cupom (opcional)',draft['coupon_code'])
        for control in (duration,cost,safety,coupon,autonomy):
            control.width = None
        duration.keyboard_type = cost.keyboard_type = safety.keyboard_type = autonomy.keyboard_type = ft.KeyboardType.NUMBER
        # One-tap durations: typing minutes on a phone keyboard is the slowest step.
        limit_minutes = _point_limit(draft)
        presets = sorted({minutes for minutes in (15,30,60) if minutes < limit_minutes} | {min(limit_minutes,1440)})

        def choose_duration(minutes):
            async def choose():
                duration.value = str(minutes)
                await changed()
            return choose
        preset_row = ft.Row([d.chip_option(f'{minutes} min' if minutes != limit_minutes else f'Máx. {minutes} min',
                                           on_click=app.action(choose_duration(minutes)))
                             for minutes in presets],wrap=True,spacing=8,run_spacing=8)
        time_panel = ft.Column([duration,preset_row],visible=draft['mode']=='time',spacing=10,
                               horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        safety_section,safety_summary = disclosure_field('Ajustar tempo máximo','',[
            safety,ft.Text('A recarga para ao atingir o valor ou o tempo máximo, o que acontecer primeiro.',size=12,color=theme.GRAY_TEXT)],
            expanded=draft.get('safety_expanded',False),on_toggle=lambda value:draft.update(safety_expanded=value),on_update=app.page.update)
        # Cupons ficam fora da área do motorista: o campo segue no rascunho, mas não é exibido.
        coupon_section,coupon_summary = disclosure_field('Cupom de desconto','Opcional',[
            coupon,ft.Text('O código será validado ao solicitar o início. Informar um cupom não confirma o desconto.',size=12,color=theme.GRAY_TEXT)],
            expanded=draft.get('coupon_expanded',bool(draft['coupon_code'])),on_toggle=lambda value:draft.update(coupon_expanded=value),on_update=app.page.update)
        value_panel = ft.Column([cost,safety_section],
                               spacing=12,visible=draft['mode']=='value',horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        autonomy_note = ft.Text(size=12,color=theme.GRAY_TEXT,visible=False)
        autonomy_panel = ft.Column([autonomy,autonomy_note],spacing=10,visible=draft['mode']=='autonomy',
                                   horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        estimate = ft.Text(size=13,color=theme.GRAY_TEXT)
        mode_toggle = ft.Container()

        def capture_limits():
            draft.update(duration_minutes=duration.value or '',max_cost=cost.value or '',
                         safety_minutes=safety.value or '',coupon_code=coupon.value or '',
                         autonomy_km=autonomy.value or '',furthest=2)
            saved()

        def refresh_mode():
            mode = draft['mode']
            time_panel.visible,value_panel.visible,autonomy_panel.visible = (mode=='time',mode=='value',
                                                                             mode=='autonomy')
            mode_toggle.content = d.segmented(MODES,draft['mode'],lambda value:select_mode(value),height=40)
            note = None
            if mode == 'autonomy':
                try:
                    car = _car(draft)
                    note = rules.autonomy_note(rules.autonomy_energy(rules.parse_km(draft.get('autonomy_km')),
                                                                     car['consumption'],car['soc'],car['usable_kwh']))
                except (ValueError,ArithmeticError):
                    note = None
            autonomy_note.value,autonomy_note.visible = note or '',bool(note)
            safety_summary.value = f"Limite de segurança: {draft['safety_minutes']} min"
            coupon_summary.value = 'Código informado · validação no início' if draft['coupon_code'].strip() else 'Opcional · adicionar código'
            estimate.value = _estimate(draft)

        async def changed(event=None):
            capture_limits()
            for control in (duration,cost,safety,coupon,autonomy):
                control.error_text = None
            refresh_mode()
            app.page.update()

        async def select_mode(value):
            capture_limits()
            if value == 'autonomy' and not draft.get('car'):
                draft['car'] = await vehicle_state.snapshot(app)
            draft['mode'] = value
            refresh_mode()
            app.page.update()

        duration.on_change = cost.on_change = safety.on_change = coupon.on_change = autonomy.on_change = changed
        refresh_mode()
        async def continue_limits():
            capture_limits()
            try:
                _limits(draft)
            except ApiError as exc:
                target = (duration if draft['mode']=='time' else autonomy if draft['mode']=='autonomy'
                          else safety if 'duração' in str(exc) else cost)
                target.error_text = str(exc)
                app.page.update()
                raise
            draft['furthest'] = 3
            await navigate(3)
        async def back():
            capture_limits()
            await navigate(1)
        controls += [mode_toggle,
                     time_panel,value_panel,autonomy_panel,estimate,
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
            sent = draft.get('pending_body') or draft.get('last_body') or {}
            prepaid.link_session(app,result['id'],reservation_id=sent.get('reservation_id') or draft['reservation_id'],
                                 connector_id=(draft['point_context'].get('connector') or {}).get('id'))
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
                # Bateria do carro (escondida; no modo apresentação, a do celular) e capacidade útil:
                # a API e o totem passam a mostrar o mesmo SoC durante a recarga.
                body.update(await vehicle_state.start_fields(app))
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
                try:
                    result = await app.api.request('POST','charging-sessions',body,key=draft['key'])
                except ApiError as exc:
                    # API anterior à bateria do carro recusa campos desconhecidos (422 sem
                    # efeito): repete uma vez sem eles, com nova chave, para não travar a recarga.
                    legacy = {k: v for k, v in body.items() if k not in vehicle_state.START_KEYS}
                    if exc.status != 422 or exc.code != 'validation_error' or legacy == body:
                        raise
                    body = legacy
                    draft['key'] = app.api.new_key()
                    draft['pending_body'] = deepcopy(body)
                    draft['last_body'] = deepcopy(body)
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
