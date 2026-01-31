#!/usr/bin/env node
const WebSocket = require("ws");
const fs = require("fs");
const path = require("path");
const logUpdate = require("log-update");

// Load config
const configPath = path.join(__dirname, "..", "config.json");
let config = {};
try {
  config = JSON.parse(fs.readFileSync(configPath, "utf8"));
} catch (e) {
  // Use defaults if config not found
}

// Configuration with defaults
const PROD_URL = config.connection?.url || "wss://api.oilpriceapi.com/cable";
const LOCAL_URL = config.connection?.localUrl || "ws://localhost:5000/cable";
const CHANNEL = config.connection?.channel || "EnergyPricesChannel";
const CONNECTION_TIMEOUT_MS = config.connection?.timeoutMs || 30000;
const MAX_RECONNECT_ATTEMPTS = config.connection?.maxReconnectAttempts || 5;
const RECONNECT_BASE_DELAY_MS = 1000;
const MAX_LOG_LINES = config.display?.maxLogLines || 8;
const REFRESH_MS = config.display?.refreshMs || 500;

// Parse arguments
const args = process.argv.slice(2);
const flags = {
  local: args.includes("--local") || args.includes("-l"),
  verbose: args.includes("--verbose") || args.includes("-v"),
  showPings: args.includes("--pings") || args.includes("-p"),
  export: args.includes("--export") || args.includes("-e"),
  help: args.includes("--help") || args.includes("-h"),
  scroll: args.includes("--scroll") || args.includes("-s"),
  all: args.includes("--all") || args.includes("-a"),
};

const apiKey = args.find((a) => !a.startsWith("-"));
const customUrl = process.env.OILPRICEAPI_WS_URL;

if (flags.help || !apiKey) {
  console.log(`
OilPriceAPI WebSocket Tester - CLI

Usage: node cli/index.js YOUR_API_KEY [options]

Options:
  -l, --local    Use localhost:5000 (development mode)
  -a, --all      Show all available measures (including drilling data)
  -v, --verbose  Show detailed connection info and raw messages
  -p, --pings    Show ping messages (filtered by default)
  -e, --export   Export log to file on exit
  -s, --scroll   Classic scrolling output (instead of in-place update)
  -h, --help     Show this help message

Configuration:
  Edit config.json to customize measures, labels, and display options.

Environment variables:
  OILPRICEAPI_WS_URL  Custom WebSocket URL (overrides --local)

Examples:
  node cli/index.js abc123                    # Connect to production
  node cli/index.js abc123 --all              # Show all measures
  node cli/index.js abc123 --local            # Connect to localhost
  node cli/index.js abc123 -v -p              # Verbose mode with pings
`);
  process.exit(flags.help ? 0 : 1);
}

// Determine URL
const baseUrl = customUrl || (flags.local ? LOCAL_URL : PROD_URL);
const url = `${baseUrl}?token=${apiKey}`;

// State
let ws = null;
let reconnectAttempts = 0;
let connectionTimeout = null;
let connectionStartTime = null;
let messageCount = 0;
let bytesReceived = 0;
let lastPingTime = null;
let pingCount = 0;
let connectionStatus = "disconnected";
let displayInterval = null;
const logEntries = [];
const recentLogs = [];

// Dynamic price state based on config
const prices = {};
const drilling = {};

// Initialize price state from config
function initPriceState() {
  const measures = config.measures || {};

  // Oil prices
  if (measures.oil) {
    for (const [key, cfg] of Object.entries(measures.oil)) {
      if (cfg.enabled !== false) {
        prices[`oil_${key}`] = {
          value: null,
          change: null,
          updated: null,
          config: cfg,
        };
      }
    }
  }

  // Natural gas prices
  if (measures.natural_gas) {
    for (const [key, cfg] of Object.entries(measures.natural_gas)) {
      if (cfg.enabled !== false) {
        prices[`gas_${key}`] = {
          value: null,
          change: null,
          updated: null,
          config: cfg,
        };
      }
    }
  }

  // Drilling intelligence
  if (measures.drilling_intelligence?.enabled !== false && flags.all) {
    const di = measures.drilling_intelligence;
    if (di.rig_counts) {
      for (const [key, cfg] of Object.entries(di.rig_counts)) {
        if (cfg.enabled !== false) {
          drilling[`rig_${key}`] = { value: null, updated: null, config: cfg };
        }
      }
    }
    if (di.frac_spreads) {
      for (const [key, cfg] of Object.entries(di.frac_spreads)) {
        if (cfg.enabled !== false) {
          drilling[`frac_${key}`] = { value: null, updated: null, config: cfg };
        }
      }
    }
    if (di.duc_wells) {
      for (const [key, cfg] of Object.entries(di.duc_wells)) {
        if (cfg.enabled !== false) {
          drilling[`duc_${key}`] = { value: null, updated: null, config: cfg };
        }
      }
    }
  }
}

