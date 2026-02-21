# Secure Remote Access & Docs Sharing Setup

Tailscale · SSH · tmux · Nginx docs browser · Optional HTTPS via Tailscale certs

**Target:** Ubuntu 22.04 LTS server

## Overview
This guide sets up:

A private mesh network with Tailscale. Your server is not reachable from the public internet (no open router ports).
​

Hardened SSH with key‑only auth.
​

Persistent tmux sessions so work survives dropped connections.
​

A docs folder browsable from phone/laptop over HTTP on your home LAN (no SSH session required).

Optional HTTPS on your tailnet using Tailscale certificates with Nginx.

Safety model:

On your home LAN, you access docs directly via HTTP/HTTPS.

From outside, you first join your tailnet (Tailscale) and access docs over HTTPS on the tailnet; SSH is used for admin work/file transfers.
​

Part 1 – Install Tailscale on the Linux Server
1.1 Install Tailscale
bash
curl -fsSL <https://tailscale.com/install.sh> | sh
This adds the repo and GPG key and installs Tailscale on Ubuntu 22.04.
​

1.2 Start Tailscale and authenticate
bash
sudo tailscale up
Tailscale prints a URL; open it in a browser and log in with Google/GitHub/Microsoft.

The server appears in the Tailscale admin console at <https://login.tailscale.com/admin/machines>.
​

1.3 Get your server’s Tailscale IP
bash
tailscale ip -4
Note the 100.x.x.x address; you will use it for SSH and (optionally) HTTPS on the tailnet.
​

1.4 Enable Tailscale SSH (optional but recommended)
bash
sudo tailscale up --ssh
Any device authenticated to your tailnet can SSH to the server using Tailscale credentials; no manual key distribution required.
​

Part 2 – Install Tailscale on Windows
Download and install the Windows client from <https://tailscale.com/download>.
​

Log in with the same account as on the server.
​

After a moment your server (100.x.x.x) appears in the Tailscale tray app.
​

Test connectivity from PowerShell:

powershell
ssh <your-username@100.x.x.x>
Replace your-username with your Linux username and 100.x.x.x with the Tailscale IP.
​

Part 3 – Harden SSH (Key‑Based Only)
Do this from an existing SSH session so you do not lock yourself out.
​

3.1 Generate an SSH key pair on Windows
In PowerShell:

powershell
ssh-keygen -t ed25519 -C "<your-email@example.com>"
Accept default location (C:\Users\you\.ssh\id_ed25519).

Set a passphrase to protect the key.
​

3.2 Copy the public key to your server
powershell
type "$env:USERPROFILE\.ssh\id_ed25519.pub" | ssh <your-username@100.x.x.x> "mkdir -p .ssh && cat >> .ssh/authorized_keys"
You will be prompted for your server password one time.
​

3.3 Verify key auth works
powershell
ssh <your-username@100.x.x.x>
You should log in without being asked for the Linux password (only the key passphrase if set).
​

Do not proceed until this works.

3.4 Disable password authentication
On the server:

bash
sudo nano /etc/ssh/sshd_config
Ensure:

text
PasswordAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
PermitRootLogin no
Save and restart SSH:

bash
sudo systemctl restart sshd
Keep your current SSH session open while you test a new one.
​

3.5 Test from a new SSH session
From Windows:

powershell
ssh <your-username@100.x.x.x>
Password auth is now disabled; only key‑bearing devices can connect.
​

Part 4 – Install and Configure tmux
4.1 Install tmux
bash
sudo apt update
sudo apt install -y tmux
4.2 Basic tmux usage
Start new named session:

bash
tmux new -s claudecode
Detach (leave it running): press Ctrl+B then D.

Reattach:

bash
tmux attach -t claudecode
List sessions:

bash
tmux ls
This keeps sessions alive when your SSH connection drops.
​

4.3 Optional tmux config
bash
nano ~/.tmux.conf
Example:

