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
pip install websocket-client
python python/tester.py YOUR_API_KEY
```

## Features

### All Clients

| Feature                  | Description                                        |
| ------------------------ | -------------------------------------------------- |
| **Connection Latency**   | Measures time to establish WebSocket connection    |
| **Message Stats**        | Tracks message count, bytes received, messages/sec |
| **Uptime Tracking**      | Shows how long connected                           |
| **Pretty Price Display** | Formatted price cards with change arrows (▲/▼)     |
| **Local Dev Mode**       | Connect to localhost:5000 for development          |
| **Custom URL**           | Override endpoint via env var or input             |
| **Auth Error Detail**    | Specific troubleshooting for 401/403/1006 errors   |
| **Log Export**           | Save session log to file for debugging             |
| **Auto Reconnect**       | Up to 5 retries with exponential backoff           |
| **Graceful Shutdown**    | Clean disconnect with final stats on Ctrl+C        |

### Browser UI Specific

- **Live Price Cards** - Visual display of Brent, WTI, US/UK Natural Gas
- **Options Panel** - Toggle local mode, verbose mode, show pings
- **Stats Bar** - Messages, Bytes, Rate, Latency, Uptime
- **Log Rotation** - Keeps last 1000 entries to prevent memory issues
- **Export Button** - Download log as .txt file

### CLI Options

```bash
# Node.js
node cli/index.js YOUR_API_KEY [options]

Options:
  -l, --local    Use localhost:5000 (development mode)
  -a, --all      Show all measures (drilling intelligence, well permits)
  -v, --verbose  Show detailed connection info and raw messages
  -p, --pings    Show ping messages (filtered by default)
  -e, --export   Export log to file on exit
  -s, --scroll   Classic scrolling output (instead of in-place update)
  -h, --help     Show help

# Python
python python/tester.py YOUR_API_KEY [options]

Same options as Node.js CLI
```

## Configuration

### config.json

Edit `config.json` to customize which measures are displayed:

```json
{
  "measures": {
    "oil": {
      "brent": {
        "enabled": true,
        "label": "Brent Crude",
        "unit": "$",
        "suffix": "/bbl"
      },
      "wti": {
        "enabled": true,
        "label": "WTI Crude",
        "unit": "$",
        "suffix": "/bbl"
      }
    },
    "natural_gas": {
      "us": {
        "enabled": true,
        "label": "US Natural Gas",
        "unit": "$",
        "suffix": "/MMBtu"
      },
      "uk": {
        "enabled": true,
        "label": "UK Natural Gas",
        "unit": "",
        "suffix": "p/therm"
      },
      "eu": {
        "enabled": true,
        "label": "EU Natural Gas",
        "unit": "€",
        "suffix": "/MMBtu"
      }
    },
    "drilling_intelligence": {
      "enabled": true,
      "rig_counts": {
        "us_rigs": { "enabled": true, "label": "US Rig Count" }
      }
    }
  }
}
```

Set `"enabled": false` to hide any measure.

### Custom WebSocket URL

Override the default WebSocket URL:

```bash
# Environment variable (all clients)
export OILPRICEAPI_WS_URL=wss://custom-endpoint.example.com/cable

# Node.js
node cli/index.js YOUR_API_KEY

# Python
python python/tester.py YOUR_API_KEY

# Or use --url flag
python python/tester.py YOUR_API_KEY --url wss://custom.example.com/cable
```

## What to Expect

Once connected, you'll see:

1. **Welcome message** from server
2. **Subscription confirmation**
3. **Price updates** when market data changes

Example price update (formatted):

```
┌─────────────────────────────────────────┐
│           LIVE PRICES                   │
├─────────────────────────────────────────┤
│  Brent Crude: $74.50 ▲ 0.35%           │
│  WTI Crude: $71.20 ▼ 0.12%             │
│  US NatGas: $2.45 ▲ 1.20%              │
│  UK NatGas: 85.30p/therm               │
└─────────────────────────────────────────┘
```

Raw message format:

```json
{
  "type": "price_update",
  "prices": {
    "oil": {
      "brent": { "normalized_price": 74.5, "change_percent": 0.35 },
      "wti": { "normalized_price": 71.2, "change_percent": -0.12 }
    },
    "natural_gas": {
      "us": { "normalized_price": 2.45 },
      "uk": { "normalized_price": 85.3 }
    }
  },
  "timestamp": "2026-01-30T10:00:00Z"
}
```

## Troubleshooting

### Connection timeout after 30 seconds

- Check your network connection
- Verify the WebSocket endpoint is accessible
- The tester will automatically retry up to 5 times

### Connection closed: 4001 - Unauthorized

- Verify your API key is correct
- Check the key hasn't been revoked

### Connection closed: 4003 - Forbidden

- WebSocket access requires Reservoir Mastery tier ($129/mo)
- Or purchase the WebSocket add-on
- Check https://oilpriceapi.com/dashboard

### Connection closed: 1006 - Abnormal closure

- Network interruption or firewall blocking WebSocket
- Check if your network allows WebSocket connections
- Try from a different network

### No price updates received

- Price updates are sent when market data changes
- During quiet periods, you may only see ping messages
- Enable `--pings` or "Show Ping Messages" to verify connection is alive

## Development

### Local Development Testing

1. Start your local API server on port 5000
2. Use `--local` flag or check "Local Development" in browser

```bash
# Node.js
node cli/index.js YOUR_API_KEY --local

# Python
python python/tester.py YOUR_API_KEY --local
```

### Verbose Mode

For debugging, enable verbose mode to see raw messages:

```bash
node cli/index.js YOUR_API_KEY --verbose --pings
```

### Exporting Logs

Export session logs for debugging or support tickets:

```bash
# CLI: Add --export flag, logs saved on Ctrl+C
node cli/index.js YOUR_API_KEY --export

# Browser: Click "Export Log" button
```

Log files include:

- Timestamp of export
- Connection URL
- Total messages and bytes
- Uptime
- Full message log

## Security

Your API key is never stored - always passed at runtime. This repository contains no secrets.

## License

MIT
