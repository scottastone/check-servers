"""
Core library for checking the status of local and remote servers.
"""

import argparse
from dataclasses import dataclass
import re
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Dict, Tuple, Any
import sys

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn


USER_CONFIG_DIR = Path.home() / ".config/check-servers"
USER_CONFIG_FILE = USER_CONFIG_DIR / "servers.conf"
SYSTEM_CONFIG_FILE = Path("/etc/check-servers/servers.conf")

# Status constants
STATUS_OK = "OK"
STATUS_DOWN = "DOWN"

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
    latency: Optional[float] = None # in ms

def find_config_file() -> Optional[Path]:
    """Finds the configuration file in user or system paths."""
    if USER_CONFIG_FILE.exists():
        return USER_CONFIG_FILE
    if SYSTEM_CONFIG_FILE.exists():
        return SYSTEM_CONFIG_FILE
    return None

def parse_config(config_file: Path) -> Tuple[Dict[str, Any], List[Server]]:
    """Parses the server configuration file."""
    settings: Dict[str, Any] = {
        'timeout': 0.2,
        'retries': 3,
    }
    servers = []
    current_section = None
    try:
        with open(config_file, 'r') as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                if line.startswith('[') and line.endswith(']'):
                    current_section = line[1:-1]
                    continue

                if '=' in line:
                    parts = line.split('=', 1)
                    if len(parts) != 2: continue
                    key, value = parts[0].strip(), parts[1].strip()
                    if key in settings:
                        try:
                            settings[key] = float(value) if '.' in value else int(value)
                        except ValueError:
                            # Silently ignore malformed settings, or print a warning
                            # print(f"Warning: Invalid value for '{key}' on line {i} in {config_file}")
                            pass
                elif current_section in ['local', 'remote']:
                    parts = line.split(maxsplit=1)
                    if len(parts) >= 2:
                        ip, name = parts[0], parts[1]
                        servers.append(Server(ip=ip, name=name, type=current_section))
    except IOError as e:
        # This provides a more specific error if the file is unreadable
        raise IOError(f"Error reading configuration file {config_file}: {e}") from e

    return settings, servers

def add_server_to_config(ip: str, name: str, server_type: str, console: Console):
    """Adds a new server to the user's configuration file."""
    config_file = find_config_file()
    # If no config file exists, default to the user config file.
    if not config_file:
        config_file = USER_CONFIG_FILE
        console.print(f"No config file found. Creating a new one at [cyan]{config_file}[/cyan].")
        # Ensure the directory exists
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config_file.touch()

    # We should only add to the user's config file, not the system-wide one.
    if str(config_file) == str(SYSTEM_CONFIG_FILE):
        console.print(f"[bold red]Error:[/bold red] Cannot add server to system-wide config at [cyan]{SYSTEM_CONFIG_FILE}[/cyan].")
        console.print("Please create a user config file at [cyan]~/.config/check-servers/servers.conf[/cyan].")
        return

    new_entry = f"{ip:<15} {name}\n"
    
    with open(config_file, "r+") as f:
        content = f.read()
        section_header = f"[{server_type}]"
        if section_header in content:
            # Find the section and append the server
            content = content.replace(section_header, f"{section_header}\n{new_entry}", 1)
        else:
            # Add the section and the server at the end of the file
            content += f"\n{section_header}\n{new_entry}"
        f.seek(0)
        f.write(content)
    
    console.print(f"Successfully added server [bold cyan]{name}[/bold cyan] ([green]{ip}[/green]) to [magenta]{config_file}[/magenta].")

def remove_server_from_config(console: Console):
    """Interactively removes a server from the user's configuration file."""
    config_file = find_config_file()
    if not config_file:
        console.print("[bold red]Error:[/bold red] No configuration file found to remove a server from.", style="error")
        return

    if str(config_file) == str(SYSTEM_CONFIG_FILE):
        console.print(f"[bold red]Error:[/bold red] Cannot remove server from system-wide config at [cyan]{SYSTEM_CONFIG_FILE}[/cyan].")
        console.print("This command only works on the user config file at [cyan]~/.config/check-servers/servers.conf[/cyan].")
        return

    _, servers = parse_config(config_file)
    if not servers:
        console.print("[yellow]No servers found in the configuration file to remove.[/yellow]")
        return

    console.print("Select a server to remove:")
    for i, server in enumerate(servers, 1):
        console.print(f"{i:>3}. [cyan]{server.name:<15}[/cyan] ([magenta]{server.ip:<15}[/magenta]) [blue]({server.type})[/blue]")

    try:
        choice = int(console.input("\nEnter the number of the server to remove (or 0 to cancel): "))
        if choice == 0:
            console.print("Cancelled.")
            return
        if not (1 <= choice <= len(servers)):
            raise ValueError()
    except ValueError:
        console.print("[bold red]Invalid selection.[/bold red]")
        return

    server_to_remove = servers[choice - 1]

    with open(config_file, "r") as f:
        lines = f.readlines()
    
    with open(config_file, "w") as f:
        for line in lines:
            if not (server_to_remove.ip in line and server_to_remove.name in line):
                f.write(line)

    console.print(f"Successfully removed server [bold cyan]{server_to_remove.name}[/bold cyan] from [magenta]{config_file}[/magenta].")

def ping_server(server: Server, timeout: float, retries: int) -> PingResult:
    """Pings a server with retries and returns a result object."""
    # Ensure timeout is a string for the command
    timeout_str = str(timeout)
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
                return PingResult(server=server, status=STATUS_OK, latency=latency)
        
        # If ping fails (non-zero return code or no match), the loop continues to the next retry.
        
    return PingResult(server=server, status=STATUS_DOWN)