text
set -g mouse on
set -g history-limit 10000
set -g status-right "%H:%M"
set -g status-left "#S"
Apply without restart:

bash
tmux source-file ~/.tmux.conf
Part 5 – iOS Setup (Tailscale + Blink Shell)
5.1 Install Tailscale on iOS
Install from the App Store, log in with the same account.

Your server appears in the app; toggle it on so the device joins your tailnet.
​

5.2 Install Blink Shell (recommended) or Termius
Blink Shell (paid) supports mosh and works well with tmux.
​

Termius is a free alternative but has less polished terminal handling.
​

5.3 Add your SSH key to Blink
Two options:

Option A – new key in Blink (simpler)

In Blink: Settings → Keys → Create New → ED25519.

Copy the public key and add to server:

bash
nano ~/.ssh/authorized_keys
Paste on a new line.
​

Option B – import Windows key

Export C:\Users\you\.ssh\id_ed25519 and import in Blink: Settings → Keys → Import from Clipboard.
​

5.4 Configure host in Blink
Name: linux-server

Host: 100.x.x.x (Tailscale IP)

User: your-username

Port: 22

Key: the one you added in 5.3.
​

5.5 Connect and attach to tmux
In Blink:

bash
ssh linux-server
tmux attach -t claudecode
You now see the same session from any device, even if the phone connection drops.
​

Part 6 – Migrate Claude Code to the Linux Server
6.1 Install Node.js 20
Ubuntu’s repo is too old. Use NodeSource:

bash
curl -fsSL <https://deb.nodesource.com/setup_20.x> | sudo -E bash -
sudo apt install -y nodejs
node --version
Should show v20.x.x.
​

6.2 Install Claude Code CLI
bash
npm install -g anthropic-ai/claude-code
6.3 Transfer Claude config from Windows
Global config:

powershell
scp -r "$env:USERPROFILE\.claude" <your-username@100.x.x.x>:~/.claude
Project‑level config (example project path; adjust as needed):

powershell
scp -r "C:\opcua\.claude" <your-username@100.x.x.x>:~/simantha-opcua/.claude
6.4 Recreate Python venv
On the server:

bash
cd ~/simantha-opcua
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
Part 7 – Docs Folder Accessible from Browser
Goal: A folder on the server (~/docs) that you can:

Upload files into (from laptop, later from iPhone).

Browse and read from phone/laptop via HTTP/HTTPS, without needing SSH.

7.1 Create shared docs folder
On server:

bash
mkdir -p ~/docs
This is the root for files you want to read in the browser.

7.2 Install Nginx
bash
sudo apt update
sudo apt install -y nginx
7.3 Configure Nginx to serve /docs/ with directory listing
Edit default site:

bash
sudo nano /etc/nginx/sites-available/default
Inside server { ... }, add:

text
server {
    listen 80;
    server_name_;

    location /docs/ {
        alias /home/your-username/docs/;
        autoindex on;
    }
}
alias maps /docs/ to /home/your-username/docs/.

autoindex on; enables simple file‑browser listings in the browser.

Test and reload:

bash
sudo nginx -t
sudo systemctl reload nginx
7.4 Access docs on home LAN (no SSH)
Find server LAN IP (for example):

bash
ip a
Suppose it is 192.168.1.50.

On phone or laptop (connected to home Wi‑Fi):

Open browser, go to:

text
<http://192.168.1.50/docs/>
You see a listing of files in ~/docs; click/tap to view or download.

At this point, inside your home network you do not need SSH to read docs; you just use HTTP.

7.5 Getting files into ~/docs
For now, simplest path is via a laptop:

From Windows (over Tailscale or LAN IP):

powershell
scp "C:\path\to\file.docx" your-username@192.168.1.50:~/docs/
Later you can add WebDAV or an upload endpoint plus iOS Shortcuts if you want direct iPhone → server uploads.

