from decimal import Decimal, InvalidOperation

import flet as ft

from ..api_client import ApiError
from ..ui import theme
from ..ui.components import button, card, date_time, field, money, title

LABELS = {'starting':'Aguardando equipamento iniciar','charging':'Recarga confirmada','stopping':'Parada pendente no equipamento','completed':'Recarga concluída','failed':'Falha confirmada','interrupted':'Recarga interrompida'}
SOURCE = {'simulated':'Simulada pelo equipamento','measured':'Medida','estimated':'Estimada'}
ACTIVE = {'starting','charging','stopping'}
END_REASONS = {'user_stop':'Parada solicitada', 'stop_requested':'Parada solicitada', 'duration_limit':'Limite de duração atingido', 'max_duration':'Limite de duração atingido', 'cost_limit':'Limite de custo atingido', 'max_cost':'Limite de custo atingido', 'disconnected':'Cabo desconectado', 'device_fault':'Falha no equipamento', 'reboot':'Equipamento reiniciado'}
END_REASONS.update(requested='Parada solicitada', communication_lost='Conexão perdida com o servidor',
                   device_reboot='Equipamento reiniciado', command_timeout='Equipamento não confirmou a operação')


def session_card(session):
    soc = session.get('soc_percent')
    controls = [ft.Text(LABELS.get(session['status'],session['status']),size=20,weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR),ft.Text('Bateria: '+('não disponível' if soc is None else f'{float(soc):.0f}%'),size=24,color=theme.TEXT_COLOR),ft.Text(SOURCE.get(session.get('source'),'Origem não informada'),size=12,color=theme.GRAY_TEXT),ft.Divider(color=theme.LIGHT_GRAY),ft.Text(f"Energia: {float(session.get('energy_wh') or 0)/1000:.3f} kWh",color=theme.TEXT_COLOR),ft.Text('Custo estimado: '+money(session.get('cost_estimate')),color=theme.TEXT_COLOR),ft.Text('Limite de duração: '+str(session['max_duration_minutes'])+' min',color=theme.GRAY_TEXT),ft.Text('Última medida: '+date_time(session.get('last_measurement_at')),size=12,color=theme.GRAY_TEXT)]
    if session['status'] in ACTIVE and not session.get('online'):
        controls += [ft.Text('Equipamento offline. Últimos dados mantidos; parada física não confirmada.',color=theme.RED)]
    if session.get('end_reason'):
        controls.append(ft.Text('Encerramento: '+END_REASONS.get(session['end_reason'],session['end_reason']),size=12,color=theme.GRAY_TEXT))
    return card(controls)


async def build(app, public_code='', reservation_id=None, session_id=None, max_duration=30):
    session = await app.api.request('GET',f'charging-sessions/{session_id}' if session_id else 'charging-sessions/current')
    if not session and app.api.last_session_id and not public_code and not reservation_id:
        session = await app.api.request('GET',f'charging-sessions/{app.api.last_session_id}')
    if session:
        key = app.api.new_key()
        async def stop():
            await app.api.request('POST',f"charging-sessions/{session['id']}/stop",key=key)
            await app.go('charging',session_id=session['id'])
        state = ft.Container(session_card(session))
        controls = [title('Minha recarga'),state]
        async def update():
            current = await app.api.request('GET',f"charging-sessions/{session['id']}")
            if current['status'] != session['status']:
                await app.go('charging',session_id=session['id'])
                return
            state.content = session_card(current)
            app.page.update()
        if session['status'] in ACTIVE:
            app.set_poll(update,5)
        else:
            async def again():
                app.api.clear_operation('charging-sessions')
                await app.go('charging')
            controls.append(button('Iniciar outra recarga',app.action(again)))
        if session['status'] in ('starting','charging'):
            controls.append(button('Solicitar parada',app.action(stop)))
        controls += [ft.Text(
            'Atualiza a cada 5 s. Fechar o app ou sair da conta mantém a sessão física e seus limites.'
            if session['status'] in ACTIVE else 'Sessão encerrada. Os dados também estão disponíveis no histórico.',
            size=12, color=theme.GRAY_TEXT)]
        return ft.Column(controls,spacing=15,scroll=ft.ScrollMode.AUTO)
    code, duration, cost, coupon = field('Código público do ponto',public_code),field('Duração máxima (min)', str(max_duration)),field('Limite de custo estimado (opcional)'),field('Cupom (opcional)')
    duration.keyboard_type = ft.KeyboardType.NUMBER
    cost.keyboard_type = ft.KeyboardType.NUMBER
    key = app.api.new_key()
    last_body = None
    async def start():
        nonlocal key,last_body
        if not code.value.strip():
            raise ApiError('Informe o código do ponto de recarga.')
        try:
            minutes = int(duration.value)
        except ValueError as exc:
            raise ApiError('Informe a duração em minutos inteiros.') from exc
        if not 1 <= minutes <= 1440:
            raise ApiError('Escolha uma duração de 1 a 1440 minutos, dentro do limite do ponto.')
        body = {'public_code':code.value.strip(),'max_duration_minutes':int(duration.value)}
        if reservation_id:
            body['reservation_id'] = reservation_id
        if cost.value.strip():
            try:
                amount = Decimal(cost.value.replace(',','.'))
                if not amount.is_finite() or not 0 < amount <= 100000:
                    raise InvalidOperation
            except InvalidOperation as exc:
                raise ApiError('Informe um limite de custo maior que zero e de até R$ 100.000.') from exc
            body['max_cost'] = cost.value.replace(',','.')
        if coupon.value.strip():
            body['coupon_code'] = coupon.value.strip()
        if last_body is not None and body != last_body:
            key = app.api.new_key()
        last_body = body.copy()
        result = await app.api.request('POST','charging-sessions',body,key=key)
        await app.go('charging',session_id=result['id'])
    return ft.Column([title('Iniciar recarga','Leia o código impresso no ponto.'),card(ft.Column([code,duration,cost,coupon],spacing=12)),ft.Text('Conecte a bancada antes de iniciar. O equipamento confirma a operação. Confira o código no próprio ponto.'),button('Solicitar início',app.action(start)),ft.Text('Valores demonstrativos. Nenhuma cobrança real.',size=12)],spacing=15,scroll=ft.ScrollMode.AUTO)
