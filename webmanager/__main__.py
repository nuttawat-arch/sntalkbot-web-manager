import os
import uvicorn

if __name__ == '__main__':
    # The FastAPI process stays on a private loopback backend.  The stable
    # Guardian owns SNWEB_BIND/SNWEB_PORT and proxies to this socket so Web
    # Manager can restart during self-update without exposing a raw 502.
    uvicorn.run(
        'webmanager.app:app',
        host=os.getenv('SNWEB_APP_BIND', '127.0.0.1'),
        port=int(os.getenv('SNWEB_APP_PORT', '28766')),
        workers=1,
        proxy_headers=True,
        forwarded_allow_ips=os.getenv('SNWEB_FORWARDED_ALLOW_IPS', '127.0.0.1'),
    )
