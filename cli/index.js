#!/usr/bin/env node
const WebSocket = require("ws");

// Configuration
const DEFAULT_URL = "wss://api.oilpriceapi.com/cable";
const CHANNEL = "EnergyPricesChannel";
const CONNECTION_TIMEOUT_MS = 30000;
const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_BASE_DELAY_MS = 1000;

// Parse arguments
const apiKey = process.argv[2];
const customUrl = process.env.OILPRICEAPI_WS_URL || DEFAULT_URL;

if (!apiKey) {
  console.error("Usage: node cli/index.js YOUR_API_KEY");
  console.error("");
  console.error("Environment variables:");
  console.error(
    "  OILPRICEAPI_WS_URL - Custom WebSocket URL (default: " +
      DEFAULT_URL +
      ")",
  );
  process.exit(1);
}

const url = `${customUrl}?token=${apiKey}`;
let ws = null;
let reconnectAttempts = 0;
let connectionTimeout = null;

function connect() {
  console.log(`Connecting to ${customUrl}...`);

  ws = new WebSocket(url);

  // Set connection timeout
  connectionTimeout = setTimeout(() => {
    if (ws.readyState !== WebSocket.OPEN) {
      console.error("Connection timeout after 30 seconds");
      ws.terminate();
      handleReconnect();
    }
  }, CONNECTION_TIMEOUT_MS);

  ws.on("open", () => {
    clearTimeout(connectionTimeout);
    reconnectAttempts = 0;
    console.log("Connected! Subscribing to " + CHANNEL + "...");
    ws.send(
      JSON.stringify({
        command: "subscribe",
        identifier: JSON.stringify({ channel: CHANNEL }),
      }),
    );
  });

  ws.on("message", (data) => {
    try {
      const msg = JSON.parse(data);
      if (msg.type === "ping") return;
      if (msg.type === "welcome") {
        console.log("Server welcomed connection");
        return;
      }
      if (msg.type === "confirm_subscription") {
        console.log(
          "Subscribed to " + CHANNEL + " - waiting for price updates...",
        );
        return;
      }
      if (msg.message) {
        console.log("\n--- Price Update ---");
        console.log(JSON.stringify(msg.message, null, 2));
      }
    } catch (err) {
      console.error("Failed to parse message:", err.message);
      console.error("Raw data:", data.toString().substring(0, 200));
    }
  });

  ws.on("error", (err) => {
    clearTimeout(connectionTimeout);
    console.error("Error:", err.message);
  });

  ws.on("close", (code, reason) => {
    clearTimeout(connectionTimeout);
    console.log(`Connection closed (code: ${code})`);
    handleReconnect();
  });
}

function handleReconnect() {
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    console.error(
      `Max reconnection attempts (${MAX_RECONNECT_ATTEMPTS}) reached. Exiting.`,
    );
    process.exit(1);
  }

  reconnectAttempts++;
  const delay = RECONNECT_BASE_DELAY_MS * Math.pow(2, reconnectAttempts - 1);
  console.log(
    `Reconnecting in ${delay / 1000}s (attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})...`,
  );

  setTimeout(connect, delay);
}

// Start connection
connect();

process.on("SIGINT", () => {
  console.log("\nDisconnecting...");
  clearTimeout(connectionTimeout);
  if (ws) ws.close();
  process.exit(0);
});