// Well permits state (separate from drilling for clarity)
const wellPermits = {
  summary: { total_7d: null, total_30d: null, active_states: null },
  topStates: [], // Top 5 states by 7d count
  lastUpdated: null,
};

// Set defaults if no config
if (!config.measures) {
  config.measures = {
    oil: {
      brent: { enabled: true, label: "Brent Crude", unit: "$", suffix: "/bbl" },
      wti: { enabled: true, label: "WTI Crude", unit: "$", suffix: "/bbl" },
    },
    natural_gas: {
      us: {
        enabled: true,
        label: "US Natural Gas",
        unit: "$",
        suffix: "/MMBtu",
      },
      uk: {
        enabled: true,
        label: "UK Natural Gas",
        unit: "",
        suffix: "p/therm",
      },
      eu: {
        enabled: true,
        label: "EU Natural Gas",
        unit: "€",
        suffix: "/MMBtu",
      },
    },
    drilling_intelligence: {
      enabled: true,
      rig_counts: {
        us_rigs: { enabled: true, label: "US Rig Count" },
        canada_rigs: { enabled: true, label: "Canada Rigs" },
        international_rigs: { enabled: true, label: "Intl Rigs" },
      },
      duc_wells: {
        permian: { enabled: true, label: "Permian DUC" },
        eagle_ford: { enabled: true, label: "Eagle Ford DUC" },
        bakken: { enabled: true, label: "Bakken DUC" },
      },
    },
  };
}

initPriceState();

// ANSI escape codes
const BOLD = "\x1b[1m";
const DIM = "\x1b[2m";
const RESET = "\x1b[0m";
const FG_CYAN = "\x1b[36m";
const FG_GREEN = "\x1b[32m";
const FG_RED = "\x1b[31m";
const FG_YELLOW = "\x1b[33m";
const FG_WHITE = "\x1b[97m";
const FG_GRAY = "\x1b[90m";
const FG_MAGENTA = "\x1b[35m";
const BG_GREEN = "\x1b[42m";
const BG_RED = "\x1b[41m";
const BG_YELLOW = "\x1b[43m";

// Helpers
function formatBytes(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(2) + " MB";
}

function formatUptime(ms) {
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return seconds + "s";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes + "m " + (seconds % 60) + "s";
  const hours = Math.floor(minutes / 60);
  return hours + "h " + (minutes % 60) + "m";
}

function timestamp() {
  return new Date().toISOString().substr(11, 12);
}

function addLog(msg, type = "info") {
  const ts = timestamp();
  logEntries.push(`[${ts}] ${msg}`);
  recentLogs.push({ ts, msg, type });
  if (recentLogs.length > MAX_LOG_LINES) {
    recentLogs.shift();
  }

  if (flags.scroll) {
    const colors = {
      info: FG_CYAN,
      error: FG_RED,
      warn: FG_YELLOW,
      price: FG_GREEN,
    };
    console.log(`${colors[type] || ""}[${ts}] ${msg}${RESET}`);
  }
}

function extractPriceValue(price) {
  if (!price) return null;
  if (typeof price.original_price === "number") return price.original_price;
  if (price.original_price?.cents !== undefined)
    return price.original_price.cents / 100;
  if (typeof price.normalized_price === "number") return price.normalized_price;
  if (price.normalized_price?.cents !== undefined)
    return price.normalized_price.cents / 100;
  return null;
}

