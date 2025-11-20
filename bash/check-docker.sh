#!/bin/bash

# A script to check the status of Docker containers on remote hosts.

# ==========================================
# GLOBALS & COLORS
# ==========================================
# Define standard configuration paths
USER_CONFIG_DIR="$HOME/.config/check-docker"
USER_CONFIG_FILE="$USER_CONFIG_DIR/servers.conf"
SYSTEM_CONFIG_FILE="/etc/check-docker/servers.conf"
CONFIG_FILE="" # This will be set by find_or_create_config_file
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m' # For Docker
NC='\033[0m'        # No Color

# ==========================================
# FUNCTIONS
# ==========================================

function print_usage() {
    echo "Usage: $(basename "$0") [FLAG]"
    echo "Flags:"
    echo "  -r, --restart [NAME] Attempt to restart a specific container by NAME, or all down containers if NAME is omitted."
    echo "  -q, --quiet          Only show containers that are down and the final summary."
    echo "  -C, --config-path    Show the path to the active configuration file."
    echo "  -h, --help           Show this help message."
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
# Docker checker configuration file.
# Format:
#   host = <IP_ADDRESS>
#   <container_name_1>
#   <container_name_2>
#
# You can have multiple 'host' sections for different Docker hosts.

host = 127.0.0.1
# my-container-1
# my-container-2
EOF
            CONFIG_FILE="$USER_CONFIG_FILE"
            echo "File created. Please edit it to add your Docker host and containers."
            exit 0
        else
            echo "Aborted. No configuration file to use." >&2
            exit 1
        fi
    fi
}

