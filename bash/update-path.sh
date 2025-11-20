set -xe

# Remove old shell scripts if they exist
sudo rm -f /usr/local/bin/check-servers
sudo rm -f /usr/local/bin/check-docker
sudo rm -f /usr/local/bin/check-dns

# Copy the new Python scripts
sudo cp ./check-servers.py /usr/local/bin/check-servers
sudo chmod +x /usr/local/bin/check-servers

sudo cp ./check-docker.py /usr/local/bin/check-docker
sudo chmod +x /usr/local/bin/check-docker

sudo cp ./check-dns.py /usr/local/bin/check-dns
sudo chmod +x /usr/local/bin/check-dns

# The config file copy can remain the same
mkdir -p "$HOME/.config/check-servers"
cp -n servers.conf "$HOME/.config/check-servers/servers.conf"