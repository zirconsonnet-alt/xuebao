import execjs
from urllib.parse import urlencode
"""工具类"""


class Sign:

    def __init__(self):
        pass

    # 问题-回答 签名str
    def get_answer_sign_url(self, id, p, config):
        return '101_3_3.0+/api/v4/questions/{}/feeds?{}+{}'.format(
            id, urlencode(p), config.get('d_c0'))

    # search
    def get_search_sign_url(self, p, config):

        return '101_3_3.0+/api/v4/search_v3?{}+{}+{}'.format(
            urlencode(p), config.get('d_c0'), config.get('xZst81'))

    # 获取到96加密结果
    def get_zst_96(self, s):
        with open('../Signature.js', encoding="utf-8") as file:
            value = execjs.compile(file.read()).call('get_signature', s)
            return value