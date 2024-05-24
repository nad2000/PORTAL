## Issue a "Let's Encrypt" cert for multiple domains

```bash

 sudo certbot  -d pmspp.prodata.nz -d xn--twhia-fwa.prodata.nz -d  ttm.prodata.nz -d international.prodata.nz -d puanga.prodata.nz -d stlp.prodata.nz

```


## Reject request with incorrect Host header (not matching the host domain names or empty)

```config

server {
        listen 80 default_server;
        listen [::]:80 default_server;

        listen 443 ssl default_server;
        listen [::]:443 ssl default_server;

        ssl_certificate /etc/letsencrypt/live/pmspp.prodata.nz/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/pmspp.prodata.nz/privkey.pem;
        include /etc/letsencrypt/options-ssl-nginx.conf;
        ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

        server_name _;
        server_name "";

        return 444;
}
```