function extractChangePercent(price) {
  if (!price) return null;
  const change = price.change_24h_percent ?? price.change_percent;
  if (typeof change === "number" && !isNaN(change)) return change;
  return null;
}

function updatePrices(data) {
  const priceData = data.prices || data;
  const now = new Date().toLocaleTimeString();

  // Update oil prices
  if (priceData.oil) {
    for (const [key, priceInfo] of Object.entries(priceData.oil)) {
      const stateKey = `oil_${key}`;
      if (prices[stateKey]) {
        const val = extractPriceValue(priceInfo);
        if (val !== null) {
          prices[stateKey].value = val;
          prices[stateKey].change = extractChangePercent(priceInfo);
          prices[stateKey].updated = now;
        }
      }
    }
  }

  // Update natural gas prices
  if (priceData.natural_gas) {
    for (const [key, priceInfo] of Object.entries(priceData.natural_gas)) {
      const stateKey = `gas_${key}`;
      if (prices[stateKey]) {
        const val = extractPriceValue(priceInfo);
        if (val !== null) {
          prices[stateKey].value = val;
          prices[stateKey].change = extractChangePercent(priceInfo);
          prices[stateKey].updated = now;
        }
      }
    }
  }

  // Update drilling intelligence
  if (data.drilling_intelligence && flags.all) {
    const di = data.drilling_intelligence;

    if (di.rig_counts) {
      for (const [key, info] of Object.entries(di.rig_counts)) {
        const stateKey = `rig_${key}`;
        if (drilling[stateKey] && info?.value !== undefined) {
          drilling[stateKey].value = info.value;
          drilling[stateKey].updated = now;
        }
      }
    }

    if (di.frac_spreads) {
      for (const [key, info] of Object.entries(di.frac_spreads)) {
        const stateKey = `frac_${key}`;
        if (drilling[stateKey] && info?.value !== undefined) {
          drilling[stateKey].value = info.value;
          drilling[stateKey].updated = now;
        }
      }
    }

    if (di.duc_wells) {
      for (const [key, info] of Object.entries(di.duc_wells)) {
        const stateKey = `duc_${key}`;
        if (drilling[stateKey] && info?.value !== undefined) {
          drilling[stateKey].value = info.value;
          drilling[stateKey].updated = now;
        }
      }
    }

    // Update well permits (new structure: summary + by_state)
    if (di.well_permits) {
      const wp = di.well_permits;
      if (wp.summary) {
        wellPermits.summary = {
          total_7d: wp.summary.total_permits_7d,
          total_30d: wp.summary.total_permits_30d,
          active_states: wp.summary.active_states,
        };
      }
      if (wp.by_state) {
        // Get all states by 7d count (sorted descending)
        wellPermits.topStates = Object.entries(wp.by_state)
          .map(([state, data]) => ({ state, count_7d: data.count_7d || 0 }))
          .sort((a, b) => b.count_7d - a.count_7d);
      }
      wellPermits.lastUpdated = wp.last_updated || now;
    }
  }
}

function formatPriceDisplay(label, price, unit = "$", suffix = "") {
  const labelStr = label.padEnd(16);
  if (price.value === null) {
    return `${FG_GRAY}${labelStr} ${"--".padEnd(14)}${RESET}          `;
  }
  const val = `${unit}${price.value.toFixed(2)}${suffix}`;
  let changeDisplay = "          ";
  if (typeof price.change === "number" && !isNaN(price.change)) {
    const color = price.change >= 0 ? FG_GREEN : FG_RED;
    const arrow = price.change >= 0 ? "▲" : "▼";
    changeDisplay = `${color}${arrow}${Math.abs(price.change).toFixed(2)}%${RESET}`;
  }
  return `${FG_WHITE}${labelStr}${RESET}${BOLD}${val.padEnd(14)}${RESET} ${changeDisplay}`;
}

function formatDrillingDisplay(label, data) {
  const labelStr = label.padEnd(16);
  if (data.value === null) {
    return `${FG_GRAY}${labelStr} --${RESET}`;
  }
  return `${FG_MAGENTA}${labelStr}${RESET}${BOLD}${data.value.toString().padEnd(10)}${RESET}`;
}

