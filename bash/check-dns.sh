#!/bin/bash

# A script to check DNS resolution against specified DNS servers (Pi-holes).

# ==========================================
# GLOBALS & COLORS
# ==========================================
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ==========================================
# CONFIGURATION
# ==========================================
# DNS Servers to check against
PIHOLE1="10.0.0.5"  # Primary Pi-hole (this machine)
PIHOLE2="10.0.0.3"  # Secondary Pi-hole

# Timeout for DNS queries in seconds. 'dig' rounds values < 1 up to 1.
DNS_TIMEOUT=1

# Websites to resolve
WEBSITES=(
    "google.com"
    "cloudflare.com"
    "github.com"
    "youtube.com"
    "amazon.com"
    "reddit.com"
    "netflix.com"
    "microsoft.com"
    "apple.com"
)

# ==========================================
# FUNCTIONS
# ==========================================

function print_usage() {
    echo "Usage: $(basename "$0")"
    echo "Checks DNS resolution for a predefined list of websites against two Pi-hole servers."
    echo "The servers are hardcoded as PIHOLE1=${PIHOLE1} and PIHOLE2=${PIHOLE2}."
}

function check_dns() {
    local temp_dir
    temp_dir=$(mktemp -d -t check-dns-XXXXXX)
    trap 'rm -rf -- "$temp_dir"' EXIT

    echo "--------------------------------------------------------------------------------------------------"
    printf "%-20s %-18s %-18s %-18s %s\n" "WEBSITE" "PIHOLE1 STATUS" "PIHOLE2 STATUS" "DNS IPV4" "DNS IPV6"
    echo "--------------------------------------------------------------------------------------------------"

    # --- 1. Launch all checks in parallel ---
    for site in "${WEBSITES[@]}"; do
    (
        # Check against Pi-hole 1
        local ph1_ipv4 ph1_ipv6 ph1_status
        ph1_ipv4=$(dig @"$PIHOLE1" A "$site" +short +time="$DNS_TIMEOUT" | head -n1)
        # If dig output contains an error message, treat it as a failure and blank the variable.
        if [[ "$ph1_ipv4" == *";; communications error"* ]]; then ph1_ipv4=""; fi
        local ph1_ipv4_success=$?
        ph1_ipv6=$(dig @"$PIHOLE1" AAAA "$site" +short +time="$DNS_TIMEOUT" | head -n1)
        if [[ "$ph1_ipv6" == *";; communications error"* ]]; then ph1_ipv6=""; fi
        local ph1_ipv6_success=$?

        # Success if at least one query succeeded AND returned an IP.
        if { [ $ph1_ipv4_success -eq 0 ] && [ -n "$ph1_ipv4" ]; } || { [ $ph1_ipv6_success -eq 0 ] && [ -n "$ph1_ipv6" ]; }; then
            ph1_status="OK"
        else
            ph1_status="FAIL"
        fi

        # Check against Pi-hole 2
        local ph2_ipv4 ph2_ipv6 ph2_status
        ph2_ipv4=$(dig @"$PIHOLE2" A "$site" +short +time="$DNS_TIMEOUT" | head -n1)
        if [[ "$ph2_ipv4" == *";; communications error"* ]]; then ph2_ipv4=""; fi
        local ph2_ipv4_success=$?
        ph2_ipv6=$(dig @"$PIHOLE2" AAAA "$site" +short +time="$DNS_TIMEOUT" | head -n1)
        if [[ "$ph2_ipv6" == *";; communications error"* ]]; then ph2_ipv6=""; fi
        local ph2_ipv6_success=$?

        if { [ $ph2_ipv4_success -eq 0 ] && [ -n "$ph2_ipv4" ]; } || { [ $ph2_ipv6_success -eq 0 ] && [ -n "$ph2_ipv6" ]; }; then
            ph2_status="OK"
        else
            ph2_status="FAIL"
        fi

        # Use the result from the primary pi-hole for the IP display.
        local display_ipv4="$ph1_ipv4"
        local display_ipv6="$ph1_ipv6"

        # Fallback to secondary IP ONLY if primary was empty AND secondary lookup was successful.
        [[ -z "$display_ipv4" && "$ph2_status" == "OK" ]] && display_ipv4="$ph2_ipv4" # This line is mostly for redundancy
        [[ -z "$display_ipv6" && "$ph2_status" == "OK" ]] && display_ipv6="$ph2_ipv6"

        # Store results in a temp file for ordered printing
        local temp_file_name=$(echo "$site" | tr -s -c '[:alnum:]' '_')
        {
            echo "$ph1_status"
            echo "$ph2_status"
            echo "${display_ipv4:--}"
            echo "${display_ipv6:--}"
        } > "$temp_dir/$temp_file_name"
    ) &
    done

    # --- 2. Wait for all background jobs to finish ---
    wait

    # --- 3. Process results and print in order ---
    # Stats variables
    local ph1_ok_count=0
    local ph1_fail_count=0
    local ph2_ok_count=0
    local ph2_fail_count=0

    for site in "${WEBSITES[@]}"; do
        local temp_file_name=$(echo "$site" | tr -s -c '[:alnum:]' '_')
        
        # Check if the temp file was created; if not, something went wrong.
        if [[ ! -f "$temp_dir/$temp_file_name" ]]; then
            printf "%-20s ${RED}%-18s %-18s %-18s %s${NC}\n" "$site" "ERROR" "ERROR" "N/A" "N/A"
            continue
        fi

        mapfile -t results < "$temp_dir/$temp_file_name"
        local ph1_status=${results[0]}
        local ph2_status=${results[1]}
        local ipv4=${results[2]}
        local ipv6=${results[3]}

        # Increment counters
        if [[ "$ph1_status" == "OK" ]]; then
            ((ph1_ok_count++))
        else
            ((ph1_fail_count++))
        fi
        if [[ "$ph2_status" == "OK" ]]; then
            ((ph2_ok_count++))
        else
            ((ph2_fail_count++))
        fi

        local ph1_color=$([[ "$ph1_status" == "OK" ]] && echo "$GREEN" || echo "$RED")
        local ph2_color=$([[ "$ph2_status" == "OK" ]] && echo "$GREEN" || echo "$RED")

        printf "%-20s ${ph1_color}%-18s${NC} ${ph2_color}%-18s${NC} ${CYAN}%-18s${NC} ${YELLOW}%s${NC}\n" \
            "$site" \
            "$ph1_status" \
            "$ph2_status" \
            "$ipv4" \
            "$ipv6"
    done

    echo "--------------------------------------------------------------------------------------------------"

    # Calculate and print stats
    local total_sites=${#WEBSITES[@]}
    echo -e "PIHOLE1 STATS: ${GREEN}${ph1_ok_count}/${total_sites} OK${NC} | ${RED}${ph1_fail_count} FAIL${NC} | PIHOLE2 STATS: ${GREEN}${ph2_ok_count}/${total_sites} OK${NC} | ${RED}${ph2_fail_count} FAIL${NC}"
    echo ""
}

function main() {
    # Simple execution, no arguments needed for this version.
    # Check if 'dig' command exists
    if ! command -v dig &> /dev/null; then
        echo "${RED}Error: 'dig' command not found. Please install dnsutils (Debian/Ubuntu) or bind-utils (CentOS/RHEL).${NC}" >&2
        exit 1
    fi

    check_dns
}

# ==========================================
# SCRIPT EXECUTION
# ==========================================
main "$@"