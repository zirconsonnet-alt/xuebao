import time
import random
import scrapy
from zhihu.Utils import Tool
from urllib.parse import urlencode
from zhihu.settings import MAX_PAGE, CONFIG_LIST, STOP_DATE
from ..items import QuestionIdItem, KnowledeAdItem
from zhihu.SignTool import Sign

tool = Tool()
signTool = Sign()
"""首页-综合搜索"""


class searchSpider(scrapy.Spider):
    name = 'searchSpider'
    allowed_domains = ['zhihu.com']
    # 截止时间
    stop_date = tool.get_mill_time(STOP_DATE)

    headers = {
        "topicity": "www.zhihu.com",
        "user-agent":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36",
        "x-zse-93": "101_3_3.0",
    }

    # 个人中心-关注-关注的问题列表_参数
    search_params = {
        "gk_version": "gz-gaokao",
        "t": "general",
        "q": "中国家长教育焦虑教育政策",
        "correction": "1",
        "offset": "0",
        "limit": "20",
        "filter_fields": "",
        "lc_idx": "0",
        "show_all_topics": "0",
        "search_source": "Normal"
    }

    referer = {
        'q': '',
        'type': 'content',
        'utm_content': 'search_history',
    }

    def start_requests(self):

        with open("../key_words.csv", "r", encoding="utf-8") as file:
            keys = file.readlines()
            for key in keys:
                key = key.replace('\n', '').replace(r" ", '')
                config = random.choice(CONFIG_LIST)
                self.search_params.update({'q': key})

                temp_url = signTool.get_search_sign_url(
                    self.search_params, config)
                self.referer.update({'q': key})

                self.headers.update({
                    'x-zse-96':
                    signTool.get_zst_96(temp_url),
                    "x-zst-81":
                    config.get('xZst81'),
                    'Cookie':
                    config.get('cookie'),
                    'referer':
                    "https://www.zhihu.com/search?{}".format(
                        urlencode(self.referer))
                })

                s_url = "https://www.zhihu.com/api/v4/search_v3?{}".format(
                    urlencode(self.search_params))

                yield scrapy.Request(s_url,
                                     headers=self.headers,
                                     callback=self.question_parse,
                                     meta={
                                         "page": 0,
                                         'key': key
                                     })
        print('所有 "关键词" request 预处理完成。')

    def question_parse(self, response):
        res = response.json()
        key = response.meta['key']
        page = response.meta['page']
        data_list = res.get('data', [])
        paging = res.get('paging')
        search_hash_id = res.get('search_action_info').get('search_hash_id')

        isEnd = paging.get('is_end')

        if isEnd and len(data_list) == 0:
            return

        for data_item in data_list:
            if data_item['type'] == 'relevant_query':
                continue

            target = data_item['object']
            if data_item['type'] == 'knowledge_result':
                item = QuestionIdItem()
                item['question_id'] = tool.get_question_id(target.get('url'))
                yield {'key': 'questionId', 'item': item}
            elif data_item['type'] == 'knowledge_ad':
                item = KnowledeAdItem()
                item['url'] = target.get('url')
                yield {'key': 'knowledge_ad', 'item': item}
            elif data_item['type'] == 'search_result':
                if target.get('type') == 'article':
                    item = KnowledeAdItem()
                    temp_id = tool.get_question_id(target.get('url'))
                    item['url'] = "https://zhuanlan.zhihu.com/p/{}".format(
                        temp_id)
                    yield {'key': 'search_result', 'item': item}
                elif target.get('type') == 'answer':
                    item = QuestionIdItem()
                    item['question_id'] = tool.get_question_id(
                        target.get('question').get('url'))
                    yield {'key': 'questionId', 'item': item}
            else:
                print('--logo--', data_item['type'])

        if MAX_PAGE > 0 and MAX_PAGE - 1 <= page:
            return

        if not paging.get('is_end'):

            offset = (page + 1) * 20
            config = random.choice(CONFIG_LIST)
            self.search_params.update({
                'offset': str(offset),
                'lc_idx': str(offset),
                'search_hash_id': search_hash_id,
                'vertical_info': '0,0,0,0,0,0,0,0,0,0',
            })
            temp_url = signTool.get_search_sign_url(self.search_params, config)
            self.headers.update({
                "referer":
                "https://www.zhihu.com/search?{}".format(
                    urlencode(self.referer)),
                'x-zse-96':
                signTool.get_zst_96(temp_url),
                "x-zst-81":
                config.get('xZst81'),
                'Cookie':
                config.get('cookie'),
            })

            s_url = "https://www.zhihu.com/api/v4/search_v3?{}".format(
                urlencode(self.search_params))

            yield scrapy.Request(s_url,
                                 headers=self.headers,
                                 callback=self.question_parse,
                                 meta={
                                     "page": page + 1,
                                     'key': key
                                 })
