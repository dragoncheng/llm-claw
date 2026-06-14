import json
import base64

from .dy_util import trans_cookies, generate_msToken, generate_verify_fp


class DouyinAuth:
    def __init__(self):
        self.cookie = None
        self.cookie_str = None
        self.private_key = None
        self.ticket = None
        self.ts_sign = None
        self.client_cert = None
        self.ree_public_key = None
        self.uid = None
        self.msToken = None

    def prepare_auth(self, cookie_str: str, web_protect_: str = "", keys_: str = ""):
        self.cookie = trans_cookies(cookie_str)
        self.cookie_str = cookie_str
        self.msToken = self.cookie.get("msToken") or generate_msToken()
        self.cookie["msToken"] = self.msToken
        if not self.cookie.get("s_v_web_id"):
            self.cookie["s_v_web_id"] = generate_verify_fp()
        self.cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookie.items())
        if web_protect_:
            web_protect_ = json.loads(json.loads(web_protect_)["data"])
            self.ticket = web_protect_["ticket"]
            self.ts_sign = web_protect_["ts_sign"]
            self.client_cert = web_protect_["client_cert"]
        if keys_:
            keys_ = json.loads(json.loads(keys_)["data"])
            self.private_key = keys_["ec_privateKey"]
            self.ree_public_key = base64.b64encode(self.private_key.encode()).decode()
