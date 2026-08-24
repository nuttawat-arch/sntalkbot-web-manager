import os
import uvicorn

if __name__ == '__main__':
    # Safe default: localhost only. Use SNWEB_BIND=0.0.0.0 explicitly for
    # standalone direct-IP access without a reverse proxy.
    uvicorn.run(
        'webmanager.app:app',
        host=os.getenv('SNWEB_BIND', '127.0.0.1'),
        port=int(os.getenv('SNWEB_PORT', '28765')),
        workers=1,
        proxy_headers=True,
        forwarded_allow_ips=os.getenv('SNWEB_FORWARDED_ALLOW_IPS', '127.0.0.1'),
    )
