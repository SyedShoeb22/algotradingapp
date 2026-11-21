from app.broker.angel_one import connect_angel_one
s = connect_angel_one()
api = s['smart_api']
print('=== ANGEL ONE PROFILE ===')
print('Client:', s['client_code'], '| Name:', s['profile'].get('name'))

try:
    rms = api.rmsLimit()
    data = rms.get('data') or {}
    print('=== FUNDS / MARGIN ===')
    print('Available Cash:', data.get('availablecash'), '| Net:', data.get('net'))
except Exception as e:
    print('RMS error:', e)

try:
    orders = api.orderBook()
    orders_list = orders.get('data') or []
    print('=== ORDER BOOK ===')
    print('Total orders today:', len(orders_list))
    for o in orders_list[:3]:
        print('Order:', o.get('orderid'), o.get('tradingsymbol'), o.get('transactiontype'), o.get('quantity'), o.get('status'), o.get('averageprice'))
except Exception as e:
    print('OrderBook error:', e)

try:
    positions = api.position()
    pos_list = positions.get('data') or []
    print('=== POSITIONS ===')
    print('Open positions:', len(pos_list))
    for p in pos_list[:3]:
        print('Pos:', p.get('tradingsymbol'), p.get('netqty'), p.get('pnl'))
except Exception as e:
    print('Position error:', e)