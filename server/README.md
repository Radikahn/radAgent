# Chat server

[Garage](https://garagehq.deuxfleurs.fr), a small self-hosted S3, holding radagent's chats so every device sees the
same ones: their conversations, memory and cards. Each device runs its own agent, and they all read and write one
bucket on your server.

## Set up

On the server, with Docker:

```sh
cd server
./setup.sh             # writes .env with fresh secrets and prints what the agent needs
docker compose up -d
```

Garage creates the `radagent` bucket and its key on first start. That key can also create buckets, which the agent
never needs, so take that away:

```sh
docker compose exec garage /garage key deny --create-bucket <GARAGE_DEFAULT_ACCESS_KEY from .env>
```

Then, on each device, add the lines `setup.sh` printed to `agent/.env`:

```sh
RADAGENT_S3_ENDPOINT=http://<server>:3900
RADAGENT_S3_BUCKET=radagent
RADAGENT_S3_REGION=garage
RADAGENT_S3_ACCESS_KEY=GK...
RADAGENT_S3_SECRET_KEY=...
```

Requests are signed for Garage's region, so `RADAGENT_S3_REGION=garage` has to match `s3_region` in `garage.toml`.
With `RADAGENT_S3_BUCKET` unset, the agent keeps chats in `agent/.agent/chats` as before. The layout is the same in
both, so existing chats move over with one copy (the key's credentials go to the AWS CLI for this command only):

```sh
AWS_ACCESS_KEY_ID=GK... AWS_SECRET_ACCESS_KEY=... aws s3 sync agent/.agent/chats s3://radagent/chats --endpoint-url http://<server>:3900 --region garage
```

## Reaching it from your devices

Only the S3 API (port 3900) leaves the container. Garage's cluster port (3901) is never published, and the admin API
is turned off. By default 3900 listens on the server's localhost only.

### Tailscale (recommended)

If every device is yours, put them on [Tailscale](https://tailscale.com) (or plain WireGuard) and don't expose
anything. Set `S3_BIND` in `.env` to the server's Tailscale IP (`tailscale ip -4`), run `docker compose up -d`, and use
`http://<that IP>:3900` as the endpoint. Garage stays unreachable from the internet, traffic between devices is
encrypted by WireGuard, and it works from anywhere your devices are, phones included.

To get HTTPS inside the tailnet too, leave `S3_BIND=127.0.0.1` and let Tailscale proxy it:
`tailscale serve --bg --https=8443 http://127.0.0.1:3900`, with `https://<machine>.<tailnet>.ts.net:8443` as the
endpoint. This needs HTTPS certificates turned on for your tailnet.

### The public internet

Exposing S3 itself is reasonable. It's built for the open internet: there's no login page to guess at, and every
request is signed with the secret key, a random 256-bit value. What makes it safe or not is how you expose it:

- **Only behind TLS.** The signature proves who sent a request but doesn't hide what's in it, so over plain HTTP
  anyone on the path can read your chats.
- **Only port 3900.** Port 3901 controls the cluster; `docker-compose.yml` doesn't publish it, so keep it that way.
- **A key scoped to the one bucket**, with bucket creation denied as above.

What you still accept: Garage is reachable by anyone, so a bug in it would be too (keep the image current); a key
leaked from one device can read every chat until you rotate it; and the server's IP is public.

The `public` profile puts [Caddy](https://caddyserver.com) in front of Garage, with a Let's Encrypt certificate it
renews itself:

1. Point a DNS name (e.g. `s3.example.com`) at the server, and forward ports 80 and 443 to it.
2. Set `S3_DOMAIN=s3.example.com` in `.env`.
3. `docker compose --profile public up -d`
4. Use `https://s3.example.com` as the endpoint.

If you'd rather not open ports, a Cloudflare Tunnel to `http://127.0.0.1:3900` works too and hides the server's IP.
But Cloudflare decrypts the traffic at its edge, so it can see your chats.

## Rotating the key

If a device with the key is lost, or the key leaks, replace it. Garage won't start while `.env` names a key that
was deleted, so put the new key in `.env` before deleting the old one:

1. In `.env`, set `GARAGE_DEFAULT_ACCESS_KEY` to `GK` + `openssl rand -hex 16` and `GARAGE_DEFAULT_SECRET_KEY` to
   `openssl rand -hex 32`.
2. `docker compose up -d`. Garage creates the new key and gives it the existing bucket.
3. `docker compose exec garage /garage key deny --create-bucket <new key>`
4. `docker compose exec garage /garage key delete --yes <old key>`
5. Update `agent/.env` on each device.

## Backups

Everything is in `./data`: `meta/` (Garage's index, which it also snapshots every 6 hours) and `data/` (the objects).
There is one copy, so back it up. Stop Garage first so the copy is consistent:

```sh
docker compose stop garage && tar czf radagent-$(date +%F).tgz data && docker compose start garage
```

## Good to know

- Each chat should have one writer at a time. Two devices answering in the same chat at once means the last snapshot
  saved wins.
- When the server can't be reached, the app says so, and the chat list and new messages wait until it's back.
  Nothing is cached locally yet.
