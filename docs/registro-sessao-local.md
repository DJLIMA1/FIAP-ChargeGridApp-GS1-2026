# Registro observável da sessão — rodada local de 30/09/2026

O detalhe de recarga e o histórico do consumidor permitem abrir **Ver eventos da sessão**. A API persiste apenas fatos recebidos ou produzidos durante a operação, em ordem de inserção. Cada linha mostra o horário observado e a fonte: servidor, sincronização autenticada do ponto ou simulador local. O endpoint `GET /v1/charging-sessions/{id}/events` exige que a sessão pertença ao usuário autenticado; sessões alheias respondem 404.

O registro distingue pedido de START/STOP, ACK `received`, ACK `applied`, ACK `failed`, reconciliação após um período em que o servidor considerou o ponto offline e fim observado no sync. Repetições do mesmo pedido ou sync não criam novas linhas. A reconciliação só é registrada quando um novo sync aceito traz a sessão e o estado está conciliado. A ausência de linha não comprova que o ponto permaneceu online, e energia/bateria continuam sujeitas à origem da medição. Sessões anteriores à migração não recebem eventos retroativos.

A migração `9c4a2b8e1170` adiciona `session_events` sem modificar tabelas ou valores anteriores. Execute-a somente em um banco autorizado para o ambiente correspondente. Nesta rodada ela foi aplicada exclusivamente em PostgreSQL descartável local; nenhum banco remoto foi alterado. A demonstração guarda eventos apenas em memória, identificados como simulação.

O enunciado/rubrica da disciplina não foi disponibilizado. Este diferencial dá evidência de confirmação e falha sem afirmar critérios acadêmicos, medições físicas ou pagamentos. Ainda faltam validação em APK, acessibilidade com leitor de tela, teste físico com ESP32 e avaliação com usuários. Esses ensaios exigem coordenação própria.
