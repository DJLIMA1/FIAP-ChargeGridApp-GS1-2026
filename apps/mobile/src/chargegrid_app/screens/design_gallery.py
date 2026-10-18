"""Galeria do design kit (rota ``design_gallery``): referência visual para o harness de capturas.

``go('design_gallery', variant='wizard'|'account'|'form'|'list'|'success'|'details')`` reproduz
telas da referência usando só ``ui.design``; não é navegável pelo app normal.
"""

from ..ui import design, theme


async def build(app, variant='wizard', **_):
    back = app.back
    if variant == 'account':
        return design.page(
            design.txt('Conta', 15, 'bold'),
            design.card_box(design.list_row('João Pedro Sousa', 'joaopedrosousa@email.com', chevron=False,
                                            tile_control=design.avatar(None, 54)), padding=0, radius=18),
            design.list_row('Meu saldo', 'R$ 214,80 disponíveis', icon=design.ft.Icons.ACCOUNT_BALANCE_WALLET,
                            dark_tile=True, plain=True),
            design.list_row('Perfil', 'Editar informações do usuário', icon=design.ft.Icons.EDIT, dark_tile=True,
                            plain=True),
            footer=design.primary_button('Sair'), gap=18)
    if variant == 'form':
        return design.page(
            design.labeled_input('Nome da estação', 'Marginal Pinheiros'),
            design.labeled_input('Endereço', 'Av. das Nações Unidas, 4777'),
            design.labeled_input('Identificador', 'CG-001'),
            design.labeled('Status', design.segmented([('on', 'Ativa'), ('off', 'Inativa')], 'on')),
            design.primary_button('Salvar alterações'),
            title='Configurar Estação', on_back=back, center_title=True, gap=14)
    if variant == 'list':
        return design.page(
            design.section_label('Próximas'),
            design.card_box(design.ft.Column([
                design.txt('Horário: 12:30 | Data: DD/MM/AAAA', 14),
                design.list_row('Villa Lobos', 'Pinheiros - São Paulo', tile=47, plain=True)], spacing=6)),
            design.section_label('Em andamento'),
            title='Minhas recargas', title_size=19, on_back=None,
            footer=design.danger_button('Buscar mais estações', height=54))
    if variant == 'success':
        return design.page(design.success_state('Pagamento aprovado', 'Seu saldo já foi atualizado.'), scroll=False)
    if variant == 'details':
        return design.page(
            design.map_image(158), design.txt('Villa Lobos', 22, 'bold'),
            design.txt('Av. Prof Fonseca Rodrigues, 4777', 16, 'regular', theme.GRAY_TEXT),
            design.section_label('Conectores'),
            design.list_row('CCS2 - 60 kW', '1 de 2 conectores livre'),
            design.list_row('Tipo 2 - 22 kW', '2 conectores livres'),
            title='Detalhes da estação', on_back=back, footer=design.primary_button('Reservar estação'))
    return design.page(
        design.radio_option('CCS2 - 60 kW', '1 de 2 conectores livre', selected=True),
        design.radio_option('Tipo 2 - 22 kW', '2 conectores livres'),
        title='Qual conector deseja usar?', on_back=back, steps=4, step=1, gutter=3,
        footer=[design.warning_box('A potência real pode variar conforme o veículo e o nível da bateria.'),
                design.primary_button('Continuar', height=55, size=16, weight='bold')])
