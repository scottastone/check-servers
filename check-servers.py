#!/home/scott/code/projects/check-servers/.venv/bin/python3

"""
A script to check the status of local and remote servers using ICMP pings.
Replicates the functionality of check-servers.sh with a rich UI.
"""

import argparse
from dataclasses import dataclass
import re
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Dict

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn

# ==========================================
# CONFIGURATION
# ==========================================
USER_CONFIG_DIR = Path.home() / ".config/check-servers"
USER_CONFIG_FILE = USER_CONFIG_DIR / "servers.conf"
SYSTEM_CONFIG_FILE = Path("/etc/check-servers/servers.conf")

# ==========================================
# DATA CLASSES & FUNCTIONS
# ==========================================

@dataclass
class Server:
    ip: str
    name: str
    type: str

@dataclass
class PingResult:
    server: Server
    status: str
    latency: Optional[float] = None

def find_config_file() -> Optional[Path]:
    """Finds the configuration file in user or system paths."""
    if USER_CONFIG_FILE.exists():
        return USER_CONFIG_FILE
    if SYSTEM_CONFIG_FILE.exists():
        return SYSTEM_CONFIG_FILE
    return None

def parse_config(config_file: Path) -> (Dict, List[Server]):
    """Parses the server configuration file."""
    settings = {
        'timeout': 0.2,
        'retries': 3,
    }
    servers = []
    current_section = None
    with open(config_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            if line.startswith('[') and line.endswith(']'):
                current_section = line[1:-1]
                continue
            
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                if key in settings:
                    settings[key] = float(value.strip()) if '.' in value else int(value.strip())
            elif current_section in ['local', 'remote']:
                parts = line.split(maxsplit=1)
                if len(parts) >= 2:
                    ip = parts[0]
                    name = parts[1]
                    servers.append(Server(ip=ip, name=name, type=current_section))

    return settings, servers

def ping_server(server: Server, timeout: float, retries: int) -> PingResult:
    """Pings a server with retries and returns a result object."""
    for _ in range(retries):
        # Construct the ping command.
        # -c 1: Send only one packet.
        # -W <timeout>: Wait for a reply for <timeout> seconds.
        command = ["ping", "-c", "1", f"-W{timeout}", server.ip]
        
        result = subprocess.run(command, capture_output=True, text=True)
        
        # A return code of 0 means the ping was successful.
        if result.returncode == 0:
            # Use regex to find the time from the output, e.g., "time=0.523 ms"
            match = re.search(r"time=([\d.]+)\s*ms", result.stdout)
            if match:
                latency = float(match.group(1))
                return PingResult(server=server, status="OK", latency=latency)
        
        # If ping fails (non-zero return code or no match), the loop continues to the next retry.
        
    return PingResult(server=server, status="DOWN")

def main():
    """Main script execution."""
    parser = argparse.ArgumentParser(description="Check the status of local and remote servers.")
    parser.add_argument("-l", "--local", action="store_true", help="Check local servers only.")
    parser.add_argument("-r", "--remote", action="store_true", help="Check remote servers only.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Only show servers that are down.")
    args = parser.parse_args()

    console = Console()
    config_file = find_config_file()
    if not config_file:
        console.print("[bold red]Error:[/bold red] Configuration file not found.", style="error")
        return

    settings, all_servers = parse_config(config_file)

    # Filter servers based on arguments
    if args.local:
        servers_to_check = [s for s in all_servers if s.type == 'local']
    elif args.remote:
        servers_to_check = [s for s in all_servers if s.type == 'remote']
    else:
        servers_to_check = all_servers

    if not servers_to_check:
        console.print("[yellow]No servers to check.[/yellow]")
        return

    results: Dict[str, PingResult] = {}
    progress = Progress(SpinnerColumn(), BarColumn(), TextColumn("[progress.percentage]{task.percentage:>3.0f}%"), transient=True)

    with Live(progress, console=console):
        with ThreadPoolExecutor() as executor:
            task = progress.add_task("Pinging servers...", total=len(servers_to_check))
            future_to_server = {
                executor.submit(ping_server, s, settings['timeout'], settings['retries']): s for s in servers_to_check
            }
            for future in as_completed(future_to_server):
                res = future.result()
                results[res.server.name] = res
                progress.update(task, advance=1)

    # --- Build and print the results table ---
    table = Table(title="Server Status")
    table.add_column("SERVER", style="cyan", no_wrap=True)
    table.add_column("ADDRESS", style="magenta")
    table.add_column("TYPE", style="blue")
    table.add_column("STATUS", justify="center")
    table.add_column("TIME (ms)", justify="right", style="green")

    up_count, down_count = 0, 0
    total_latency = 0

    for server in servers_to_check:
        res = results.get(server.name)
        if not res: continue

        if res.status == "OK":
            up_count += 1
            total_latency += res.latency
            status_style = "[green]OK[/green]"
            latency_str = f"{res.latency:.2f}"
            if not args.quiet:
                table.add_row(res.server.name, res.server.ip, res.server.type, status_style, latency_str)
        else:
            down_count += 1
            status_style = "[red]DOWN[/red]"
            table.add_row(res.server.name, res.server.ip, res.server.type, status_style, "--")

    console.print(table)
    avg_latency = (total_latency / up_count) if up_count > 0 else 0
    console.print(f"STATS: [green]{up_count}/{len(servers_to_check)} Online[/] | [red]{down_count} Down[/] | Avg Latency: {avg_latency:.2f}ms")

if __name__ == "__main__":
    main()