function build_process_list() {
    local process_list=()
    local docker_host_ip=""

    # Read from the config file, piping it to the while loop to correctly handle lines.
    while IFS= read -r line; do
        # Trim leading/trailing whitespace
        line=$(echo "$line" | sed 's/^[ \t]*//;s/[ \t]*$//')
        if [[ -z "$line" || "$line" =~ ^# ]]; then continue; fi

        # If the line defines a new host, update the current host IP
        if [[ "$line" =~ ^host\s*=\s*(.+) ]]; then
            docker_host_ip="${BASH_REMATCH[1]}"
            continue # Move to the next line after processing the host
        fi

        # If we have a valid host IP set, treat the line as a container
        if [[ -n "$docker_host_ip" ]]; then
            local container_name="$line"
            # Format: "HOST_IP|CONTAINER_NAME|DISPLAY_NAME|docker"
            # The display name is the same as the container name for this simple format.
            process_list+=("$docker_host_ip|$container_name|$container_name|docker")
        fi
    done < "$CONFIG_FILE"
    
    # Return the list
    printf "%s\n" "${process_list[@]}"
}

function perform_single_restart() {
    local ip="$1"
    local name="$2"

    echo "Attempting to restart container '${name}' on host '${ip}'..."
    local restart_output
    local restart_result

    if [[ "$ip" == "127.0.0.1" || "$ip" == "localhost" ]]; then
        restart_output=$(docker restart "$name" 2>&1)
    else
        restart_output=$(ssh -o ConnectTimeout=5 "$ip" "docker restart $name" 2>&1)
    fi
    restart_result=$?

    if [[ $restart_result -eq 0 ]]; then
        printf "${GREEN}Success.${NC}\n"
    else
        printf "${RED}Failed.${NC} Error: %s\n" "$restart_output"
    fi
}

function check_containers() {
    # $1: process_list_str, $2: quiet_mode
    # $1: process_list_str, $2: quiet_mode, $3: restart_mode
    local process_list_str="$1"
    local quiet_mode="$2"
    local restart_mode="$3"
    mapfile -t process_list < <(echo -e "$process_list_str")

    # Stats variables
    local total=0
    local up=0
    local down=0
    local header_printed=false
    
    local temp_dir
    temp_dir=$(mktemp -d -t check-docker-XXXXXX)
    trap 'rm -rf -- "$temp_dir"' EXIT

    echo "--------------------------------------------------------------------------------------------------"
    if [[ "$quiet_mode" = false ]]; then
        printf "%-45s %-18s %-10s %s\n" "CONTAINER" "HOST" "STATUS" "INFO"
        echo "--------------------------------------------------------------------------------------------------"
        header_printed=true
    fi

    # --- 1. Launch all checks in parallel ---
    # Group containers by host to minimize SSH connections
    declare -A containers_by_host
    for entry in "${process_list[@]}"; do
        local ip name
        IFS='|' read -r ip name _ _ <<< "$entry"
        # Append container name to the list for this IP
        containers_by_host["$ip"]+="$name "
    done

    # For each host, run one SSH command to check all its containers
    for ip in "${!containers_by_host[@]}"; do
        (
            local container_list=${containers_by_host[$ip]}
            local filter_args=""
            # Build multiple --filter arguments for the docker command
            for container_name in $container_list; do
                filter_args+="--filter name=^/${container_name}$ "
            done

            # Command to get Name and Status for all specified containers on the host
            # The -a flag ensures we see stopped containers as well.
            # Using a unique separator '|||' to handle spaces in status.
            local remote_cmd="docker ps -a ${filter_args} --format '{{.Names}}|||{{.Status}}'"
            
            # Execute the single SSH command and process its output
            local cmd_output
            local cmd_result

            if [[ "$ip" == "127.0.0.1" || "$ip" == "localhost" ]]; then
                # Execute locally, avoiding SSH overhead. Use bash -c to handle quotes in the command.
                cmd_output=$(bash -c "$remote_cmd" 2>&1)
            else
                # Execute via SSH for remote hosts
                cmd_output=$(ssh -o ConnectTimeout=5 "$ip" "$remote_cmd" 2>&1)
            fi
            cmd_result=$?

            # Process each container that was supposed to be on this host
            for container_name in $container_list; do
                local result=1 # Default to DOWN
                local status_info="Not Found" # Default status

                if [[ $cmd_result -eq 0 ]]; then
                    # Find the line for the current container in the SSH output
                    local container_line=$(echo "$cmd_output" | grep -E "^${container_name}\|\|\|")
                    if [[ -n "$container_line" ]]; then
                        status_info=$(echo "$container_line" | cut -d'|' -f4-)
                        # Check if the status starts with "Up"
                        [[ "$status_info" == Up* ]] && result=0
                    fi
                fi
                
                # Store result in temp file for ordered printing later
                local temp_file_name=$(echo "$container_name" | tr -s -c '[:alnum:]' '_')
                echo "$result" > "$temp_dir/$temp_file_name"
                echo "$status_info" >> "$temp_dir/$temp_file_name"
            done
        ) &
    done

    # --- 2. Wait for all background jobs to finish ---
    wait

    # --- 3. Process results and print in order ---
    for entry in "${process_list[@]}"; do
        local ip name display_name type
        IFS='|' read -r ip name display_name type <<< "$entry"
        
        local temp_file_name=$(echo "$name" | tr -s -c '[:alnum:]' '_')
        local result
        local status_info
        result=$(head -n 1 "$temp_dir/$temp_file_name")
        status_info=$(tail -n 1 "$temp_dir/$temp_file_name")

        ((total++))
        if [[ "$result" -eq 0 ]]; then
            ((up++))
            if [[ "$quiet_mode" = false ]]; then
                printf "%-45s %-18s ${GREEN}%-10s${NC} %s\n" "$name" "$ip" "OK" "$status_info"
            fi
        else
            ((down++))
            if [[ "$header_printed" = false ]];
            then
                printf "%-45s %-18s %-10s %s\n" "CONTAINER" "HOST" "STATUS" "INFO"
                echo "--------------------------------------------------------------------------------------------------"
                header_printed=true
            fi
            printf "%-45s %-18s ${RED}%-10s${NC} %s\n" "$name" "$ip" "DOWN" "$status_info"

            if [[ "$restart_mode" = true ]]; then
                printf "    -> ${YELLOW}Attempting to restart...${NC} "
                local restart_output
                restart_output=$(ssh -o ConnectTimeout=5 "$ip" "docker restart $name" 2>&1)
                if [[ $? -eq 0 ]]; then
                    printf "${GREEN}Success.${NC}\n"
                else
                    printf "${RED}Failed.${NC} Error: %s\n" "$restart_output"
                fi
            fi
        fi
    done    

    echo "--------------------------------------------------------------------------------------------------"
    echo -e "STATS: ${GREEN}$up/$total Online${NC} | ${RED}$down Down${NC}"
    echo ""
}

function main() {
    local quiet_mode=false
    local container_to_restart="" # New variable for specific container restart
    local restart_mode=false

    find_or_create_config_file

    # --- Argument Parsing ---
    while [[ $# -gt 0 ]]; do
        key="$1"
        case $key in
            -q|--quiet)
                quiet_mode=true
                shift # past argument
                ;;
            -r|--restart)
                # Check if the next argument is a container name or another flag
                if [[ -n "$2" && ! "$2" =~ ^- ]]; then
                    container_to_restart="$2"
                    shift 2 # past argument and its value
                else
                    # No container name provided, so it's the general restart mode
                    restart_mode=true
                    shift # past argument
                fi
                ;;
            -C|--config-path)
                echo "$CONFIG_FILE"
                exit 0
                ;;
            -h|--help)
                print_usage; exit 0
                ;;
            *) # unknown option
                break
                ;;
        esac
    done

    # --- Execution ---
    local list_to_process
    list_to_process=$(build_process_list)
    
    if [ -z "$list_to_process" ]; then
        echo "No docker containers found in '$CONFIG_FILE'"
        exit 0
    fi

    if [[ -n "$container_to_restart" ]]; then
        local found_container_ip=""
        for entry in "${process_list[@]}"; do
            local ip name _ _
            IFS='|' read -r ip name _ _ <<< "$entry"
            if [[ "$name" == "$container_to_restart" ]]; then
                found_container_ip="$ip"
                break
            fi
        done

        if [[ -n "$found_container_ip" ]]; then
            perform_single_restart "$found_container_ip" "$container_to_restart"
        else
            echo "${RED}Error: Container '${container_to_restart}' not found in configuration.${NC}" >&2
            exit 1
        fi
    else
        # If no specific container to restart, proceed with general checks
        check_containers "$list_to_process" "$quiet_mode" "$restart_mode"
    fi
}

# ==========================================
# SCRIPT EXECUTION
# ==========================================
main "$@"
