"""IN-PROCESS loopback wire-shape exerciser for x402 v2 and MPP charge.

Runs actual HTTP 402 challenge/response headers, but no facilitator, network
settlement, real payment credential, or standard-compliant wallet signature.
Mock HMACs authenticate only against this ephemeral sandbox server.
Never connect it to an externally reachable address or real funds.
"""
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from .model import canonical


def b64(obj) -> str:
    return base64.urlsafe_b64encode(canonical(obj).encode()).rstrip(b"=").decode()


def unb64(s):
    return json.loads(base64.urlsafe_b64decode(s+"="*(-len(s)%4)))


def mac(secret:bytes, fields:dict) -> str:
    return hmac.new(secret,canonical(fields).encode(),hashlib.sha256).hexdigest()

class PaidResource(BaseHTTPRequestHandler):
    server_version="PaidAuditBench-MOCK/0.1"
    def log_message(self, *args): pass

    def respond(self,code:int,body:dict,headers:dict|None=None):
        data=canonical(body).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store")
        for name,value in (headers or {}).items(): self.send_header(name,value)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path not in ("/x402/task", "/mpp/task"):
            return self.respond(404,{"error":"unknown resource"})
        protocol="x402" if self.path.startswith("/x402/") else "mpp"
        if protocol=="x402":
            accepted={"scheme":"exact","network":"eip155:84532", "amount":"100", "asset":"SIMULATED_ONLY", "payTo":"sandbox:provider", "maxTimeoutSeconds":60}
            required={"x402Version":2,"resource":{"url":self.path},"accepts":[accepted],"extensions":{}}
            signed=self.headers.get("PAYMENT-SIGNATURE")
            if not signed:
                return self.respond(402,{"error":"payment_required"},{"PAYMENT-REQUIRED":b64(required)})
            try:
                payload=unb64(signed)
                proof=payload["payload"]
                nonce=proof["nonce"]
                details={"resource":payload["resource"],"accepted":payload["accepted"],"nonce":nonce}
                if (payload["x402Version"]!=2 or payload["accepted"]!=accepted or
                    details["resource"]!={"url":self.path} or
                    len(nonce)<16 or not hmac.compare_digest(proof["mock_hmac"],mac(self.server.secret,details))):
                    return self.respond(403,{"error":"bad mock authorization"})
                with self.server.lock:
                    if (protocol,nonce) in self.server.used:
                        return self.respond(409,{"error":"mock replay blocked"})
                    self.server.used.add((protocol,nonce))
                receipt={"success":True,"transaction":"MOCK-NO-CHAIN","network":"eip155:84532","payer":"sandbox:client"}
                return self.respond(200,{"task":"fictional paid API response", "scheme":"x402"},
                                    {"PAYMENT-RESPONSE":b64(receipt)})
            except (ValueError,TypeError,KeyError,UnicodeError,base64.binascii.Error):
                return self.respond(403,{"error":"malformed mock credential"})
        request={"amount":"100","currency":"SIM_CREDITS","recipient":"sandbox:provider"}
        request_b64=b64(request)
        fields={"realm":"localhost","method":"mock","intent":"charge","request":request_b64}
        challenge={"id":mac(self.server.secret,fields),**fields}
        auth=self.headers.get("Authorization","")
        if not auth.startswith("Payment "):
            header=f'Payment id="{challenge["id"]}", realm="localhost", method="mock", intent="charge", request="{request_b64}"'
            return self.respond(402,{"error":"payment_required"},{"WWW-Authenticate":header})
        try:
            cred=unb64(auth[len("Payment "):])
            if cred["challenge"]!=challenge:
                return self.respond(403,{"error":"challenge mismatch"})
            proof=cred["payload"]
            nonce=proof["nonce"]
            if len(nonce)<16 or not hmac.compare_digest(proof["mock_hmac"],mac(self.server.secret,{"challenge":challenge,"nonce":nonce})):
                return self.respond(403,{"error":"bad mock payment credential"})
            with self.server.lock:
                if (protocol,nonce) in self.server.used:
                    return self.respond(409,{"error":"mock replay blocked"})
                self.server.used.add((protocol,nonce))
            receipt={"status":"success","method":"mock","reference":"MOCK-NO-CHAIN","timestamp":"simulated"}
            return self.respond(200,{"task":"fictional paid API response", "scheme":"mpp"},
                                {"Payment-Receipt":b64(receipt)})
        except (ValueError,TypeError,KeyError,UnicodeError,base64.binascii.Error):
            return self.respond(403,{"error":"malformed mock credential"})