function getStatusBadge() {
  switch (connectionStatus) {
    case "connected":
      return `${BG_GREEN}${FG_WHITE} CONNECTED ${RESET}`;
    case "connecting":
      return `${BG_YELLOW}${FG_WHITE} CONNECTING ${RESET}`;
    default:
      return `${BG_RED}${FG_WHITE} DISCONNECTED ${RESET}`;
  }
}

function renderDisplay() {
  if (flags.scroll) return;

  const uptime = connectionStartTime
    ? formatUptime(Date.now() - connectionStartTime)
    : "--";
  const output = [];

  // Header
  output.push(
    `${BOLD}${FG_CYAN}╔═══════════════════════════════════════════════════════════╗${RESET}`,
  );
  output.push(
    `${BOLD}${FG_CYAN}║${RESET}  ${BOLD}OilPriceAPI WebSocket Tester${RESET}            ${getStatusBadge()}  ${BOLD}${FG_CYAN}║${RESET}`,
  );
  output.push(
    `${BOLD}${FG_CYAN}╚═══════════════════════════════════════════════════════════╝${RESET}`,
  );
  output.push("");

  // Connection info
  output.push(
    `${FG_GRAY}Endpoint:${RESET} ${baseUrl.startsWith("wss") ? "🔒" : "⚠️"} ${baseUrl}`,
  );
  output.push("");

  // Stats row
  output.push(
    `${BOLD}Stats${RESET}  ${FG_GRAY}│${RESET} Messages: ${FG_CYAN}${messageCount.toString().padStart(6)}${RESET}  ${FG_GRAY}│${RESET} Bytes: ${FG_CYAN}${formatBytes(bytesReceived).padStart(10)}${RESET}  ${FG_GRAY}│${RESET} Uptime: ${FG_CYAN}${uptime.padStart(8)}${RESET}  ${FG_GRAY}│${RESET} Pings: ${FG_CYAN}${pingCount.toString().padStart(4)}${RESET}`,
  );
  output.push("");

  // Prices section
  output.push(
    `${BOLD}${FG_WHITE}┌─────────────────────────────────────────────────────────┐${RESET}`,
  );
  output.push(
    `${BOLD}${FG_WHITE}│${RESET}                    ${BOLD}LIVE PRICES${RESET}                        ${BOLD}${FG_WHITE}│${RESET}`,
  );
  output.push(
    `${BOLD}${FG_WHITE}├─────────────────────────────────────────────────────────┤${RESET}`,
  );

  for (const [key, data] of Object.entries(prices)) {
    const cfg = data.config || {};
    const label = cfg.label || key;
    const unit = cfg.unit || "$";
    const suffix = cfg.suffix || "";
    output.push(
      `${BOLD}${FG_WHITE}│${RESET}  ${formatPriceDisplay(label, data, unit, suffix)}   ${BOLD}${FG_WHITE}│${RESET}`,
    );
  }

  output.push(
    `${BOLD}${FG_WHITE}└─────────────────────────────────────────────────────────┘${RESET}`,
  );

  // Drilling intelligence section (if --all flag)
  if (flags.all && Object.keys(drilling).length > 0) {
    output.push("");
    output.push(
      `${BOLD}${FG_WHITE}┌─────────────────────────────────────────────────────────┐${RESET}`,
    );
    output.push(
      `${BOLD}${FG_WHITE}│${RESET}              ${BOLD}DRILLING INTELLIGENCE${RESET}                   ${BOLD}${FG_WHITE}│${RESET}`,
    );
    output.push(
      `${BOLD}${FG_WHITE}├─────────────────────────────────────────────────────────┤${RESET}`,
    );

    for (const [key, data] of Object.entries(drilling)) {
      const cfg = data.config || {};
      const label = cfg.label || key;
      output.push(
        `${BOLD}${FG_WHITE}│${RESET}  ${formatDrillingDisplay(label, data).padEnd(55)}${BOLD}${FG_WHITE}│${RESET}`,
      );
    }

    output.push(
      `${BOLD}${FG_WHITE}└─────────────────────────────────────────────────────────┘${RESET}`,
    );
  }

  // Well Permits section (if --all flag and data available)
  if (flags.all && wellPermits.summary.total_7d !== null) {
    output.push("");
    output.push(
      `${BOLD}${FG_WHITE}┌─────────────────────────────────────────────────────────┐${RESET}`,
    );
    output.push(
      `${BOLD}${FG_WHITE}│${RESET}               ${BOLD}WELL PERMITS (26 States)${RESET}                ${BOLD}${FG_WHITE}│${RESET}`,
    );
    output.push(
      `${BOLD}${FG_WHITE}├─────────────────────────────────────────────────────────┤${RESET}`,
    );

    // Summary line
    const summary = wellPermits.summary;
    output.push(
      `${BOLD}${FG_WHITE}│${RESET}  ${FG_CYAN}National:${RESET} ${BOLD}${summary.total_7d}${RESET} (7d)  ${BOLD}${summary.total_30d}${RESET} (30d)  ${FG_GRAY}${summary.active_states} active states${RESET}   ${BOLD}${FG_WHITE}│${RESET}`,
    );

    output.push(
      `${BOLD}${FG_WHITE}│${RESET}  ${FG_GRAY}All states (7d):${RESET}                                     ${BOLD}${FG_WHITE}│${RESET}`,
    );

    // Top 5 states
    for (const { state, count_7d } of wellPermits.topStates) {
      const stateDisplay = `${FG_MAGENTA}${state}${RESET}: ${BOLD}${count_7d}${RESET}`;
      output.push(
        `${BOLD}${FG_WHITE}│${RESET}    ${stateDisplay.padEnd(60)}${BOLD}${FG_WHITE}│${RESET}`,
      );
    }

    output.push(
      `${BOLD}${FG_WHITE}└─────────────────────────────────────────────────────────┘${RESET}`,
    );
  }

  // Last update time
  const lastUpdate =
    Object.values(prices).find((p) => p.updated)?.updated || "--";
  output.push(`${FG_GRAY}Last update: ${lastUpdate}${RESET}`);
  output.push("");

  // Recent activity log
  output.push(`${BOLD}Recent Activity${RESET}`);
  output.push(`${FG_GRAY}${"─".repeat(59)}${RESET}`);
  const logColors = {
    info: FG_CYAN,
    error: FG_RED,
    warn: FG_YELLOW,
    price: FG_GREEN,
  };
  for (const entry of recentLogs) {
    output.push(
      `${logColors[entry.type] || ""}[${entry.ts}] ${entry.msg}${RESET}`,
    );
  }
  for (let i = recentLogs.length; i < MAX_LOG_LINES; i++) {
    output.push("");
  }

  output.push("");
  output.push(`${DIM}Press Ctrl+C to disconnect${RESET}`);

  logUpdate(output.join("\n"));
}

