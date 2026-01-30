# OilPriceAPI WebSocket Tester

Test your WebSocket connection to OilPriceAPI's real-time energy price feed.

## Prerequisites

- OilPriceAPI account with WebSocket access (Reservoir Mastery tier or websocket add-on)
- Your API key from https://oilpriceapi.com/api-keys

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

## What to Expect

Once connected, you'll see:

1. Welcome message from server
2. Subscription confirmation
3. Price updates every few seconds (when market data changes)

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

**Connection refused / 401 Unauthorized**

- Verify your API key is correct
- Ensure your account has WebSocket access (Reservoir Mastery tier or add-on)

**No price updates**

- Price updates are sent when market data changes
- During quiet periods, you may only see ping messages

## Security

Your API key is never stored - always passed at runtime. This repository contains no secrets.

## License

MIT
