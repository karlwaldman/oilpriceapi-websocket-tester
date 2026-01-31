#!/usr/bin/env python3
"""OilPriceAPI WebSocket Tester - Python CLI"""

import os
import sys
import json
import time
import argparse
import threading
from datetime import datetime

try:
    import websocket
except ImportError:
    print("Error: websocket-client not installed")
    print("Run: pip install websocket-client")
    sys.exit(1)

# Configuration
PROD_URL = "wss://api.oilpriceapi.com/cable"
LOCAL_URL = "ws://localhost:5000/cable"
CHANNEL = "EnergyPricesChannel"
CONNECTION_TIMEOUT_SEC = 30
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_BASE_DELAY_SEC = 1
MAX_LOG_LINES = 8

# Global state
reconnect_attempts = 0
connection_start_time = None
message_count = 0
bytes_received = 0
last_ping_time = None
ping_count = 0
connection_status = "disconnected"
log_entries = []
recent_logs = []
display_thread = None
display_running = False
args = None

# Price state
prices = {
    "brent": {"value": None, "change": None, "updated": None},
    "wti": {"value": None, "change": None, "updated": None},
    "natgas_us": {"value": None, "change": None, "updated": None},
    "natgas_uk": {"value": None, "change": None, "updated": None},
}

# Drilling intelligence state
drilling = {
    "rig_us": {"value": None, "label": "US Rig Count"},
    "rig_canada": {"value": None, "label": "Canada Rigs"},
    "rig_intl": {"value": None, "label": "Intl Rigs"},
    "frac_permian": {"value": None, "label": "Permian Frac"},
    "frac_eagle_ford": {"value": None, "label": "Eagle Ford Frac"},
    "frac_bakken": {"value": None, "label": "Bakken Frac"},
    "duc_permian": {"value": None, "label": "Permian DUC"},
    "duc_eagle_ford": {"value": None, "label": "Eagle Ford DUC"},
    "duc_bakken": {"value": None, "label": "Bakken DUC"},
}

# Well permits state (new structure)
well_permits = {
    "summary": {"total_7d": None, "total_30d": None, "active_states": None},
    "top_states": [],  # Top 5 states by 7d count
    "last_updated": None,
}


# ANSI codes
class C:
    CLEAR = '\033[2J'
    HOME = '\033[H'
    HIDE_CURSOR = '\033[?25l'
    SHOW_CURSOR = '\033[?25h'
    ALT_SCREEN_ON = '\033[?1049h'
    ALT_SCREEN_OFF = '\033[?1049l'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    WHITE = '\033[97m'
    GRAY = '\033[90m'
    BG_GREEN = '\033[42m'
    BG_RED = '\033[41m'
    BG_YELLOW = '\033[43m'


def format_bytes(b):
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b / (1024 * 1024):.2f} MB"


