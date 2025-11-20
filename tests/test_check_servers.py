import argparse
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

import pytest

# Import directly from the check_servers package.
# Pytest handles the path automatically when run from the project root.
from check_servers import (
    Server,
    PingResult,
    find_config_file,
    parse_config,
    ping_server,
    get_servers_to_check,
    STATUS_OK,
    STATUS_DOWN
)

@pytest.fixture
def mock_home_dir(monkeypatch):
    """Fixture to mock Path.home() to a temporary directory."""
    def mock_home():
        return Path("/fake/home")
    monkeypatch.setattr(Path, "home", mock_home)


def test_find_config_file_user(mock_home_dir):
    """Test finding the user config file."""
    with patch('pathlib.Path.exists') as mock_exists:
        mock_exists.side_effect = [True, False]
        config_path = find_config_file()
        assert config_path is not None


def test_find_config_file_system(mock_home_dir):
    """Test finding the system config file when user one doesn't exist."""
    with patch('pathlib.Path.exists') as mock_exists:
        # User config doesn't exist, system one does
        mock_exists.side_effect = [False, True]
        config_path = find_config_file()
        assert config_path == Path("/etc/check-servers/servers.conf")


def test_find_config_file_none(mock_home_dir):
    """Test when no config file is found."""
    with patch('pathlib.Path.exists', return_value=False):
        assert find_config_file() is None


@pytest.fixture
def sample_config_content():
    return """
# Settings
timeout = 0.5
retries = 2

[local]
127.0.0.1 localhost
10.0.0.1 router

[remote]
8.8.8.8 google-dns

# Malformed lines to be ignored
bad-line
timeout=notanumber
"""

def test_parse_config_success(sample_config_content):
    """Test successful parsing of a valid config file."""
    with patch("builtins.open", mock_open(read_data=sample_config_content)):
        settings, servers = parse_config(Path("dummy.conf"))

        assert settings['timeout'] == 0.5
        assert settings['retries'] == 2
        assert len(servers) == 3
        assert Server(ip='127.0.0.1', name='localhost', type='local') in servers
        assert Server(ip='10.0.0.1', name='router', type='local') in servers
        assert Server(ip='8.8.8.8', name='google-dns', type='remote') in servers


def test_parse_config_empty():
    """Test parsing an empty config file."""
    with patch("builtins.open", mock_open(read_data="")):
        settings, servers = parse_config(Path("dummy.conf"))
        assert settings['timeout'] == 0.2 # Default
        assert settings['retries'] == 3    # Default
        assert len(servers) == 0


@patch('subprocess.run')
def test_ping_server_success(mock_run):
    """Test a successful ping."""
    server = Server('1.1.1.1', 'one', 'remote')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=11.5 ms"
    mock_run.return_value = mock_result

    result = ping_server(server, timeout=0.2, retries=1)

    assert result.status == STATUS_OK
    assert result.latency == 11.5
    mock_run.assert_called_with(["ping", "-c", "1", "-W0.2", "1.1.1.1"], capture_output=True, text=True)


@patch('subprocess.run')
def test_ping_server_failure(mock_run):
    """Test a failed ping after retries."""
    server = Server('10.255.255.1', 'down', 'local')
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_run.return_value = mock_result

    result = ping_server(server, timeout=0.1, retries=3)

    assert result.status == STATUS_DOWN
    assert result.latency is None
    assert mock_run.call_count == 3


@patch('subprocess.run', side_effect=FileNotFoundError)
def test_ping_server_command_not_found(mock_run):
    """Test that ping_server raises FileNotFoundError if ping command is missing."""
    server = Server('127.0.0.1', 'localhost', 'local')
    # The exception is caught in run_pings, so we test that it's raised here.
    with pytest.raises(FileNotFoundError):
        ping_server(server, timeout=0.1, retries=1)


@pytest.fixture
def all_servers_list():
    return [
        Server('127.0.0.1', 'localhost', 'local'),
        Server('192.168.1.1', 'router', 'local'),
        Server('8.8.8.8', 'google', 'remote'),
        Server('1.1.1.1', 'cloudflare', 'remote'),
    ]

def test_get_servers_to_check_local_only(all_servers_list):
    args = argparse.Namespace(local=True, remote=False)
    result = get_servers_to_check(all_servers_list, args)
    assert len(result) == 2
    assert all(s.type == 'local' for s in result)

def test_get_servers_to_check_remote_only(all_servers_list):
    args = argparse.Namespace(local=False, remote=True)
    result = get_servers_to_check(all_servers_list, args)
    assert len(result) == 2
    assert all(s.type == 'remote' for s in result)

def test_get_servers_to_check_all_none_specified(all_servers_list):
    args = argparse.Namespace(local=False, remote=False)
    result = get_servers_to_check(all_servers_list, args)
    assert len(result) == 4
    assert result == all_servers_list

def test_get_servers_to_check_all_both_specified(all_servers_list):
    args = argparse.Namespace(local=True, remote=True)
    result = get_servers_to_check(all_servers_list, args)
    assert len(result) == 4
    assert result == all_servers_list