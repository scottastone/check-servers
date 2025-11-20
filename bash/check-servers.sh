#!/bin/bash

# A script to check the status of local and remote servers.

# ==========================================
# GLOBALS & COLORS
# ==========================================
# Define standard configuration paths
USER_CONFIG_DIR="$HOME/.config/check-servers"
USER_CONFIG_FILE="$USER_CONFIG_DIR/servers.conf"
SYSTEM_CONFIG_FILE="/etc/check-servers/servers.conf"
CONFIG_FILE="" # This will be set by find_or_create_config_file
GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'   # For Local
PURPLE='\033[0;35m' # For Remote
NC='\033[0m'        # No Color

# ==========================================
# FUNCTIONS
# ==========================================

function print_usage() {
    echo "Usage: $(basename "$0") [FLAG]"
    echo "Flags:"
    echo "  -l, --local                     Check local servers only."
    echo "  -r, --remote                    Check remote servers only."
    echo "  -a, --add <IP> <NAME> <TYPE>    Add a new server (e.g., -a 10.0.0.9 garage local)."
    echo "  -d, --delete <NAME>             Delete a server by its name."
    echo "  -q, --quiet                     Only show servers that are down and the final summary."
    echo "  -H, --history <NAME>            Show historical uptime for a specific server."
    echo "  -L, --list                      List all configured servers and exit."
    echo "  -C, --config-path               Show the path to the active configuration file."
    echo "  -h, --help                      Show this help message."
}

function find_or_create_config_file() {
    if [ -f "$USER_CONFIG_FILE" ]; then
        CONFIG_FILE="$USER_CONFIG_FILE"
    elif [ -f "$SYSTEM_CONFIG_FILE" ]; then
        CONFIG_FILE="$SYSTEM_CONFIG_FILE"
    else
        read -p "Configuration not found. Create a default user config at '$USER_CONFIG_FILE'? [y/N] " -n 1 -r
        echo # Move to a new line
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "Creating default configuration file..."
            mkdir -p "$USER_CONFIG_DIR"
            # Create the file with a helpful template
            cat > "$USER_CONFIG_FILE" << 'EOF'
# Server configuration for check-servers.sh
# Format: IP DISPLAY_NAME
# Lines starting with # are ignored.

# --- Global Settings ---
timeout = 0.2 # Ping timeout in seconds (e.g., 0.2 for 200ms)
retries = 3   # Number of ping attempts before marking as down.

# --- Add your local servers under this section ---
[local]
# 192.168.1.1 my-router
# 10.0.0.100 file-server

# --- Add your remote servers under this section ---
[remote]
# 8.8.8.8 google-dns
EOF
            CONFIG_FILE="$USER_CONFIG_FILE"
            echo "File created. Please edit it to add your servers."
            exit 0
        else
            echo "Aborted. No configuration file to use." >&2
            exit 1
        fi
    fi
}

function add_server() {
    local new_ip="$1"
    local new_name="$2"
    local new_type="$3"

    if [[ "$new_type" != "local" && "$new_type" != "remote" ]]; then
        echo "Error: TYPE must be 'local' or 'remote'." >&2
        exit 1
    fi

    # Check if server name or IP already exists
    # We check for the IP at the start of a line, or the name as a distinct word
    if grep -qE "^\s*${new_ip}\s" "$CONFIG_FILE" || grep -qE "\s\b${new_name}\b\s*$" "$CONFIG_FILE"; then
        echo "Error: A server with name '${new_name}' or IP '${new_ip}' already exists." >&2
        exit 1
    fi

    local new_entry="$new_ip $new_name"

    if [[ "$new_type" == "local" ]]; then
        # Add the server under the [local] section.
        # If [remote] exists, add it before that section. Otherwise, append to the file.
        local remote_section_line
        remote_section_line=$(grep -n '\[remote\]' "$CONFIG_FILE" | cut -d: -f1)
        if [[ -n "$remote_section_line" ]]; then
            sed -i "$((remote_section_line - 1)) a\\$new_entry" "$CONFIG_FILE"
        else
            echo "$new_entry" >> "$CONFIG_FILE"
        fi
    else # remote
        echo "" >> "$CONFIG_FILE" && echo "$new_entry" >> "$CONFIG_FILE"
    fi
    echo "Server '$new_name' added successfully."
}

