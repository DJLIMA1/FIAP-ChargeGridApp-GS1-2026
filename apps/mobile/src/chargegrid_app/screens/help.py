import flet as ft

from ..ui.components import card, title


async def build(app):
    return ft.Column([title('Ajuda ChargeGrid','Informações da demonstração'),card([ft.Text('Como reservar?',size=18),ft.Text('Escolha um ponto disponível. A reserva aparece pendente até o equipamento confirmar. Após isso, você tem 10 minutos para chegar.')]),card([ft.Text('Como iniciar e parar?',size=18),ft.Text('Informe o código público do ponto e conecte a bancada. Início e parada dependem de confirmação física. Não usamos descoberta Bluetooth.')]),card([ft.Text('Bateria e energia',size=18),ft.Text('SoC vem do equipamento: pode ser simulado, estimado, medido ou indisponível. O app não calcula progresso pelo tempo. Dados offline permanecem identificados como antigos.')]),card([ft.Text('Valores e segurança',size=18),ft.Text('Custo é apenas estimado; não existe Pix, cobrança ou conta bancária nesta versão. Não conecte o protótipo a redes de alta potência ou bateria de veículo.')]),card([ft.Text('Problemas de conexão',size=18),ft.Text('Confira a URL HTTPS da API, a rede e os certificados. Sem ACK, a ação fica pendente. Fechar o app não encerra a sessão. Não há equipe de suporte/chatbot ao vivo nesta demonstração.')])],spacing=15,scroll=ft.ScrollMode.AUTO)