function startDisplay() {
  if (flags.scroll) return;
  renderDisplay();
  displayInterval = setInterval(renderDisplay, REFRESH_MS);
}

function stopDisplay() {
  if (displayInterval) {
    clearInterval(displayInterval);
    displayInterval = null;
  }
  if (!flags.scroll) {
    logUpdate.done();
  }
}

function exportLog() {
  const filename = `websocket-log-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}.txt`;
  const content = [
    "OilPriceAPI WebSocket Tester - Log Export",
    `Exported: ${new Date().toISOString()}`,
    `URL: ${baseUrl}`,
    `Messages: ${messageCount}`,
    `Bytes: ${formatBytes(bytesReceived)}`,
    `Uptime: ${connectionStartTime ? formatUptime(Date.now() - connectionStartTime) : "N/A"}`,
    "---",
    ...logEntries,
  ].join("\n");

  fs.writeFileSync(filename, content);
  return filename;
}

function getCloseReason(code) {
  const reasons = {
    1000: "Normal closure",
    1001: "Going away",
    1006: "Abnormal closure",
    4001: "Unauthorized - invalid API key",
    4003: "Forbidden - WebSocket not enabled",
  };
  return reasons[code] || `Code ${code}`;
}

function connect() {
  connectionStatus = "connecting";
  addLog(`Connecting to ${baseUrl}...`);

  if (flags.verbose) {
    addLog(
      `Protocol: ${baseUrl.startsWith("wss") ? "WSS (secure)" : "WS (insecure)"}`,
      "info",
    );
  }

  const connectStart = Date.now();
  ws = new WebSocket(url);

  connectionTimeout = setTimeout(() => {
    if (ws.readyState !== WebSocket.OPEN) {
      addLog("Connection timeout", "error");
      ws.terminate();
      handleReconnect();
    }
  }, CONNECTION_TIMEOUT_MS);

  ws.on("open", () => {
    clearTimeout(connectionTimeout);
    reconnectAttempts = 0;
    connectionStartTime = Date.now();
    connectionStatus = "connected";

    addLog(`Connected in ${Date.now() - connectStart}ms`, "info");
    addLog(`Subscribing to ${CHANNEL}...`, "info");

    ws.send(
      JSON.stringify({
        command: "subscribe",
        identifier: JSON.stringify({ channel: CHANNEL }),
      }),
    );
  });

  ws.on("message", (data) => {
    const dataStr = data.toString();
    bytesReceived += dataStr.length;

    try {
      const msg = JSON.parse(dataStr);

      if (msg.type === "ping") {
        pingCount++;
        if (lastPingTime && flags.verbose) {
          addLog(`Ping (interval: ${Date.now() - lastPingTime}ms)`);
        }
        lastPingTime = Date.now();
        if (flags.showPings) addLog(`Ping: ${msg.message}`);
        return;
      }

      messageCount++;

      if (msg.type === "welcome") {
        addLog("Server welcomed connection", "info");
        if (msg.data?.prices) {
          updatePrices(msg.data);
          addLog("Initial prices received", "price");
        }
        return;
      }

      if (msg.type === "confirm_subscription") {
        addLog(`Subscribed to ${CHANNEL}`, "info");
        return;
      }

      if (msg.type === "reject_subscription") {
        addLog("Subscription REJECTED", "error");
        addLog("WebSocket requires premium tier", "warn");
        return;
      }

      if (msg.message) {
        if (msg.message.prices || msg.message.data?.prices) {
          updatePrices(msg.message.data || msg.message);
        }
        if (flags.verbose) {
          addLog(
            `${msg.message.type || "update"}: ${JSON.stringify(msg.message).slice(0, 100)}...`,
            "price",
          );
        } else {
          addLog(`Price update received`, "price");
        }
      }
    } catch (err) {
      addLog(`Parse error: ${err.message}`, "error");
    }
  });

  ws.on("error", (err) => {
    clearTimeout(connectionTimeout);
    addLog(`Error: ${err.message}`, "error");
  });

  ws.on("close", (code) => {
    clearTimeout(connectionTimeout);
    connectionStatus = "disconnected";
    addLog(`Closed: ${getCloseReason(code)}`, code === 1000 ? "info" : "error");

    if (code !== 1000) handleReconnect();
  });
}