function delete_server() {
    local server_name_to_delete="$1"

    # Extract the name part from each line (everything after the first space)
    # and see if it's a literal match for the server name to delete.
    local line_to_delete
    line_to_delete=$(awk -v name_to_find="$server_name_to_delete" '
        {
            # Find the position of the first space
            first_space = index($0, " ")
            # If a space is found, extract the name part
            if (first_space > 0) {
                name = substr($0, first_space + 1)
                # If the extracted name is a literal match to our variable, print the whole line
                if (name == name_to_find) {
                    print $0
                }
            }
        }' "$CONFIG_FILE")

    # Check if the server exists before trying to delete
    if [ -z "$line_to_delete" ]; then
        echo "Error: Server with name '${server_name_to_delete}' not found." >&2
        exit 1
    fi

    # Use grep to remove the exact line that was found. -F treats the pattern as a fixed string.
    grep -vF "$line_to_delete" "$CONFIG_FILE" > "$CONFIG_FILE.tmp" && mv "$CONFIG_FILE.tmp" "$CONFIG_FILE"
    echo "Server '${server_name_to_delete}' deleted successfully."
}

function show_history() {
    local server_name="$1"
    local log_dir="$USER_CONFIG_DIR/logs"
    local log_file="$log_dir/${server_name}.log"

    if [[ ! -f "$log_file" ]]; then
        echo "No history data found for server '$server_name'." >&2
        exit 1
    fi

    echo -e "Uptime History for Server: ${CYAN}${server_name}${NC}"
    echo "-------------------------------------"

    # Define time periods. We use GNU date to calculate the start time for each.
    local periods=("24 hours" "7 days" "30 days")
    local now
    now=$(date +%s)

    for period in "${periods[@]}"; do
        local start_time_str
        start_time_str=$(date -d "$now seconds - $period" -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null)
        if [[ $? -ne 0 ]]; then
            echo "Warning: Could not parse date for period '$period'. Is GNU date installed?" >&2
            continue
        fi

        # Use awk to efficiently parse the log file
        local stats
        stats=$(awk -v start_time="$start_time_str" '
            BEGIN { up=0; down=0; }
            $1 >= start_time {
                if ($2 == "UP") up++;
                if ($2 == "DOWN") down++;
            }
            END { print up, down; }
        ' "$log_file")

        local up_count down_count
        read -r up_count down_count <<< "$stats"
        
        local total_count=$((up_count + down_count))
        local uptime_percent="N/A"

        if [[ $total_count -gt 0 ]]; then
            uptime_percent=$(printf "%.2f" "$(echo "($up_count / $total_count) * 100" | bc -l)")
        fi

        printf "Last %-8s: %-8s%% (%d/%d checks)\n" "$period" "$uptime_percent" "$up_count" "$total_count"
    done
    echo "-------------------------------------"
}

function list_servers() {
    echo -e "Configured Servers in ${CYAN}${CONFIG_FILE}${NC}:"
    echo "------------------------------------------------------------"
    printf "%-18s %-25s %s\n" "ADDRESS" "SERVER" "TYPE"
    echo "------------------------------------------------------------"

    local current_type=""
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Trim leading/trailing whitespace
        line=$(echo "$line" | sed 's/^[ \t]*//;s/[ \t]*$//')

        # Ignore comments, empty lines, and settings
        if [[ -z "$line" || "$line" =~ ^# || "$line" =~ = ]]; then
            continue
        fi

        # Detect section headers
        if [[ "$line" =~ ^\[(local|remote)\]$ ]]; then
            current_type="${BASH_REMATCH[1]}"
            continue
        fi

        # Process server lines if they are in a valid section
        if [[ -n "$current_type" ]]; then
            local ip=${line%% *}
            local name=${line#* }
            
            local type_color=$([[ "$current_type" == "local" ]] && echo "$CYAN" || echo "$PURPLE")

            printf "%-18s %-25s ${type_color}%s${NC}\n" "$ip" "$name" "$current_type"
        fi
    done < "$CONFIG_FILE"
    echo "------------------------------------------------------------"
}

function build_process_list() {
    local filter="$1"
    local process_list=()
    local current_type=""

    # Read the config file line by line to parse sections
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Trim whitespace
        line=$(echo "$line" | sed 's/^[ \t]*//;s/[ \t]*$//')
        
        # Ignore comments and empty lines
        if [[ -z "$line" || "$line" =~ ^# || "$line" =~ = ]]; then
            continue
        fi

        # Detect section headers
        if [[ "$line" =~ ^\[(local|remote)\]$ ]]; then
            current_type="${BASH_REMATCH[1]}"
            continue
        # If we encounter any other section header, reset the type to ignore subsequent lines
        elif [[ "$line" =~ ^\[.*\]$ ]]; then
            current_type=""
            continue
        fi

        # Process server lines if they are in a valid section
        if [[ -n "$current_type" ]]; then
            # Check if the current section should be processed based on the filter
            if [[ "$filter" == "all" || "$filter" == "$current_type" ]]; then
                # Extract IP and Name
                local ip=${line%% *}
                local name=${line#* }
                # Reconstruct the internal format "IP|NAME|TYPE"
                process_list+=("$ip|$name|$current_type")
            fi
        fi
    done < "$CONFIG_FILE"
    
    # Return the list
    printf "%s\n" "${process_list[@]}"
}

function check_servers() {
    # $1: process_list_str, $2: quiet_mode, $3: ping_timeout, $4: ping_retries
    local process_list_str="$1"
    local quiet_mode="$2"
    local ping_timeout="$3"
    local ping_retries="$4"
    # Convert string back to array
    mapfile -t process_list < <(echo -e "$process_list_str")

    # Stats variables
    local total=0
    local up=0
    local down=0
    local total_latency=0
    local header_printed=false
    
    # Create a temporary directory for ping outputs and set a trap to clean it up on exit.
    local temp_dir
    temp_dir=$(mktemp -d -t check-servers-XXXXXX)
    trap 'rm -rf -- "$temp_dir"' EXIT

    echo "------------------------------------------------------------------"
    if [[ "$quiet_mode" = false ]]; then
        printf "%-20s %-18s %-10s %-10s %s\n" "SERVER" "ADDRESS" "TYPE" "STATUS" "TIME"
        echo "------------------------------------------------------------------"
        header_printed=true
    fi

    # --- 1. Launch all pings in parallel ---
    for entry in "${process_list[@]}"; do
        # Run each ping in a backgrounded subshell
        (
            local ip="${entry%%|*}"
            local remainder="${entry#*|}"
            local name="${remainder%%|*}"
            local display_name="$name"
            
            local output result=1 # Default to failure

            for (( i=1; i<=ping_retries; i++ )); do
                # Run the ping command
                output=$(ping -c 1 -A -W "$ping_timeout" "$ip" 2>&1)
                result=$?
                # If ping is successful, break the loop
                if [[ $result -eq 0 ]]; then
                    break
                fi
                # Optional: sleep for a short duration between retries
                sleep 0.1
            done
            # Store result and output in a temp file for later processing
            # Use a temp file name that is safe for the filesystem
            local temp_file_name=$(echo "$display_name" | tr -s -c '[:alnum:]' '_')
            echo "$result" > "$temp_dir/$temp_file_name"
            echo "$output" >> "$temp_dir/$temp_file_name"
        ) &
    done

    # --- 2. Wait for all background jobs to finish ---
    wait

    # --- 3. Process results and print in order ---
    for entry in "${process_list[@]}"; do
        local ip name type display_name type_color
        IFS='|' read -r ip name type <<< "$entry"
        display_name="$name"
        type_color=$([[ "$type" == "local" ]] && echo "$CYAN" || echo "$PURPLE")
        
        # Use display_name for temp file to handle spaces
        local temp_file_name=$(echo "$display_name" | tr -s -c '[:alnum:]' '_')

        local result
        result=$(head -n 1 "$temp_dir/$temp_file_name")

        # --- Log the result for history tracking ---
        local log_dir="$USER_CONFIG_DIR/logs"
        mkdir -p "$log_dir"
        local log_file="$log_dir/$display_name.log"
        local log_status=$([[ "$result" -eq 0 ]] && echo "UP" || echo "DOWN")
        echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") $log_status" >> "$log_file"

        ((total++))
        if [[ "$result" -eq 0 ]]; then
            ((up++))
            # Read the rest of the file for the output
            local time
            time=$(grep "time=" "$temp_dir/$temp_file_name" | sed -E 's/.*time=([0-9.]+).*/\1/')
            total_latency=$(echo "$total_latency + $time" | bc -l)
            if [[ "$quiet_mode" = false ]]; then
                printf "${NC}%-20s %-18s ${type_color}%-10s${NC} ${GREEN}%-10s${NC} %s ms\n" "$display_name" "$ip" "$type" "OK" "$time"
            fi
        else
            ((down++))
            if [[ "$header_printed" = false ]]; then
                # Print header in quiet mode only if there's something to show
                printf "%-20s %-18s %-10s %-10s %s\n" "SERVER" "ADDRESS" "TYPE" "STATUS" "TIME"
                echo "------------------------------------------------------------------"
                header_printed=true
            fi
            printf "${NC}%-20s %-18s ${type_color}%-10s${NC} ${RED}%-10s${NC} --\n" "$display_name" "$ip" "$type" "DOWN"
        fi
    done    

    echo "------------------------------------------------------------------"

    # Calculate and print stats
    local avg_latency="0"
    if [ $up -gt 0 ] && [ "$total_latency" != "0" ]; then
        avg_latency=$(printf "%.2f" "$(echo "$total_latency / $up" | bc -l)")
    fi

    echo -e "STATS: ${GREEN}$up/$total Online${NC} | ${RED}$down Down${NC} | Avg Latency: ${avg_latency}ms"
    echo ""
}

function main() {
    local filter="all"
    local quiet_mode=false
    local ping_timeout=0.1 # Default timeout
    local ping_retries=3   # Default retries

    # Find which config file to use, or create one.
    find_or_create_config_file

    # Parse global settings from config, overriding defaults
    if grep -qE "^\s*timeout\s*=" "$CONFIG_FILE"; then
        # Read timeout, remove spaces, and strip comments
        ping_timeout=$(grep -m 1 -E "^\s*timeout\s*=" "$CONFIG_FILE" | sed -E 's/^\s*timeout\s*=\s*//;s/\s*#.*//' | tr -d ' ')
    fi
    if grep -qE "^\s*retries\s*=" "$CONFIG_FILE"; then
        # Read retries, remove spaces, and strip comments
        ping_retries=$(grep -m 1 -E "^\s*retries\s*=" "$CONFIG_FILE" | sed -E 's/^\s*retries\s*=\s*//;s/\s*#.*//' | tr -d ' ')
    fi


    # --- Argument Parsing ---
    # Use a loop to handle multiple flags, e.g., -q -l
    while [[ $# -gt 0 ]]; do
        key="$1"
        case $key in
            -l|--local)
                filter="local"
                shift # past argument
                ;;
            -r|--remote)
                filter="remote"
                shift # past argument
                ;;
            -q|--quiet)
                quiet_mode=true
                shift # past argument
                ;;
            -C|--config-path)
                echo "$CONFIG_FILE"
                exit 0
                ;;
            -L|--list)
                list_servers
                exit 0
                ;;
            -a|--add)
                if [[ $# -lt 4 ]]; then print_usage; exit 1; fi
                add_server "$2" "$3" "$4"; exit 0
                ;;
            -d|--delete)
                if [[ $# -lt 2 ]]; then print_usage; exit 1; fi
                delete_server "$2"; exit 0
                ;;
            -H|--history)
                if [[ $# -lt 2 ]]; then print_usage; exit 1; fi
                show_history "$2"; exit 0
                ;;
            -h|--help)
                print_usage; exit 0
                ;;
            *) # unknown option
                # Stop processing if we hit an unknown arg that isn't a flag
                break
                ;;
        esac
    done

    # --- Execution ---
    local listx_to_process
    list_to_process=$(build_process_list "$filter")
    
    if [ -z "$list_to_process" ]; then
        echo "No servers to check for filter: $filter"
        exit 0
    fi

    check_servers "$list_to_process" "$quiet_mode" "$ping_timeout" "$ping_retries"
}

# ==========================================
# SCRIPT EXECUTION
# ==========================================
main "$@"