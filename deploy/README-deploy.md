# Deployment notes

## The host must be able to reach the speaker

The app connects **out** to the speaker on two ports:

- `tcp/8090` — HTTP control API
- `tcp/8080` — the "gabbo" WebSocket push feed (live updates)

Whatever host runs the container must be able to route to the speaker's IP on those ports.
Check from the intended host:

```bash
curl -s -o /dev/null -w "%{http_code}\n" --max-time 5 http://<speaker-ip>:8090/info   # want 200
```

If that times out, the host cannot reach the speaker and the app will load but control
nothing. Fix the routing first (see the UniFi note below), or run the container on a host
that shares the speaker's subnet.

### UniFi: allowing a server VLAN to reach the speaker

If the speaker and the server are on different UniFi networks/VLANs, inter-VLAN traffic is
often blocked. To allow just the server to reach just the speaker:

1. **UniFi Network → Settings → Firewall & Security** (or **Security → Traffic & Firewall
   Rules** in newer versions).
2. Add an **allow** rule, placed **above** any block-inter-VLAN rule:
   - Source: the server's IP (e.g. `192.168.20.10/32`)
   - Destination: the speaker's IP (e.g. `192.168.10.20/32`), ports `8090,8080` (TCP)
   - Action: Accept. Return traffic is covered by established/related.
3. If the speaker sits on a **Guest** network, move it to a standard network — Guest
   networks are isolated by design and can't be reached across VLANs.
4. Also check the speaker network for **Client Device Isolation**; if on, it blocks this.

Verify again with the `curl` above from the server, then deploy.

## Port 80 already in use (e.g. Apache/Nextcloud)

The bundled `proxy` service binds port 80. If the host already serves something there:

- Run **only** the app service: `docker compose up -d --build app`
  (it listens on the internal network; publish a port if needed, e.g. add
  `ports: ["5001:5001"]`).
- Add a `/bose` route to the **existing** proxy. The essentials, translated per server:

  **Apache** (`a2enmod proxy proxy_http proxy_wstunnel`):
  ```apache
  ProxyPreserveHost On
  RequestHeader set X-Forwarded-Prefix "/bose"
  # SSE + WebSocket: no buffering, long timeout
  <Location /bose/>
      ProxyPass        http://<app-host>:5001/ flushpackets=on timeout=3600
      ProxyPassReverse http://<app-host>:5001/
  </Location>
  RedirectMatch 301 ^/bose$ /bose/
  ```

  **nginx**: copy the `location /bose/` block from `deploy/nginx.conf`.

The app reads `X-Forwarded-Prefix` to mount itself under the subpath, so the proxy must set
that header and strip the prefix (trailing-slash `proxy_pass`, as shown).
