#!/usr/bin/env python3
"""OilPriceAPI WebSocket Tester - Python CLI"""

import sys
import json
import websocket


def on_message(ws, message):
    """Handle incoming WebSocket messages."""
    msg = json.loads(message)

    if msg.get('type') == 'ping':
        return

    if msg.get('type') == 'welcome':
        print('Server welcomed connection')
        return

    if msg.get('type') == 'confirm_subscription':
        print('Subscribed to EnergyPricesChannel - waiting for price updates...')
        return

    if 'message' in msg:
        print('\n--- Price Update ---')
        print(json.dumps(msg['message'], indent=2))


def on_open(ws):
    """Subscribe to channel on connection open."""
    print('Connected! Subscribing to EnergyPricesChannel...')
    ws.send(json.dumps({
        'command': 'subscribe',
        'identifier': json.dumps({'channel': 'EnergyPricesChannel'})
    }))


def on_error(ws, error):
    """Handle WebSocket errors."""
    print(f'Error: {error}')


def on_close(ws, close_status_code, close_msg):
    """Handle connection close."""
    print('Connection closed')


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print('Usage: python tester.py YOUR_API_KEY')
        sys.exit(1)

    api_key = sys.argv[1]
    url = f'wss://api.oilpriceapi.com/cable?token={api_key}'

    print('Connecting to OilPriceAPI WebSocket...')

    ws = websocket.WebSocketApp(
        url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    try:
        ws.run_forever()
    except KeyboardInterrupt:
        print('\nDisconnected')


if __name__ == '__main__':
    main()