def get_servers_to_check(all_servers: List[Server], args: argparse.Namespace) -> List[Server]:
    """Filters the list of servers based on command-line arguments."""
    if args.local and not args.remote:
        return [s for s in all_servers if s.type == 'local']
    if args.remote and not args.local:
        return [s for s in all_servers if s.type == 'remote']
    return all_servers

def run_pings(servers_to_check: List[Server], settings: Dict[str, Any], console: Console) -> Dict[str, PingResult]:
    """Executes the ping checks in parallel and shows a progress bar."""
    results: Dict[str, PingResult] = {}
    progress_columns = [SpinnerColumn()]
    progress = Progress(*progress_columns, transient=True)

    with Live(progress, console=console):
        with ThreadPoolExecutor() as executor:
            task = progress.add_task("Pinging servers...", total=len(servers_to_check))
            future_to_server = {
                executor.submit(ping_server, s, settings['timeout'], settings['retries']): s for s in servers_to_check
            }
            for future in as_completed(future_to_server):
                try:
                    res = future.result()
                    results[res.server.name] = res
                except FileNotFoundError:
                    # Handle case where 'ping' command is not found
                    server_name = future_to_server[future].name
                    console.print(f"[bold red]Error:[/bold red] 'ping' command not found. Cannot check '{server_name}'.")
                except Exception as e:
                    # Catch other potential exceptions from ping_server
                    server_name = future_to_server[future].name
                    console.print(f"[bold red]Error checking '{server_name}':[/bold red] {e}")
                finally:
                    progress.update(task, advance=1)
    return results

def display_results(servers_to_check: List[Server], results: Dict[str, PingResult], args: argparse.Namespace, console: Console):
    """Builds and prints the results table and summary stats."""
    table = Table(title="Server Status")
    table.add_column("SERVER", style="cyan", no_wrap=True)
    table.add_column("ADDRESS", style="magenta")
    table.add_column("TYPE", style="blue")
    table.add_column("STATUS", justify="center")
    table.add_column("TIME", justify="right", style="green")

    up_count, down_count = 0, 0
    total_latency = 0

    for server in servers_to_check:
        res = results.get(server.name)
        if not res: continue

        if res.status == STATUS_OK:
            up_count += 1
            if res.latency is not None:
                total_latency += res.latency
            status_style = "[green]OK[/green]"
            latency_str = f"{res.latency:4.2f} ms"
            if not args.quiet:
                table.add_row(res.server.name, res.server.ip, res.server.type, status_style, latency_str)
        else:
            down_count += 1
            status_style = "[red]DOWN[/red]"
            table.add_row(res.server.name, res.server.ip, res.server.type, status_style, "--")

    if table.row_count > 0:
        console.print(table)
    elif not args.quiet:
        console.print("[yellow]No servers to display.[/yellow]")

    avg_latency = (total_latency / up_count) if up_count > 0 else 0
    console.print(f"STATS: [green]{up_count}/{len(servers_to_check)} Online[/] | [red]{down_count} Down[/] | Avg Latency: {avg_latency:.2f}ms")


def run_check_command(args: argparse.Namespace, console: Console):
    """Runs the full server check process."""
    config_file = find_config_file()
    if not config_file:
        console.print("[bold red]Error:[/bold red] Configuration file not found in ~/.config/check-servers/ or /etc/check-servers/", style="error")
        return

    settings, all_servers = parse_config(config_file)
    
    # The 'local' and 'remote' arguments will exist on the args namespace
    # because we are explicitly in the 'check' command context.
    servers_to_check = get_servers_to_check(all_servers, args)
    
    if not servers_to_check:
        console.print("[yellow]No servers to check.[/yellow]")
        return

    results = run_pings(servers_to_check, settings, console)
    display_results(servers_to_check, results, args, console)


def run():
    """Main script execution."""
    parser = argparse.ArgumentParser(
        description="Check server status or add a new server to the configuration."
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands", required=False)

    # Subparser for the 'check' command (default behavior)
    parser_check = subparsers.add_parser("check", help="Check server status (default if no command is given)")
    parser_check.add_argument("-l", "--local", action="store_true", help="Check local servers only.")
    parser_check.add_argument("-r", "--remote", action="store_true", help="Check remote servers only.")
    parser_check.add_argument("-q", "--quiet", action="store_true", default=False, help="Only show servers that are down.")

    # Subparser for the 'add' command
    parser_add = subparsers.add_parser("add", help="Add a new server to the configuration file.")
    parser_add.add_argument("ip", help="The IP address of the server.")
    parser_add.add_argument("name", help="The name of the server.")
    parser_add.add_argument("type", choices=["local", "remote"], help="The type of server (local or remote).")

    # Subparser for the 'remove' command
    parser_remove = subparsers.add_parser("remove", help="Interactively remove a server from the configuration file.")

    args = parser.parse_args()
    console = Console()

    if args.command == "add":
        add_server_to_config(args.ip, args.name, args.type, console)
    elif args.command == "remove":
        remove_server_from_config(console)
    elif args.command is None:
        # If no command is given, set 'check' as the default and re-parse
        # We need to slice sys.argv to avoid the script name being processed as a command
        check_argv = ['check'] + sys.argv[1:]
        args = parser.parse_args(check_argv)
        run_check_command(args, console)
    else: # This handles the 'check' command explicitly
        run_check_command(args, console)

