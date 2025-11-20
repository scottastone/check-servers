#!/home/scott/code/projects/check-servers/.venv/bin/python3

"""
A script to check DNS resolution against specified DNS servers (Pi-holes)
using rich for formatted output.
"""

import dns.resolver
import dns.exception
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn

# ==========================================
# CONFIGURATION
# ==========================================
PIHOLE1 = "10.0.0.5"  # Primary Pi-hole (this machine)
PIHOLE2 = "10.0.0.3"  # Secondary Pi-hole
DNS_TIMEOUT = 1.0     # Timeout for DNS queries in seconds

WEBSITES = [
    "google.com",
    "cloudflare.com",
    "github.com",
    "youtube.com",
    "amazon.com",
    "reddit.com",
    "netflix.com",
    "microsoft.com",
    "apple.com",
]

# ==========================================
# DATA CLASSES & FUNCTIONS
# ==========================================

@dataclass
class DNSQueryResult:
    """Holds the result of a DNS query for a single server."""
    status: str = "FAIL"
    ipv4: str = "-"
    ipv6: str = "-"

@dataclass
class SiteCheckResult:
    """Holds the full check result for a single website."""
    site: str
    ph1_result: DNSQueryResult
    ph2_result: DNSQueryResult
    display_ipv4: str = "-"
    display_ipv6: str = "-"

def get_dns_records(website: str, server: str) -> DNSQueryResult:
    """Queries a DNS server for A and AAAA records for a given website."""
    resolver = dns.resolver.Resolver()
    resolver.nameservers = [server]
    resolver.lifetime = DNS_TIMEOUT

    ipv4, ipv6 = "-", "-"
    try:
        # Query for A record (IPv4)
        a_records = resolver.resolve(website, 'A')
        ipv4 = str(a_records[0]) if a_records else "-"
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.Timeout, dns.resolver.NoNameservers):
        pass # Keep default "-"

    try:
        # Query for AAAA record (IPv6)
        aaaa_records = resolver.resolve(website, 'AAAA')
        ipv6 = str(aaaa_records[0]) if aaaa_records else "-"
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.Timeout, dns.resolver.NoNameservers):
        pass # Keep default "-"

    status = "OK" if ipv4 != "-" or ipv6 != "-" else "FAIL"
    return DNSQueryResult(status=status, ipv4=ipv4, ipv6=ipv6)

def check_site(site: str) -> SiteCheckResult:
    """Performs DNS checks for a single site against both Pi-holes."""
    ph1_result = get_dns_records(site, PIHOLE1)
    ph2_result = get_dns_records(site, PIHOLE2)

    # Determine which IP to display, preferring Pi-hole 1
    display_ipv4 = ph1_result.ipv4 if ph1_result.ipv4 != "-" else ph2_result.ipv4
    display_ipv6 = ph1_result.ipv6 if ph1_result.ipv6 != "-" else ph2_result.ipv6

    return SiteCheckResult(
        site=site,
        ph1_result=ph1_result,
        ph2_result=ph2_result,
        display_ipv4=display_ipv4,
        display_ipv6=display_ipv6
    )

def main():
    """Main script execution."""
    console = Console()
    results = {}

    progress = Progress(
        SpinnerColumn(),
        transient=True
    )

    with Live(progress, console=console):
        with ThreadPoolExecutor() as executor:
            task = progress.add_task("DNS Checks", total=len(WEBSITES), site=WEBSITES[0])
            future_to_site = {executor.submit(check_site, site): site for site in WEBSITES}
            for i, future in enumerate(as_completed(future_to_site)):
                site = future_to_site[future]
                try:
                    results[site] = future.result()
                except Exception as e:
                    console.print(f"Error checking {site}: {e}", style="bold red")
                progress.update(task, advance=1, site=WEBSITES[i] if i < len(WEBSITES) else "")

    # --- Build and print the results table ---
    table = Table(title="DNS Resolution Check")
    table.add_column("Website", style="cyan", no_wrap=True)
    table.add_column("Pi-hole 1 Status", justify="center")
    table.add_column("Pi-hole 2 Status", justify="center")
    table.add_column("DNS IPv4", style="magenta")
    table.add_column("DNS IPv6", style="yellow")

    ph1_ok, ph2_ok = 0, 0
    for site in WEBSITES: # Iterate in original order for consistent output
        res = results.get(site)
        if not res: continue

        ph1_status = f"[green]{res.ph1_result.status}[/]" if res.ph1_result.status == "OK" else f"[red]{res.ph1_result.status}[/]"
        ph2_status = f"[green]{res.ph2_result.status}[/]" if res.ph2_result.status == "OK" else f"[red]{res.ph2_result.status}[/]"
        if res.ph1_result.status == "OK": ph1_ok += 1
        if res.ph2_result.status == "OK": ph2_ok += 1
        table.add_row(res.site, ph1_status, ph2_status, res.display_ipv4, res.display_ipv6)

    console.print(table)
    console.print(f"PIHOLE1 STATS: [green]{ph1_ok}/{len(WEBSITES)} OK[/] | [red]{len(WEBSITES) - ph1_ok} FAIL[/]")
    console.print(f"PIHOLE2 STATS: [green]{ph2_ok}/{len(WEBSITES)} OK[/] | [red]{len(WEBSITES) - ph2_ok} FAIL[/]")

if __name__ == "__main__":
    main()