def format_uptime(seconds):
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m {int(seconds % 60)}s"
    hours = int(minutes // 60)
    return f"{hours}h {minutes % 60}m"


def timestamp():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def add_log(msg, level="info"):
    ts = timestamp()
    log_entries.append(f"[{ts}] {msg}")
    recent_logs.append({"ts": ts, "msg": msg, "level": level})
    if len(recent_logs) > MAX_LOG_LINES:
        recent_logs.pop(0)

    # For scroll mode, print immediately
    if args and args.scroll:
        colors = {
            "info": C.CYAN,
            "error": C.RED,
            "warn": C.YELLOW,
            "price": C.GREEN,
        }
        print(f"{colors.get(level, '')}[{ts}] {msg}{C.RESET}")


def extract_price_value(price, use_original=True):
    if not price:
        return None

    # Prefer original_price (actual market price in native units like $/barrel)
    # over normalized_price (converted to $/MMBtu for energy comparison)
    if use_original:
        # Handle original_price as direct number (already in dollars from API)
        if isinstance(price.get("original_price"), (int, float)):
            return price["original_price"]
        # Handle Money object: {cents: 7234, currency_iso: "USD"}
        if isinstance(price.get("original_price"), dict):
            cents = price["original_price"].get("cents")
            if cents is not None:
                return cents / 100

    # Fallback to normalized_price
    if isinstance(price.get("normalized_price"), (int, float)):
        return price["normalized_price"]
    if isinstance(price.get("normalized_price"), dict):
        cents = price["normalized_price"].get("cents")
        if cents is not None:
            return cents / 100

    return None


def extract_change_percent(price):
    if not price:
        return None
    # API returns change_24h_percent, not change_percent
    change = price.get("change_24h_percent") or price.get("change_percent")
    if isinstance(change, (int, float)) and change == change:  # check not NaN
        return change
    return None


def update_prices(data):
    price_data = data.get("prices", data)
    now = datetime.now().strftime("%H:%M:%S")

    if price_data.get("oil", {}).get("brent"):
        val = extract_price_value(price_data["oil"]["brent"])
        if val is not None:
            prices["brent"] = {
                "value": val,
                "change": extract_change_percent(price_data["oil"]["brent"]),
                "updated": now,
            }
    if price_data.get("oil", {}).get("wti"):
        val = extract_price_value(price_data["oil"]["wti"])
        if val is not None:
            prices["wti"] = {
                "value": val,
                "change": extract_change_percent(price_data["oil"]["wti"]),
                "updated": now,
            }
    if price_data.get("natural_gas", {}).get("us"):
        val = extract_price_value(price_data["natural_gas"]["us"])
        if val is not None:
            prices["natgas_us"] = {
                "value": val,
                "change": extract_change_percent(price_data["natural_gas"]["us"]),
                "updated": now,
            }
    if price_data.get("natural_gas", {}).get("uk"):
        val = extract_price_value(price_data["natural_gas"]["uk"])
        if val is not None:
            prices["natgas_uk"] = {
                "value": val,
                "change": extract_change_percent(price_data["natural_gas"]["uk"]),
                "updated": now,
            }

    # Update drilling intelligence
    di = data.get("drilling_intelligence", {})
    if di:
        # Rig counts
        if di.get("rig_counts"):
            rc = di["rig_counts"]
            if rc.get("us_rigs", {}).get("value") is not None:
                drilling["rig_us"]["value"] = rc["us_rigs"]["value"]
            if rc.get("canada_rigs", {}).get("value") is not None:
                drilling["rig_canada"]["value"] = rc["canada_rigs"]["value"]
            if rc.get("international_rigs", {}).get("value") is not None:
                drilling["rig_intl"]["value"] = rc["international_rigs"]["value"]

        # Frac spreads
        if di.get("frac_spreads"):
            fs = di["frac_spreads"]
            if fs.get("permian", {}).get("value") is not None:
                drilling["frac_permian"]["value"] = fs["permian"]["value"]
            if fs.get("eagle_ford", {}).get("value") is not None:
                drilling["frac_eagle_ford"]["value"] = fs["eagle_ford"]["value"]
            if fs.get("bakken", {}).get("value") is not None:
                drilling["frac_bakken"]["value"] = fs["bakken"]["value"]

        # DUC wells
        if di.get("duc_wells"):
            duc = di["duc_wells"]
            if duc.get("permian", {}).get("value") is not None:
                drilling["duc_permian"]["value"] = duc["permian"]["value"]
            if duc.get("eagle_ford", {}).get("value") is not None:
                drilling["duc_eagle_ford"]["value"] = duc["eagle_ford"]["value"]
            if duc.get("bakken", {}).get("value") is not None:
                drilling["duc_bakken"]["value"] = duc["bakken"]["value"]

        # Well permits (new structure with summary + by_state)
        if di.get("well_permits"):
            wp = di["well_permits"]
            if wp.get("summary"):
                well_permits["summary"] = {
                    "total_7d": wp["summary"].get("total_permits_7d"),
                    "total_30d": wp["summary"].get("total_permits_30d"),
                    "active_states": wp["summary"].get("active_states"),
                }
            if wp.get("by_state"):
                # Get all states by 7d count (sorted descending)
                states = [(state, (data.get("count_7d", 0) if data else 0)) for state, data in wp["by_state"].items()]
                states.sort(key=lambda x: x[1], reverse=True)
                well_permits["top_states"] = states
            well_permits["last_updated"] = wp.get("last_updated", now)


def format_price_display(label, price, unit="$", suffix=""):
    if price["value"] is None:
        return f"{C.GRAY}{label:<16} {'--':<14} {'':10}{C.RESET}"
    val = f"{unit}{price['value']:.2f}{suffix}"
    change = price.get("change")
    change_str = ""
    padding = "          "
    if change is not None and isinstance(change, (int, float)) and not (change != change):  # check for NaN
        change_color = C.GREEN if change >= 0 else C.RED
        arrow = "▲" if change >= 0 else "▼"
        change_str = f"{change_color}{arrow}{abs(change):.2f}%{C.RESET}"
        padding = ""
    return f"{C.WHITE}{label:<16}{C.RESET}{C.BOLD}{val:<14}{C.RESET} {change_str}{padding}"


def get_status_badge():
    if connection_status == "connected":
        return f"{C.BG_GREEN}{C.WHITE} CONNECTED {C.RESET}"
    elif connection_status == "connecting":
        return f"{C.BG_YELLOW}{C.WHITE} CONNECTING {C.RESET}"
    else:
        return f"{C.BG_RED}{C.WHITE} DISCONNECTED {C.RESET}"


def render_display():
    if args and args.scroll:
        return

    uptime = format_uptime(time.time() - connection_start_time) if connection_start_time else "--"
    lines = []

    # Move cursor home and clear from there to end of screen
    sys.stdout.write("\033[H\033[J")

    # Header
    lines.append(f"{C.BOLD}{C.CYAN}╔═══════════════════════════════════════════════════════════╗{C.RESET}")
    lines.append(f"{C.BOLD}{C.CYAN}║{C.RESET}  {C.BOLD}OilPriceAPI WebSocket Tester{C.RESET}            {get_status_badge()}  {C.BOLD}{C.CYAN}║{C.RESET}")
    lines.append(f"{C.BOLD}{C.CYAN}╚═══════════════════════════════════════════════════════════╝{C.RESET}")
    lines.append("")

    # Connection info
    url = args.url if args else PROD_URL
    lock_icon = "🔒" if url.startswith("wss") else "⚠️"
    lines.append(f"{C.GRAY}Endpoint:{C.RESET} {lock_icon} {url}")
    lines.append("")

    # Stats row
    lines.append(f"{C.BOLD}Stats{C.RESET}  {C.GRAY}│{C.RESET} Messages: {C.CYAN}{message_count:>6}{C.RESET}  {C.GRAY}│{C.RESET} Bytes: {C.CYAN}{format_bytes(bytes_received):>10}{C.RESET}  {C.GRAY}│{C.RESET} Uptime: {C.CYAN}{uptime:>8}{C.RESET}  {C.GRAY}│{C.RESET} Pings: {C.CYAN}{ping_count:>4}{C.RESET}")
    lines.append("")

    # Prices section
    lines.append(f"{C.BOLD}{C.WHITE}┌─────────────────────────────────────────────────────────┐{C.RESET}")
    lines.append(f"{C.BOLD}{C.WHITE}│{C.RESET}                    {C.BOLD}LIVE PRICES{C.RESET}                        {C.BOLD}{C.WHITE}│{C.RESET}")
    lines.append(f"{C.BOLD}{C.WHITE}├─────────────────────────────────────────────────────────┤{C.RESET}")
    lines.append(f"{C.BOLD}{C.WHITE}│{C.RESET}  {format_price_display('Brent Crude', prices['brent'])}      {C.BOLD}{C.WHITE}│{C.RESET}")
    lines.append(f"{C.BOLD}{C.WHITE}│{C.RESET}  {format_price_display('WTI Crude', prices['wti'])}      {C.BOLD}{C.WHITE}│{C.RESET}")
    lines.append(f"{C.BOLD}{C.WHITE}│{C.RESET}  {format_price_display('US Natural Gas', prices['natgas_us'], '$', '/MMBtu')}      {C.BOLD}{C.WHITE}│{C.RESET}")
    lines.append(f"{C.BOLD}{C.WHITE}│{C.RESET}  {format_price_display('UK Natural Gas', prices['natgas_uk'], '', 'p/therm')}      {C.BOLD}{C.WHITE}│{C.RESET}")
    lines.append(f"{C.BOLD}{C.WHITE}└─────────────────────────────────────────────────────────┘{C.RESET}")

    # Drilling Intelligence section (if --all flag and data available)
    has_drilling_data = any(d["value"] is not None for d in drilling.values())
    if args and args.all and has_drilling_data:
        lines.append("")
        lines.append(f"{C.BOLD}{C.WHITE}┌─────────────────────────────────────────────────────────┐{C.RESET}")
        lines.append(f"{C.BOLD}{C.WHITE}│{C.RESET}              {C.BOLD}DRILLING INTELLIGENCE{C.RESET}                   {C.BOLD}{C.WHITE}│{C.RESET}")
        lines.append(f"{C.BOLD}{C.WHITE}├─────────────────────────────────────────────────────────┤{C.RESET}")
        for key, data in drilling.items():
            if data["value"] is not None:
                label = data.get("label", key)
                val_str = f"{data['value']}"
                lines.append(f"{C.BOLD}{C.WHITE}│{C.RESET}  {C.CYAN}{label:<16}{C.RESET}{C.BOLD}{val_str:<10}{C.RESET}                             {C.BOLD}{C.WHITE}│{C.RESET}")
        lines.append(f"{C.BOLD}{C.WHITE}└─────────────────────────────────────────────────────────┘{C.RESET}")

    # Well Permits section (if --all flag and data available)
    if args and args.all and well_permits["summary"]["total_7d"] is not None:
        lines.append("")
        lines.append(f"{C.BOLD}{C.WHITE}┌─────────────────────────────────────────────────────────┐{C.RESET}")
        lines.append(f"{C.BOLD}{C.WHITE}│{C.RESET}               {C.BOLD}WELL PERMITS (26 States){C.RESET}                {C.BOLD}{C.WHITE}│{C.RESET}")
        lines.append(f"{C.BOLD}{C.WHITE}├─────────────────────────────────────────────────────────┤{C.RESET}")
        summary = well_permits["summary"]
        lines.append(f"{C.BOLD}{C.WHITE}│{C.RESET}  {C.CYAN}National:{C.RESET} {C.BOLD}{summary['total_7d']}{C.RESET} (7d)  {C.BOLD}{summary['total_30d']}{C.RESET} (30d)  {C.GRAY}{summary['active_states']} states{C.RESET}    {C.BOLD}{C.WHITE}│{C.RESET}")
        lines.append(f"{C.BOLD}{C.WHITE}│{C.RESET}  {C.GRAY}All states (7d):{C.RESET}                                     {C.BOLD}{C.WHITE}│{C.RESET}")
        for state, count in well_permits["top_states"]:
            lines.append(f"{C.BOLD}{C.WHITE}│{C.RESET}    {C.CYAN}{state}{C.RESET}: {C.BOLD}{count}{C.RESET}                                            {C.BOLD}{C.WHITE}│{C.RESET}")
        lines.append(f"{C.BOLD}{C.WHITE}└─────────────────────────────────────────────────────────┘{C.RESET}")

    # Last update time
    last_update = prices["brent"]["updated"] or prices["wti"]["updated"] or prices["natgas_us"]["updated"] or "--"
    lines.append(f"{C.GRAY}Last update: {last_update}{C.RESET}")
    lines.append("")

    # Recent activity log
    lines.append(f"{C.BOLD}Recent Activity{C.RESET}")
    lines.append(f"{C.GRAY}{'─' * 59}{C.RESET}")
    log_colors = {
        "info": C.CYAN,
        "error": C.RED,
        "warn": C.YELLOW,
        "price": C.GREEN,
    }
    for entry in recent_logs:
        color = log_colors.get(entry["level"], "")
        lines.append(f"{color}[{entry['ts']}] {entry['msg']}{C.RESET}")
    # Pad empty lines
    for _ in range(MAX_LOG_LINES - len(recent_logs)):
        lines.append("")

    lines.append("")
    lines.append(f"{C.DIM}Press Ctrl+C to disconnect{C.RESET}")

    sys.stdout.write("\n".join(lines))
    sys.stdout.flush()


def display_loop():
    global display_running
    while display_running:
        render_display()
        time.sleep(0.5)


def start_display():
    global display_thread, display_running
    if args and args.scroll:
        return
    # Use alternate screen buffer (like vim/less)
    sys.stdout.write(C.ALT_SCREEN_ON + C.HIDE_CURSOR)
    sys.stdout.flush()
    display_running = True
    display_thread = threading.Thread(target=display_loop, daemon=True)
    display_thread.start()


def stop_display():
    global display_running
    display_running = False
    if not (args and args.scroll):
        # Exit alternate screen buffer and show cursor
        sys.stdout.write(C.SHOW_CURSOR + C.ALT_SCREEN_OFF)
        sys.stdout.flush()


def export_log():
    filename = f"websocket-log-{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}.txt"
    uptime = format_uptime(time.time() - connection_start_time) if connection_start_time else "N/A"
    content = "\n".join([
        "OilPriceAPI WebSocket Tester - Log Export",
        f"Exported: {datetime.now().isoformat()}",
        f"URL: {args.url}",
        f"Messages: {message_count}",
        f"Bytes: {format_bytes(bytes_received)}",
        f"Uptime: {uptime}",
        "---",
        *log_entries
    ])
    with open(filename, "w") as f:
        f.write(content)
    return filename


def get_close_reason(code):
    reasons = {
        1000: "Normal closure",
        1001: "Going away",
        1002: "Protocol error",
        1003: "Unsupported data",
        1006: "Abnormal closure (no close frame)",
        1007: "Invalid payload",
        1008: "Policy violation",
        1009: "Message too big",
        1011: "Server error",
        1015: "TLS handshake failed",
        4001: "Unauthorized - invalid API key",
        4003: "Forbidden - WebSocket access not enabled",
    }
    return reasons.get(code, "Unknown")


def on_message(ws, message):
    global message_count, bytes_received, last_ping_time, ping_count

    bytes_received += len(message)

    try:
        msg = json.loads(message)

        if msg.get("type") == "ping":
            ping_count += 1
            if last_ping_time and args.verbose:
                interval = (time.time() - last_ping_time) * 1000
                add_log(f"Ping received (interval: {interval:.0f}ms)")
            last_ping_time = time.time()
            if args.pings:
                add_log(f"Ping: {msg.get('message')}")
            return

        message_count += 1

        if msg.get("type") == "welcome":
            add_log("Server welcomed connection")
            # Welcome message includes initial price data
            try:
                welcome_data = msg.get("data") or {}
                if isinstance(welcome_data, dict) and welcome_data.get("prices"):
                    update_prices(welcome_data)
                    add_log("Initial prices received", "price")
            except Exception as e:
                if args.verbose:
                    add_log(f"Error processing welcome data: {e}", "error")
            return

        if msg.get("type") == "confirm_subscription":
            add_log(f"Subscribed to {CHANNEL}")
            add_log("Waiting for price updates...")
            return

        if msg.get("type") == "reject_subscription":
            add_log("Subscription REJECTED", "error")
            add_log("WebSocket requires Reservoir Mastery tier", "warn")
            return

        if "message" in msg:
            msg_type = msg["message"].get("type", "update")

            # Update price state
            try:
                msg_data = msg["message"].get("data") or {}
                if msg["message"].get("prices") or (isinstance(msg_data, dict) and msg_data.get("prices")):
                    update_prices(msg_data if msg_data.get("prices") else msg["message"])
            except Exception as e:
                if args.verbose:
                    add_log(f"Error processing prices: {e}", "error")

            if args.verbose:
                add_log(f"{msg_type}: {json.dumps(msg['message'])}", "price")
            else:
                add_log(f"Price update received ({msg_type})", "price")

    except json.JSONDecodeError as e:
        add_log(f"Failed to parse message: {e}", "error")
        if args.verbose:
            add_log(f"Raw: {message[:100]}...", "warn")


def on_open(ws):
    global reconnect_attempts, connection_start_time, connection_status

    reconnect_attempts = 0
    connection_start_time = time.time()
    connection_status = "connected"

    add_log("Connected!")
    add_log(f"Subscribing to {CHANNEL}...")

    ws.send(json.dumps({
        "command": "subscribe",
        "identifier": json.dumps({"channel": CHANNEL})
    }))


def on_error(ws, error):
    add_log(f"Error: {error}", "error")


def on_close(ws, close_status_code, close_msg):
    global connection_status
    connection_status = "disconnected"
    reason = get_close_reason(close_status_code)
    level = "info" if close_status_code == 1000 else "error"
    add_log(f"Connection closed: {close_status_code} - {reason}", level)

    if close_status_code in (4001, 4003, 1006):
        add_log("Check API key and tier level", "warn")

    if close_status_code != 1000:
        handle_reconnect()


def handle_reconnect():
    global reconnect_attempts

    if reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
        add_log("Max reconnection attempts reached. Exiting.", "error")
        stop_display()
        if args.export:
            export_log()
        sys.exit(1)

    reconnect_attempts += 1
    delay = RECONNECT_BASE_DELAY_SEC * (2 ** (reconnect_attempts - 1))
    add_log(f"Reconnecting in {delay}s ({reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS})...")

    time.sleep(delay)
    run_websocket()


def run_websocket():
    global connection_status
    connection_status = "connecting"
    add_log(f"Connecting to {args.url}...")

    if args.verbose:
        protocol = "WSS (secure)" if args.url.startswith("wss") else "WS (insecure)"
        add_log(f"Protocol: {protocol}")
        add_log(f"Python: {sys.version.split()[0]}")

    ws = websocket.WebSocketApp(
        f"{args.url}?token={args.api_key}",
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    ws.run_forever(
        ping_interval=60,
        ping_timeout=10
    )


def main():
    global args

    parser = argparse.ArgumentParser(
        description="OilPriceAPI WebSocket Tester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tester.py abc123                    # Connect to production
  python tester.py abc123 --local            # Connect to localhost
  python tester.py abc123 -v -p              # Verbose mode with pings
  python tester.py abc123 --export           # Export log on Ctrl+C
  python tester.py abc123 --scroll           # Classic scrolling output
        """
    )
    parser.add_argument("api_key", help="Your OilPriceAPI key")
    parser.add_argument("-l", "--local", action="store_true", help="Use localhost:5000")
    parser.add_argument("-a", "--all", action="store_true", help="Show all measures (drilling data, well permits)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed info")
    parser.add_argument("-p", "--pings", action="store_true", help="Show ping messages")
    parser.add_argument("-e", "--export", action="store_true", help="Export log on exit")
    parser.add_argument("-s", "--scroll", action="store_true", help="Classic scrolling output")
    parser.add_argument("--url", help="Custom WebSocket URL")

    args = parser.parse_args()

    # Determine URL
    if args.url:
        pass  # Use provided URL
    elif os.environ.get("OILPRICEAPI_WS_URL"):
        args.url = os.environ["OILPRICEAPI_WS_URL"]
    elif args.local:
        args.url = LOCAL_URL
    else:
        args.url = PROD_URL

    if args.scroll:
        print("""
╔═══════════════════════════════════════════╗
║   OilPriceAPI WebSocket Tester            ║
║   Press Ctrl+C to disconnect              ║
╚═══════════════════════════════════════════╝
        """)

    try:
        start_display()
        run_websocket()
    except KeyboardInterrupt:
        stop_display()
        print()
        if connection_start_time:
            uptime = format_uptime(time.time() - connection_start_time)
            print(f"{C.CYAN}Final stats: Messages={message_count} Bytes={format_bytes(bytes_received)} Uptime={uptime}{C.RESET}")
        if args.export:
            filename = export_log()
            print(f"Log exported to: {filename}")


if __name__ == "__main__":
    main()