function handleReconnect() {
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    addLog("Max reconnect attempts reached", "error");
    stopDisplay();
    if (flags.export) exportLog();
    process.exit(1);
  }

  reconnectAttempts++;
  const delay = RECONNECT_BASE_DELAY_MS * Math.pow(2, reconnectAttempts - 1);
  addLog(
    `Reconnecting in ${delay / 1000}s (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})...`,
  );
  setTimeout(connect, delay);
}

// Start
if (flags.scroll) {
  console.log(`
╔═══════════════════════════════════════════╗
║   OilPriceAPI WebSocket Tester            ║
║   Press Ctrl+C to disconnect              ║
╚═══════════════════════════════════════════╝
`);
}

startDisplay();
connect();

// Graceful shutdown
process.on("SIGINT", () => {
  stopDisplay();
  console.log("\n");
  const uptime = connectionStartTime
    ? formatUptime(Date.now() - connectionStartTime)
    : "N/A";
  console.log(
    `${FG_CYAN}Final: Messages=${messageCount} Bytes=${formatBytes(bytesReceived)} Uptime=${uptime}${RESET}`,
  );

  clearTimeout(connectionTimeout);
  if (ws) ws.close(1000, "User disconnect");

  if (flags.export) {
    const file = exportLog();
    console.log(`Log exported: ${file}`);
  }

  process.exit(0);
});
