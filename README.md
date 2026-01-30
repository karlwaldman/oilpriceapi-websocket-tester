# OilPriceAPI WebSocket Tester

Test your WebSocket connection to OilPriceAPI's real-time energy price feed.

## Prerequisites

- OilPriceAPI account with WebSocket access (Reservoir Mastery tier or websocket add-on)
- Your API key from https://oilpriceapi.com/dashboard

## Quick Start

### Browser (Simplest)

1. Open `browser/index.html` in your browser
2. Enter your API key
3. Click Connect

### Node.js CLI

```bash
npm install
node cli/index.js YOUR_API_KEY
```

### Python

```bash
pip install -r python/requirements.txt
python python/tester.py YOUR_API_KEY
```

## Features

### Connection Management

- **30-second connection timeout** - Clear error if server is unreachable
- **Automatic reconnection** - Up to 5 retries with exponential backoff (1s, 2s, 4s, 8s, 16s)
- **Graceful error handling** - Malformed messages won't crash the tester

### Browser UI

- **Clear Log button** - Reset the message log anytime
- **Log rotation** - Automatically keeps last 1000 messages to prevent memory issues
- **Connection status indicator** - Shows Disconnected / Connecting / Connected states
- **Message counter** - Track how many messages received

### Configuration

Override the default WebSocket URL using an environment variable:

```bash
# Node.js
OILPRICEAPI_WS_URL=wss://custom-endpoint.example.com/cable node cli/index.js YOUR_API_KEY

# Python
OILPRICEAPI_WS_URL=wss://custom-endpoint.example.com/cable python python/tester.py YOUR_API_KEY
```

## What to Expect

Once connected, you'll see:

1. Welcome message from server
2. Subscription confirmation
3. Price updates when market data changes

Example price update:

```json
{
  "type": "price_update",
  "prices": [
    {
      "code": "BRENT",
      "name": "Brent Crude Oil",
      "value": 74.5,
      "currency": "USD",
      "unit": "barrel",
      "change_percent": -0.5,
      "updated_at": "2026-01-30T10:00:00Z"
    }
  ],
  "timestamp": "2026-01-30T10:00:00Z"
}
```

## Troubleshooting

**Connection timeout after 30 seconds**

- Check your network connection
- Verify the WebSocket endpoint is accessible
- Try again - the tester will automatically retry up to 5 times

**Connection refused / 401 Unauthorized**

- Verify your API key is correct
- Ensure your account has WebSocket access (Reservoir Mastery tier or add-on)

**Max reconnection attempts reached**

- The tester stops after 5 failed attempts to prevent infinite loops
- Check your API key and network, then restart the tester

**No price updates**

- Price updates are sent when market data changes
- During quiet periods, you may only see ping messages (filtered out by default)

## Security

Your API key is never stored - always passed at runtime. This repository contains no secrets.

## License

MIT
