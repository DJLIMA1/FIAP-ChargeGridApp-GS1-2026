"""
Persistência simples em JSON — equivalente direto do DataManager
usado na versão Kivy original. Mantém a mesma estrutura básica de dados
(usuários e sessão ativa). Estações e cupons agora ficam guardados
dentro de cada conta de vendedor (users[email]["stations"/"coupons"]),
e não mais em uma área global compartilhada.
"""

import json
import os

from theme import DATA_FILE


class DataManager:
    """Camada de persistência única do app: todo o estado (contas, sessão
    ativa, preferência de tema, estações e cupons de cada vendedor, histórico
    de cada consumidor) vive num único dicionário Python, serializado inteiro
    a cada gravação. Não há banco de dados nem migrações — qualquer nova
    chave usada em `main.py` é criada sob demanda com `dict.setdefault` no
    ponto onde é lida pela primeira vez, em vez de aqui."""

    @staticmethod
    def load_data():
        """Carrega o ev_data.json do disco. Se o arquivo ainda não existir
        (primeira execução), cria a estrutura mínima (usuários vazios, sem
        sessão ativa) e já grava esse esqueleto antes de devolvê-lo."""
        if not os.path.exists(DATA_FILE):
            default_data = {
                "users": {},
                "settings": {
                    "active_session": None,
                    "active_role": None,
                },
            }
            DataManager.save_data(default_data)
            return default_data

        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def save_data(data):
        """Sobrescreve o ev_data.json inteiro com o dicionário `data` atual.
        Chamado depois de qualquer mudança que precise sobreviver a um
        reinício do app (login, CRUD de estação/cupom, histórico de recarga,
        preferência de tema etc.) — não há gravação incremental."""
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)