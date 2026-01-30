#!/usr/bin/env python3
"""OilPriceAPI WebSocket Tester - Python CLI"""

import os
import sys
import json
import time
import websocket

# Configuration
DEFAULT_URL = "wss://api.oilpriceapi.com/cable"
CHANNEL = "EnergyPricesChannel"
CONNECTION_TIMEOUT_SEC = 30
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_BASE_DELAY_SEC = 1

# Global state
reconnect_attempts = 0
api_key = None
ws_url = None


def on_message(ws, message):
    """Handle incoming WebSocket messages."""
    try:
        msg = json.loads(message)

        if msg.get('type') == 'ping':
            return

        if msg.get('type') == 'welcome':
            print('Server welcomed connection')
            return

        if msg.get('type') == 'confirm_subscription':
            print(f'Subscribed to {CHANNEL} - waiting for price updates...')
            return

        if 'message' in msg:
            print('\n--- Price Update ---')
            print(json.dumps(msg['message'], indent=2))
    except json.JSONDecodeError as e:
        print(f'Failed to parse message: {e}')
        print(f'Raw data: {message[:200]}')


def on_open(ws):
    """Subscribe to channel on connection open."""
    global reconnect_attempts
    reconnect_attempts = 0
    print(f'Connected! Subscribing to {CHANNEL}...')
    ws.send(json.dumps({
        'command': 'subscribe',
        'identifier': json.dumps({'channel': CHANNEL})
    }))


def on_error(ws, error):
    """Handle WebSocket errors."""
    print(f'Error: {error}')


def on_close(ws, close_status_code, close_msg):
    """Handle connection close."""
    print(f'Connection closed (code: {close_status_code})')
    handle_reconnect()


def handle_reconnect():
    """Attempt to reconnect with exponential backoff."""
    global reconnect_attempts

    if reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
        print(f'Max reconnection attempts ({MAX_RECONNECT_ATTEMPTS}) reached. Exiting.')
        sys.exit(1)

    reconnect_attempts += 1
    delay = RECONNECT_BASE_DELAY_SEC * (2 ** (reconnect_attempts - 1))
    print(f'Reconnecting in {delay}s (attempt {reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS})...')

    time.sleep(delay)
    run_websocket()


def run_websocket():
    """Create and run WebSocket connection."""
    ws = websocket.WebSocketApp(
        ws_url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    # Run with ping interval to detect dead connections
    ws.run_forever(
        ping_interval=20,
        ping_timeout=CONNECTION_TIMEOUT_SEC
    )


def main():
    """Main entry point."""
    global api_key, ws_url

    if len(sys.argv) < 2:
        print('Usage: python tester.py YOUR_API_KEY')
        print('')
        print('Environment variables:')
        print(f'  OILPRICEAPI_WS_URL - Custom WebSocket URL (default: {DEFAULT_URL})')
        sys.exit(1)

    api_key = sys.argv[1]
    base_url = os.environ.get('OILPRICEAPI_WS_URL', DEFAULT_URL)
    ws_url = f'{base_url}?token={api_key}'

    print(f'Connecting to {base_url}...')

    try:
        run_websocket()
    except KeyboardInterrupt:
        print('\nDisconnected')


if __name__ == '__main__':
    main()