class SandboxHTTP(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1",0),PaidResource)
        self.secret=secrets.token_bytes(32)
        self.used=set()
        self.lock=threading.Lock()
        self.runner=None
    def __enter__(self):
        self.runner=threading.Thread(target=self.serve_forever,daemon=True)
        self.runner.start()
        return self
    def __exit__(self,typ,value,tb):
        self.shutdown()
        self.server_close()
        self.runner.join(timeout=5)


def smoke_once(srv:SandboxHTTP, protocol:str, attack:str="none") -> dict:
    """Send genuine HTTP requests; construct deliberately MOCK credentials locally.
    The server's secret is only known to this built-in test wallet; real payments
    would instead use scheme-specific wallets, signing methods and verification.
    """
    if protocol not in ("x402","mpp"):
        raise ValueError("wire smoke supported for x402/mpp only")
    url=f"http://127.0.0.1:{srv.server_port}/{protocol}/task"
    try:
        with urlopen(url,timeout=3) as r:
            raise AssertionError("unpaid resource unexpectedly accessible")
    except HTTPError as e:
        if e.code != 402:raise
        challenge_header=e.headers.get("PAYMENT-REQUIRED" if protocol=="x402" else "WWW-Authenticate")
        if not challenge_header:raise AssertionError("no payment challenge")
    nonce=secrets.token_hex(16)
    if protocol=="x402":
        req=unb64(challenge_header)
        accepted=req["accepts"][0].copy()
        if attack=="alter_amount": accepted["amount"]="999"
        details={"resource":{"url":"/x402/task"},"accepted":accepted,"nonce":nonce}
        signed={"x402Version":2,"resource":details["resource"],"accepted":accepted,
                "payload":{"nonce":nonce,"mock_hmac":mac(srv.secret,details)},"extensions":{}}
        headers={"PAYMENT-SIGNATURE":b64(signed)}
    else:
        # Parsed parameters are safe in this fixture: no escaping in emitted values.
        import re
        c=dict(re.findall(r'([a-z]+)="([^"]+)"',challenge_header))
        if attack=="alter_amount":
            rq=unb64(c["request"])
            rq["amount"]="999"
            c["request"]=b64(rq)
        proof={"nonce":nonce,"mock_hmac":mac(srv.secret,{"challenge":c,"nonce":nonce})}
        headers={"Authorization":"Payment "+b64({"challenge":c,"payload":proof})}
    def try_request():
        try:
            with urlopen(Request(url,headers=headers),timeout=3) as r:
                return r.status, dict(r.headers),json.loads(r.read())
        except HTTPError as e:
            return e.code, dict(e.headers),json.loads(e.read())
    status,h,b=try_request()
    again,_,_=try_request() if status==200 else (None,None,None)
    return {"protocol":protocol,"challenge_status":402,"credential_status":status,
            "replay_status":again,"attack":attack,"headers":{
                "challenge":"PAYMENT-REQUIRED" if protocol=="x402" else "WWW-Authenticate",
                "authorization":"PAYMENT-SIGNATURE" if protocol=="x402" else "Authorization: Payment",
                "receipt":"PAYMENT-RESPONSE" if protocol=="x402" else "Payment-Receipt"},
            "response":b,"real_settlement":False,"actual_cryptographic_wallet":False}