Part 8 – Optional: HTTPS with Tailscale Certificates
This section describes how to secure Nginx with TLS so that when you access docs over the tailnet (not the public internet) you get a valid HTTPS connection.

8.1 Enable HTTPS certs in Tailscale
In the Tailscale admin console (<https://login.tailscale.com/admin/acls>), ensure HTTPS and certificates are enabled for your tailnet (if required by your plan).
​

Your machine has a MagicDNS hostname like server-name.yourtailnet.ts.net.

8.2 Obtain a Tailscale TLS certificate
On the server:

bash
sudo tailscale cert server-name.yourtailnet.ts.net
This writes server-name.yourtailnet.ts.net.crt and .key into the current directory.

Move them to a suitable location:

bash
sudo mkdir -p /etc/tailscale-certs
sudo mv server-name.yourtailnet.ts.net.crt /etc/tailscale-certs/
sudo mv server-name.yourtailnet.ts.net.key /etc/tailscale-certs/
sudo chmod 600 /etc/tailscale-certs/server-name.yourtailnet.ts.net.key
Tailscale will renew the cert automatically when you re‑run tailscale cert (you can set up a cron/systemd timer to refresh before expiry if desired).

8.3 Configure Nginx for HTTPS on tailnet
Edit Nginx site again:

bash
sudo nano /etc/nginx/sites-available/default
Example combined HTTP + HTTPS config:

text
server {
    listen 80;
    server_name_;

    # Optional: redirect HTTP on tailnet hostname to HTTPS
    if ($host = server-name.yourtailnet.ts.net) {
        return 301 https://$host$request_uri;
    }

    location /docs/ {
        alias /home/your-username/docs/;
        autoindex on;
    }
}

server {
    listen 443 ssl;
    server_name server-name.yourtailnet.ts.net;

    ssl_certificate     /etc/tailscale-certs/server-name.yourtailnet.ts.net.crt;
    ssl_certificate_key /etc/tailscale-certs/server-name.yourtailnet.ts.net.key;

    location /docs/ {
        alias /home/your-username/docs/;
        autoindex on;
    }
}
Port 80 serves docs on LAN as before.

Port 443 serves HTTPS for your tailnet hostname using Tailscale’s cert.

Test and reload:

bash
sudo nginx -t
sudo systemctl reload nginx
8.4 Access docs over HTTPS via tailnet
From any Tailscale‑joined device (phone/laptop):

Make sure Tailscale is active.

In browser:

text
<https://server-name.yourtailnet.ts.net/docs/>
You should see a valid HTTPS lock because the cert is trusted (issued via Tailscale’s CA) and traffic stays entirely inside your tailnet.

Final model:

Home LAN: <http://192.168.1.50/docs/> (or LAN HTTPS if you want) – no SSH needed.

Outside home: join tailnet with Tailscale app, then <https://server-name.yourtailnet.ts.net/docs/> – secure HTTPS over the tailnet; use SSH/Tailscale SSH for shell work as in earlier parts.
​

Quick Reference – Day‑to‑day Workflow
Work sessions (Claude Code, general dev)
From Windows or iOS:

bash
ssh <your-username@100.x.x.x>
tmux attach -t claudecode   # or: tmux new -s claudecode
cd ~/simantha-opcua
source venv/bin/activate
claude
Detach without killing session: Ctrl+B, then D.
​

Docs access
Home LAN (no SSH):

<http://192.168.1.50/docs/>

Outside home (via Tailscale):

Ensure Tailscale is connected on device.

<https://server-name.yourtailnet.ts.net/docs/>

Add files by copying them into ~/docs via scp or future WebDAV/Shortcuts flow, then read them from browser on phone/laptop.

If this still doesn’t copy cleanly, tell me exactly what app you’re pasting into (VS Code, Notepad, etc.) and what breaks (e.g., extra spaces, missing lines). I’ll adapt to that environment specifically so you aren’t fighting the tooling.
