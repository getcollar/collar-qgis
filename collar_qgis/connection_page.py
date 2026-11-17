"""Self-contained, credential-free browser confirmation served only on loopback."""
import base64
import hashlib
from pathlib import Path

SCRIPT = "document.getElementById('close').addEventListener('click', function () { window.close(); document.getElementById('fallback').hidden = false; });"
SCRIPT_HASH = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
SECURITY_HEADERS = ("Cache-Control: no-store\r\nReferrer-Policy: no-referrer\r\nX-Content-Type-Options: nosniff\r\nContent-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-" + SCRIPT_HASH + "'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'\r\n").encode('ascii')

def response_body(success):
    logo = (Path(__file__).parent / 'assets/wordmark.svg').read_text()
    title = 'Connected successfully' if success else 'Connection not completed'
    text = 'Your Collar account is now connected. You can return to QGIS and start working with your projects.' if success else 'Return to QGIS to review the connection message and try again.'
    icon = '✓' if success else '!'
    return ("""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Collar · """ + title + """</title><style>
    *{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:#f4f2ec;color:#173f35;font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
    main{width:100%;max-width:500px;border:1px solid #deded3;border-radius:20px;overflow:hidden;background:#fff;box-shadow:0 20px 70px #173f3510}
    header{padding:28px 36px;background:#173f35}header svg{display:block;width:150px;height:30px}.content{padding:36px;text-align:center}.check{margin:0 auto 24px;display:grid;place-items:center;width:58px;height:58px;background:#e9efe5;color:#173f35;border-radius:50%;font-size:28px}
    h1{font-size:26px;letter-spacing:-.7px;margin:0 0 14px;font-weight:600}p{font-size:15px;line-height:1.7;color:#56635d;margin:0 0 26px}button{border:0;border-radius:8px;background:#8aa37e;color:#132e25;padding:13px 24px;font:600 15px system-ui;cursor:pointer;width:100%}button:hover{background:#9bb390}button:focus-visible{outline:3px solid #173f35;outline-offset:4px}.foot{font-size:12px;color:#70796e;margin:18px 0 0}#fallback{margin-top:18px;margin-bottom:0}footer{padding:0 24px 24px;text-align:center;color:#70796e;font-size:12px}
    </style></head><body><main><header>""" + logo + """</header><div class="content"><div class="check" aria-hidden="true">""" + icon + """</div><h1>""" + title + """</h1><p>""" + text + """</p><button id="close" type="button">Close window</button><p id="fallback" hidden>You can close this tab manually and return to QGIS.</p><p class="foot">You can manage this connection in your Collar account.</p></div><footer>Collar for QGIS</footer></main><script>""" + SCRIPT + """</script></body></html>""").encode('utf-8')
