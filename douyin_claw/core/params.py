from .dy_util import generate_webid, generate_msToken, splice_url, generate_a_bogus, generate_fake_webid


class Params:
    def __init__(self):
        self.params = {}

    def with_web_id(self, auth=None, url="", fake=False):
        webid = generate_fake_webid() if fake else generate_webid(auth, url)
        self.params["webid"] = webid
        return self

    def with_a_bogus(self, data=None):
        query = splice_url(self.get())
        data_str = splice_url(data) if data is not None else ""
        self.add_param("a_bogus", generate_a_bogus(query, data_str))
        return self

    def with_ms_token(self):
        self.params["msToken"] = generate_msToken()
        return self

    def add_param(self, key, value):
        self.params[key] = value
        return self

    def get(self):
        return self.params
