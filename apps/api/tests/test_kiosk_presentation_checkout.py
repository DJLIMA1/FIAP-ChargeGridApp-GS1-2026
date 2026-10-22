"""QR de apresentação aponta para o pedido real, sem confirmar cobrança por GET."""
import re
from urllib.parse import urlsplit

from test_kiosk_totem import Bench

pytest_plugins = ("test_kiosk_totem",)


def test_presentation_checkout_qr_is_real_read_only_and_signed(http, presentation):
    bench = Bench(http)
    order = bench.order().json()
    assert order['payment'] is None and order['status'] == 'held'
    url = urlsplit(order['qr_url'])
    assert url.path == f"/pay/o/{order['id']}" and url.query.startswith('t=')
    response = http.get(f'{url.path}?{url.query}', follow_redirects=False)
    assert response.status_code == 200
    assert 'R$ 20,00' in response.text and 'Já efetuei o pagamento' in response.text
    assert 'Nesta recarga nenhum valor é cobrado.' in response.text
    assert not re.search(r"simulad|demonstra|\bteste\b|modo teste|ambiente de teste|modo apresenta", response.text, re.I)
    assert response.headers['cache-control'] == 'no-store'
    assert bench.get(order['id']).json()['payment'] is None
    assert bench.get(order['id']).json()['status'] == 'held'
    assert bench.sync()['kiosk_order']['qr_url'] == order['qr_url']
    assert http.get(f'{url.path}?t=invalid', follow_redirects=False).status_code == 404
    assert bench.cancel(order['id']).status_code == 200
    assert bench.get(order['id']).json()['qr_url'] is None


def test_checkout_get_does_not_confirm_stripe_or_simulated_payment(http, stripe):
    bench = Bench(http)
    order = bench.order().json()
    assert order['qr_url'] is None
    pay = bench.pay(order['id']).json()
    url = urlsplit(pay['payment']['qr_url'])
    response = http.get(f'{url.path}?{url.query}', follow_redirects=False)
    assert response.status_code == 303
    assert response.headers['location'].startswith('https://')
    assert bench.get(order['id']).json()['payment']['status'] == 'awaiting_payment'
