#!/home/scott/code/projects/check-servers/.venv/bin/python3

"""
A script to check the status of Docker containers on local or remote hosts.
Replicates the functionality of check-docker.sh with a rich UI.
"""

import argparse
import configparser
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Dict, Tuple

import docker
from docker.errors import APIError, DockerException
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn

# ==========================================
# CONFIGURATION
# ==========================================
USER_CONFIG_DIR = Path.home() / ".config/check-docker"
USER_CONFIG_FILE = USER_CONFIG_DIR / "servers.conf"
SYSTEM_CONFIG_FILE = Path("/etc/check-docker/servers.conf")

# ==========================================
# DATA CLASSES & FUNCTIONS
# ==========================================

def find_config_file() -> Optional[Path]:
    """Finds the configuration file in user or system paths."""
    if USER_CONFIG_FILE.exists():
        return USER_CONFIG_FILE
    if SYSTEM_CONFIG_FILE.exists():
        return SYSTEM_CONFIG_FILE
    return None

def parse_config(config_file: Path) -> Dict[str, List[str]]:
    """Parses the docker configuration file."""
    containers_by_host = {}
    current_host = None
    with open(config_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('host='):
                current_host = line.split('=', 1)[1].strip()
                if current_host not in containers_by_host:
                    containers_by_host[current_host] = []
            elif current_host:
                containers_by_host[current_host].append(line)
    return containers_by_host

def check_host_containers(host: str, containers: List[str]) -> List[Tuple[str, str, str, str]]:
    """Checks the status of a list of containers on a single Docker host."""
    results = []
    try:
        # Use DOCKER_HOST environment variable or default socket
        base_url = f"ssh://{host}" if host not in ("127.0.0.1", "localhost") else None
        client = docker.from_env(environment={'DOCKER_HOST': base_url}) if base_url else docker.from_env()
        
        # Get all containers on the host to check against
        all_host_containers = client.containers.list(all=True)
        container_map = {c.name: c for c in all_host_containers}

        for name in containers:
            container = container_map.get(name)
            if container:
                status = "OK" if container.status == 'running' else "DOWN"
                info = container.status
            else:
                status = "DOWN"
                info = "Not Found"
            results.append((name, host, status, info))
            
    except (APIError, DockerException) as e:
        # If the host is down or Docker isn't running, mark all as failed
        for name in containers:
            results.append((name, host, "FAIL", "Host Unreachable"))
            
    return results

def main():
    """Main script execution."""
    parser = argparse.ArgumentParser(description="Check the status of Docker containers.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Only show containers that are down.")
    args = parser.parse_args()

    console = Console()
    config_file = find_config_file()
    if not config_file:
        console.print("[bold red]Error:[/bold red] Configuration file not found.", style="error")
        return

    containers_by_host = parse_config(config_file)
    if not containers_by_host:
        console.print("[yellow]No hosts or containers to check in config.[/yellow]")
        return

    all_results = []
    progress = Progress(SpinnerColumn(), BarColumn(), TextColumn("[progress.percentage]{task.percentage:>3.0f}%"), transient=True)

    with Live(progress, console=console):
        with ThreadPoolExecutor() as executor:
            task = progress.add_task("Checking containers...", total=len(containers_by_host))
            future_to_host = {
                executor.submit(check_host_containers, host, containers): host 
                for host, containers in containers_by_host.items()
            }
            for future in as_completed(future_to_host):
                all_results.extend(future.result())
                progress.update(task, advance=1)

    # --- Build and print the results table ---
    table = Table(title="Docker Container Status")
    table.add_column("CONTAINER", style="cyan", no_wrap=True)
    table.add_column("HOST", style="magenta")
    table.add_column("STATUS", justify="center")
    table.add_column("INFO", style="yellow")

    up_count, down_count = 0, 0
    total_containers = len(all_results)

    # Sort results for consistent output
    all_results.sort(key=lambda x: (x[1], x[0]))

    for name, host, status, info in all_results:
        if status == "OK":
            up_count += 1
            if not args.quiet:
                table.add_row(name, host, f"[green]{status}[/green]", info)
        else:
            down_count += 1
            table.add_row(name, host, f"[red]{status}[/red]", info)

    console.print(table)
    console.print(f"STATS: [green]{up_count}/{total_containers} Online[/] | [red]{down_count} Down[/]")

if __name__ == "__main__":
    main()