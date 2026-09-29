import unicodedata

TOPICS = {
    'Iniciar uma recarga': (
        'Escolha um posto, toque em Ver pontos e selecione o ponto disponível. Se já estiver no local, toque em “Já estou aqui: iniciar”. '
        'Na etapa Confirmar ponto, leia no próprio equipamento os cinco números atuais após #F e informe-os no app. Não guarde o código para usar depois. '
        'Continue para Definir limites, confira a etapa Revisar recarga e toque em Solicitar início. '
        'O código fixo identifica o ponto; o #F confirma presença e muda a cada 5 minutos. '
        'O início só é confirmado quando o equipamento responde. Não há descoberta Bluetooth.'
    ),
    'Reservar para chegar depois': (
        'Selecione um ponto disponível e faça a reserva. Aguarde a confirmação do equipamento. '
        'Após confirmar, você tem 10 minutos para chegar; veja o prazo em Minha reserva. '
        'No local, abra a reserva e informe o #F do visor. Cancelar também depende de confirmação.'
    ),
    'Tempo, valor e cupons': (
        'Por tempo define a duração máxima. Por valor define um teto de custo estimado, sempre com '
        'um limite de duração de segurança. A recarga pode terminar antes ao atingir um dos limites. '
        'Cupons válidos reduzem a estimativa nos postos indicados. Não há Pix, cobrança real ou saldo no app.'
    ),
    'Parar ou resolver uma falha': (
        'Abra Minha recarga e toque em Solicitar parada. Aguarde a confirmação do equipamento; '
        'pedido enviado não significa parada física confirmada. Offline mostra os últimos dados recebidos. '
        'Confira a rede do celular e do ESP32. Fechar o app, sair da conta ou trocar de modo não encerra '
        'a sessão física. Não conecte este protótipo a redes de alta potência ou baterias de veículo.'
    ),
    'Criar posto e vincular ponto': (
        'No modo operador, abra Postos e escaneie o QR de vinculação do ESP32 sem dono. '
        'Posto é o endereço; ponto é o equipamento instalado nele. Escolha um novo posto ou um existente, '
        'defina a tarifa e os limites, revise e publique. O QR de vinculação é privado: não o compartilhe. '
        'Restaurar remove o vínculo e gera um novo QR, preservando o Wi-Fi no firmware atual.'
    ),
    'Conta, senha e histórico': (
        'Em Conta você pode editar seus dados, alterar a senha e escolher o tema. Contas de operador '
        'podem alternar para motorista sem outro cadastro. Histórico mostra suas recargas no modo '
        'motorista e as dos seus postos no modo operador. Bateria e energia vêm do equipamento, '
        'identificadas como simuladas, medidas ou estimadas; o app não inventa progresso.'
    ),
}


def answer(question):
    """Local, deterministic guidance: no messages sent or fabricated support tickets."""
    normalized = ''.join(c for c in unicodedata.normalize('NFKD', question.casefold())
                         if not unicodedata.combining(c))
    rules = [
        (('senha', 'conta', 'historico', 'perfil', 'tema'), 'Conta, senha e histórico'),
        (('offline', 'parar', 'parada', 'falha', 'erro', 'rede', 'conexao'), 'Parar ou resolver uma falha'),
        (('operador', 'vendedor', 'criar', 'vincul', 'restaur', 'qr', 'cadastro'), 'Criar posto e vincular ponto'),
        (('reserva', 'chegar depois'), 'Reservar para chegar depois'),
        (('valor', 'tempo', 'limite', 'custo', 'cupom', 'cupons', 'pix', 'pagamento', 'dinheiro', 'preco'), 'Tempo, valor e cupons'),
        (('#f', 'codigo', 'iniciar', 'recarga', 'carregar', 'motorista', 'consumidor'), 'Iniciar uma recarga'),
    ]
    for words, topic in rules:
        if any(word in normalized for word in words):
            return topic, TOPICS[topic]
    return ('Escolha um assunto abaixo',
            'Esta ajuda local responde dúvidas sobre os fluxos do ChargeGrid. Não é uma IA nem atendimento '
            'humano e não abre chamados. Não envie senhas, códigos privados ou dados bancários.')
