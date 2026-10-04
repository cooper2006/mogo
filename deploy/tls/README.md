# TLS Certificates

Place your certificate pair here to enable HTTPS for the MOGO gateway.

## Files required

| File | Description |
|------|-------------|
| `fullchain.pem` | Full certificate chain (cert + intermediates) |
| `privkey.pem` | Private key |

## Usage

1. **Enable HTTPS** — copy the HTTPS template:
   ```bash
   cp deploy/docker/nginx-https.conf deploy/docker/nginx.conf
   ```

2. **Uncomment the HTTPS port** in `docker-compose.yml`:
   ```yaml
   ports:
     - "${MOGO_PORT:-3000}:80"
     - "${MOGO_HTTPS_PORT:-443}:443"   # uncomment this line
   ```

3. **Place certificates** in this directory, or set `MOGO_TLS_CERTS_DIR`:
   ```bash
   openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
     -keyout privkey.pem -out fullchain.pem \
     -subj "/CN=mogo.local"
   ```

4. **Restart**:
   ```bash
   docker compose down && docker compose up -d
   ```

## Custom certificate directory

Set `MOGO_TLS_CERTS_DIR` in your `.env` to point to an alternate location:
```
MOGO_TLS_CERTS_DIR=/etc/letsencrypt/live/example.com
```
