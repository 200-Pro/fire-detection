"""Export only the public LAN root and verify HTTPS without altering OS trust."""
import argparse
import hashlib
import json
from pathlib import Path
import ssl
import time
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('--address', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
certificate = root / 'runtime/caddy/pki/authorities/local/root.crt'
for _ in range(30):
    if certificate.exists():
        break
    time.sleep(.2)
if not certificate.exists():
    raise SystemExit('LAN root not ready; inspect caddy.stderr.log.')
public = root / 'runtime/public'
public.mkdir(parents=True, exist_ok=True)
pem = certificate.read_text(encoding='utf-8')
der = ssl.PEM_cert_to_DER_cert(pem)
(public / 'ember-local-ca.crt').write_text(pem, encoding='ascii')
(public / 'ember-local-ca.cer').write_bytes(der)
fingerprint = hashlib.sha256(der).hexdigest().upper()
context = ssl.create_default_context(cafile=str(certificate))
origin = f'https://{args.address}:8443'
request = urllib.request.Request(origin+'/health/ready')
# Explicitly verify this CA and IP SAN; no global trust changes or verify=False.
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
for attempt in range(15):
    try:
        with opener.open(request, timeout=3) as response:
            ready = json.load(response)['ready']
        break
    except OSError:
        if attempt == 14:
            raise
        time.sleep(.2)
if not ready:
    raise SystemExit('HTTPS model not ready.')
summary = {'origin':origin,'certificate':str(public/'ember-local-ca.cer'),
           'certificate_sha256':fingerprint,'https_health_verified':True,
           'os_trust_changed':False,'firewall_changed':False}
(public / 'lan-setup.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary, indent=2))
