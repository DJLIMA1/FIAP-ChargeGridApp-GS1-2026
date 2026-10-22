-- Remove (desativa) o posto "ChargeGrid fiap" de produção — remoção suave, idempotente.
--
-- O modelo não apaga postos: ``stations.active = false`` tira o posto da busca, do mapa, da IA e
-- bloqueia novas recargas; conectores com ``active = false`` não aceitam reserva nem recarga.
-- Nada é apagado: sessões, pagamentos, recibos e o dono (owner_id) continuam iguais, então
-- histórico e chaves estrangeiras ficam intactos. O dono ainda vê o posto como "desativado".
--
-- Como aplicar (orquestrador, com o OK do usuário):
--   1. Rode o BLOCO 1 (só leitura) e confira que aparece exatamente o posto "ChargeGrid fiap".
--   2. Rode o BLOCO 2 (uma transação). Rodar de novo não muda nada (só avisa).
--
-- Travas do BLOCO 2 (qualquer uma aborta sem alterar nada):
--   * mais de um posto com o nome (comparação sem diferenciar maiúsculas, espaços nas pontas ignorados);
--   * o nome contém "goodwe" (nunca desativar o posto da central real);
--   * reserva ativa (pending_device, confirmed, cancelling), recarga ativa (starting, charging,
--     stopping) ou pedido de totem aberto (held, awaiting_payment, paid) em algum conector do posto;
--   * dispositivo não revogado do posto visto nas últimas 24 h (equipamento vivo).

-- ============================================================ BLOCO 1 — conferência (só leitura)
SELECT s.id, s.name, s.active, s.owner_id,
       (SELECT count(*) FROM connectors c WHERE c.station_id = s.id) AS conectores,
       (SELECT count(*) FROM connectors c WHERE c.station_id = s.id AND c.active) AS conectores_ativos,
       (SELECT max(d.last_seen) FROM devices d JOIN connectors c ON c.id = d.connector_id
         WHERE c.station_id = s.id AND NOT d.revoked) AS dispositivo_visto_em,
       (SELECT count(*) FROM charging_sessions cs JOIN connectors c ON c.id = cs.connector_id
         WHERE c.station_id = s.id) AS sessoes,
       (SELECT count(*) FROM reservations r JOIN connectors c ON c.id = r.connector_id
         WHERE c.station_id = s.id AND r.status IN ('pending_device', 'confirmed', 'cancelling')) AS reservas_ativas,
       (SELECT count(*) FROM charging_sessions cs JOIN connectors c ON c.id = cs.connector_id
         WHERE c.station_id = s.id AND cs.status IN ('starting', 'charging', 'stopping')) AS recargas_ativas,
       (SELECT count(*) FROM kiosk_orders k JOIN connectors c ON c.id = k.connector_id
         WHERE c.station_id = s.id AND k.status IN ('held', 'awaiting_payment', 'paid')) AS pedidos_totem_abertos
  FROM stations s
 WHERE lower(btrim(s.name)) = 'chargegrid fiap';

-- ============================================================ BLOCO 2 — desativação (transação)
BEGIN;

DO $$
DECLARE
    target stations%ROWTYPE;
    matches integer;
    blocked integer;
BEGIN
    SELECT count(*) INTO matches FROM stations WHERE lower(btrim(name)) = 'chargegrid fiap';
    IF matches = 0 THEN
        RAISE NOTICE 'Nenhum posto "ChargeGrid fiap": nada a fazer.';
        RETURN;
    END IF;
    IF matches > 1 THEN
        RAISE EXCEPTION 'Há % postos "ChargeGrid fiap"; resolva a ambiguidade antes.', matches;
    END IF;

    SELECT * INTO target FROM stations WHERE lower(btrim(name)) = 'chargegrid fiap' FOR UPDATE;
    IF target.name ILIKE '%goodwe%' THEN
        RAISE EXCEPTION 'Recusado: o posto % parece ser o da central GoodWe.', target.id;
    END IF;

    -- Mesma ordem do PATCH /stations: trava os conectores antes de checar o que está em uso.
    PERFORM 1 FROM connectors WHERE station_id = target.id ORDER BY id FOR UPDATE;

    SELECT count(*) INTO blocked FROM reservations r JOIN connectors c ON c.id = r.connector_id
     WHERE c.station_id = target.id AND r.status IN ('pending_device', 'confirmed', 'cancelling');
    IF blocked > 0 THEN
        RAISE EXCEPTION 'Recusado: % reserva(s) ativa(s) no posto %.', blocked, target.id;
    END IF;
    SELECT count(*) INTO blocked FROM charging_sessions cs JOIN connectors c ON c.id = cs.connector_id
     WHERE c.station_id = target.id AND cs.status IN ('starting', 'charging', 'stopping');
    IF blocked > 0 THEN
        RAISE EXCEPTION 'Recusado: % recarga(s) ativa(s) no posto %.', blocked, target.id;
    END IF;
    SELECT count(*) INTO blocked FROM kiosk_orders k JOIN connectors c ON c.id = k.connector_id
     WHERE c.station_id = target.id AND k.status IN ('held', 'awaiting_payment', 'paid');
    IF blocked > 0 THEN
        RAISE EXCEPTION 'Recusado: % pedido(s) de totem aberto(s) no posto %.', blocked, target.id;
    END IF;
    SELECT count(*) INTO blocked FROM devices d JOIN connectors c ON c.id = d.connector_id
     WHERE c.station_id = target.id AND NOT d.revoked AND d.last_seen > now() - interval '24 hours';
    IF blocked > 0 THEN
        RAISE EXCEPTION 'Recusado: equipamento do posto % visto nas últimas 24 h.', target.id;
    END IF;

    IF NOT target.active AND NOT EXISTS (SELECT 1 FROM connectors WHERE station_id = target.id AND active) THEN
        RAISE NOTICE 'Posto % já estava desativado: nada mudou.', target.id;
        RETURN;
    END IF;
    UPDATE stations SET active = false WHERE id = target.id AND active;
    UPDATE connectors SET active = false WHERE station_id = target.id AND active;
    RAISE NOTICE 'Posto % ("%") desativado com seus conectores.', target.id, target.name;
END
$$;

COMMIT;
