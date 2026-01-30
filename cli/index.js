#!/usr/bin/env node
const WebSocket = require("ws");

const apiKey = process.argv[2];
if (!apiKey) {
  console.error("Usage: node cli/index.js YOUR_API_KEY");
  process.exit(1);
}

const url = `wss://api.oilpriceapi.com/cable?token=${apiKey}`;
console.log("Connecting to OilPriceAPI WebSocket...");

const ws = new WebSocket(url);

ws.on("open", () => {
  console.log("Connected! Subscribing to EnergyPricesChannel...");
  ws.send(
    JSON.stringify({
      command: "subscribe",
      identifier: JSON.stringify({ channel: "EnergyPricesChannel" }),
    }),
  );
});

ws.on("message", (data) => {
  const msg = JSON.parse(data);
  if (msg.type === "ping") return;
  if (msg.type === "welcome") {
    console.log("Server welcomed connection");
    return;
  }
  if (msg.type === "confirm_subscription") {
    console.log(
      "Subscribed to EnergyPricesChannel - waiting for price updates...",
    );
    return;
  }
  if (msg.message) {
    console.log("\n--- Price Update ---");
    console.log(JSON.stringify(msg.message, null, 2));
  }
});

ws.on("error", (err) => console.error("Error:", err.message));
ws.on("close", () => console.log("Connection closed"));

process.on("SIGINT", () => {
  ws.close();
  process.exit(0);
});
