#!/home/scott/code/projects/check-servers/.venv/bin/python3
from datetime import datetime, timezone
"""
A script to check the status of Docker containers on local or remote hosts.
Replicates the functionality of check-docker.sh with a rich UI.
"""

import argparse
from pathlib import Path
from typing import List, Optional, Dict, Any

import docker
from docker.errors import APIError, DockerException
from rich.console import Console
from rich.table import Table

# ==========================================
# CONFIGURATION
# ==========================================
USER_CONFIG_DIR = Path.home() / ".config/check-docker"
USER_CONFIG_FILE = USER_CONFIG_DIR / "servers.conf"
SYSTEM_CONFIG_FILE = Path("/etc/check-docker/servers.conf")

# ==========================================
# DATA CLASSES & FUNCTIONS
# ==========================================

class DockerInfo:
    """A simple data class to hold container information."""
    def __init__(self, name: str, status: str, uptime: str, image: str, networks: str, ports: str):
        self.name = name
        self.status = status
        self.uptime = uptime
        self.image = image
        self.networks = networks
        self.ports = ports
# ==========================================

def find_config_file() -> Optional[Path]:
    """Finds the configuration file in user or system paths."""
    if USER_CONFIG_FILE.exists():
        return USER_CONFIG_FILE
    if SYSTEM_CONFIG_FILE.exists():
        return SYSTEM_CONFIG_FILE
    return None

def parse_config(config_file: Path) -> List[str]:
    """Parses the docker configuration file for a list of container names."""
    container_names = []
    with open(config_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            container_names.append(line)
    return container_names

def get_container_details(container_names: List[str]) -> List[DockerInfo]:
    """Gets detailed information for a list of containers on localhost."""
    results = []
    try:
        client = docker.from_env()
        all_host_containers = client.containers.list(all=True)
        container_map = {c.name: c for c in all_host_containers}

        for name in container_names:
            container = container_map.get(name)
            if not container:
                results.append(DockerInfo(name=name, status="Not Found", uptime="--", image="--", networks="--", ports="--"))
                continue

            attrs = container.attrs
            state = attrs.get('State', {})
            
            # Uptime
            uptime_str = "--"
            if state.get('Running') and 'StartedAt' in state:
                start_time_str = state['StartedAt'].split('.')[0] + 'Z' # Format for UTC
                start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                uptime_delta = datetime.now(timezone.utc) - start_time
                uptime_str = str(uptime_delta).split('.')[0] # Remove microseconds

            # Networks
            network_settings = attrs.get('NetworkSettings', {}).get('Networks', {})
            networks = ', '.join(network_settings.keys())

            # Ports
            ports = attrs.get('NetworkSettings', {}).get('Ports', {})
            port_list = []
            for container_port, host_bindings in ports.items():
                if host_bindings:
                    for binding in host_bindings:
                        port_list.append(f"{binding['HostIp']}:{binding['HostPort']}->{container_port}")
                else:
                    port_list.append(container_port) # Exposed but not published
            ports_str = ', '.join(port_list) if port_list else "--"

            results.append(DockerInfo(
                name=name,
                status=container.status,
                uptime=uptime_str,
                image=container.image.short_id,
                networks=networks,
                ports=ports_str
            ))
        
    except (APIError, DockerException) as e:
        # If Docker daemon isn't running, we can't get any info.
        for name in container_names:
            results.append(DockerInfo(name=name, status="FAIL", uptime="--", image="--", networks=str(e), ports="--"))
    return results

def run():
    """Main script execution."""
    parser = argparse.ArgumentParser(description="Check the status of Docker containers.")
    args = parser.parse_args()

    console = Console()
    config_file = find_config_file()
    if not config_file:
        console.print("[bold red]Error:[/bold red] Configuration file not found.", style="error")
        return

    container_names_to_check = parse_config(config_file)
    if not container_names_to_check:
        console.print("[yellow]No containers to check in config.[/yellow]")
        return

    all_results = get_container_details(container_names_to_check)

    # --- Build and print the results table ---
    table = Table(title="Docker Container Status")
    table.add_column("CONTAINER", style="cyan", no_wrap=True)
    table.add_column("STATUS", justify="center")
    table.add_column("UPTIME", style="blue")
    table.add_column("IMAGE", style="magenta")
    table.add_column("NETWORK", style="yellow")
    table.add_column("PORTS", style="green")

    up_count, down_count = 0, 0
    total_containers = len(all_results)

    # Sort results for consistent output
    all_results.sort(key=lambda x: x.name)

    for info in all_results:
        if info.status == "running":
            up_count += 1
            status_styled = f"[green]{info.status}[/green]"
        else:
            down_count += 1
            status_styled = f"[red]{info.status}[/red]"
        
        table.add_row(info.name, status_styled, info.uptime, info.image, info.networks, info.ports)

    console.print(table)
    console.print(f"STATS: [green]{up_count}/{total_containers} Online[/] | [red]{down_count} Down[/]")