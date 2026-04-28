import random

BOT_NAME = 'zhihu'

SPIDER_MODULES = ['zhihu.spiders']
NEWSPIDER_MODULE = 'zhihu.spiders'

USER_AGENT_LIST = [
    "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36 OPR/26.0.1656.60",
    "Opera/8.0 (Windows NT 5.1; U; en)",
    "Mozilla/5.0 (Windows NT 5.1; U; en; rv:1.8.1) Gecko/20061208 Firefox/2.0.0 Opera 9.50",
    "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1; en) Opera 9.50",
    "Opera/9.80 (Macintosh; Intel Mac OS X 10.6.8; U; en) Presto/2.8.131 Version/11.11",
    "Opera/9.80 (Windows NT 6.1; U; en) Presto/2.8.131 Version/11.11",
    "Opera/9.80 (Android 2.3.4; Linux; Opera Mobi/build-1107180945; U; en-GB) Presto/2.8.149 Version/11.10",
    "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:34.0) Gecko/20100101 Firefox/34.0",
    "Mozilla/5.0 (X11; U; Linux x86_64; zh-CN; rv:1.9.2.10) Gecko/20100922 Ubuntu/10.10 (maverick) Firefox/3.6.10",
]
USER_AGENT = random.choice(USER_AGENT_LIST)
# Obey robots.txt rules
ROBOTSTXT_OBEY = False

# 在项处理器（也称为项目管道）中并行处理的并发项目的最大数量（每个响应）。
CONCURRENT_REQUESTS = 1

# Configure a delay for requests for the same website (default: 0)
# See https://docs.scrapy.org/en/latest/topics/settings.html#download-delay
# See also autothrottle settings and docs
DOWNLOAD_DELAY = 0  # "%.1f" % random.random()
RANDOMIZE_DOWNLOAD_DELAY = True
LOG_ENABLED = True
LOG_ENCODING = 'utf-8'
# 日志级别 CRITICAL, ERROR, WARNING, INFO, DEBUG
# LOG_LEVEL = 'ERROR'

# 将由Scrapy下载程序执行的并发（即同时）请求的最大数量。
# CONCURRENT_REQUESTS_PER_DOMAIN = 4
# 将对任何单个域执行的并发（即同时）请求的最大数量。
# CONCURRENT_REQUESTS_PER_IP = 4

# Disable cookies (enabled by default)
COOKIES_ENABLED = False

# Disable Telnet Console (enabled by default)
#TELNETCONSOLE_ENABLED = False

# Override the default request headers:
DEFAULT_REQUEST_HEADERS = {
    "accept": "*/*",
    "accept-language": "zh-CN,zh;q=0.9",
    "content-type": "application/json",
    "origin": "https://www.zhihu.com",
    "priority": "u=1, i",
    "referer": "https://www.zhihu.com/search?type=content&q=%E5%B1%9E%E4%B8%83%E5%92%8C%E5%BC%A6",
    "sec-ch-ua": "\"Google Chrome\";v=\"131\", \"Chromium\";v=\"131\", \"Not_A Brand\";v=\"24\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\"",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "x-requested-with": "fetch",
    "x-xsrftoken": "21qqfsrOfJ32mUo13sz9OTJqORUtP4nv",
    "x-zse-93": "101_3_3.0",
    "x-zse-96": "2.0_7dMmu0mT83lD9j6qBo0K1uTYGjHfpP8eq5XQOctSy8f4T8efOpjLQpOxgoAywISj",
    "x-zst-81": "3_2.0VhnTj77m-qofgh3TxTnq2_Qq2LYuDhV80wSL7iUZQ6nxEX20m4fBJCHMiqHPD4S1hCS974e1DrNPAQLYlUefii7q26fp2L2ZKgSfnveCgrNOQwXTt_Fq6DQye8t9DGwT9RFZQAuTLbHP2GomybO1VhRTQ6kp-XxmxgNK-GNTjTkxkhkKh0PhHix_F0P9QBtyirNGSerYcMS1areMDDVBYqeLb7Y1nJeY87xLQqo1wC38XGL_dwxLFH_zuGF82UtqGRcYSLXYTUw8-9HCqh20uqu0LUHxJTHGzJL0XCVYoDOsfBpmZgtBrioBEBcxFUN00CwGjvu1PhSfkcSG1B28qrHKo7gsBBXOnBe0CJNLWrSs"
}

MEDIA_ALLOW_REDIRECTS = True

HTTPERROR_ALLOWED_CODES = [302, 301, 401, 400, 403]

# 管道-处理数据使用
ITEM_PIPELINES = {
    'zhihu.pipelines.KnowledeAdPipeline': 300,
    'zhihu.pipelines.QuestionIdPipeline': 300,
    'zhihu.pipelines.SearchResultPipeline': 300,
}

# 下载中间件-例如开启代理
DOWNLOADER_MIDDLEWARES = {
    'zhihu.middlewares.RandomDelayMiddleware': 543,
}

# 获取到的数据的存放目录名称
DATA_URI = r'H:\Qbot\mybot\data\zhihu_keywords\zhihu\spiders\data_file'

CONFIG_LIST = [
    {
        'd_c0':
        "AQASveMVRBmPTqaJqD_QA_3oF9KeBJW6n20=|1726845870",
        'xZst81':
        "3_2.0VhnTj77m-qofgh3TxTnq2_Qq2LYuDhV80wSL7iUZQ6nxEX20m4fBJCHMiqHPD4S1hCS974e1DrNPAQLYlUefii7q26fp2L2ZKgSfnveCgrNOQwXTt_Fq6DQye8t9DGwT9RFZQAuTLbHP2GomybO1VhRTQ6kp-XxmxgNK-GNTjTkxkhkKh0PhHix_F0P9QBtyirNGSerYcMS1areMDDVBYqeLb7Y1nJeY87xLQqo1wC38XGL_dwxLFH_zuGF82UtqGRcYSLXYTUw8-9HCqh20uqu0LUHxJTHGzJL0XCVYoDOsfBpmZgtBrioBEBcxFUN00CwGjvu1PhSfkcSG1B28qrHKo7gsBBXOnBe0CJNLWrSs",
        "cookie":
        r"_zap=852278e3-d800-4eb6-9ac1-2da3bd1c0ffc; d_c0=AQASveMVRBmPTqaJqD_QA_3oF9KeBJW6n20=|1726845870; __snaker__id=tp64vaUAgYlRn4pK; q_c1=6feef68fda6f4fe6a13b36d3a7d59846|1726845944000|1726845944000; _xsrf=21qqfsrOfJ32mUo13sz9OTJqORUtP4nv; __zse_ck=004_pfIgB/Oomq2SlJKrqMK3s/Uv5UX1ak9DrgmwINXTSzX/=uWbHnnumTp7xO56ctd1fFPEoJBkSTohnUv4I1z6T6oivT9SJoYjEH0PaYZMjMdEnWzZiOQ/HgTxbOCeCiCB-QOO1qgQoqdTgAfwIb2b41I6/F3rpwEZftT8IqsfBVGt7w9kzk37NwQZ1wH+qWkCfRETrZ85cpbteSSmvUVtbvwHGpHTUeDecb6oI1bFpYYvrGPojHSZseIG0761GhCVY; Hm_lvt_98beee57fd2ef70ccdd5ca52b9740c49=1737429494; HMACCOUNT=D164181398243205; z_c0=2|1:0|10:1737429493|4:z_c0|80:MS4xM0lQTlZBQUFBQUFtQUFBQVlBSlZUZlZmZkdoMmo3Y3JieElVb3pJeU1zWklHOW84cWtwT2NBPT0=|1fa66fa03039607fc932a7d3cd108d0ebc6425c0d281c6575992f6daff32f304; Hm_lpvt_98beee57fd2ef70ccdd5ca52b9740c49=1737430157; BEC=4589376d83fd47c9203681b16177ae43; unlock_ticket=AGBSplrH_hgmAAAAYAJVTZUbj2cRe0JIodR2b9fLwYhbWEBr2SEK3g=="
    },
]

# 无登录cookie，无需更换
NO_LOGIN_COOKIE = r'_zap=76a55a14-dc24-47e6-976d-0327ca0d31b4; _xsrf=MT6tw8barcjvwSgScUIz7TGtbfmd6CCw; gdxidpyhxdE=i7cAoPQ3+tpCGeflThDc8h7o5S1IWQ60PpBHcX\d8qVampwlInqq5Vsz94+McnMIepECRE5Wbs7nAPiIDDeIglvhIN7G7HaOVRxNvXrRZMBdb3z6xk+fxCh/u9tRqs3aClqnri6tok+zCCraBpvYsxq1STrINLP1xB70U29JY8Wunte2:1680358457316; KLBRSID=81978cf28cf03c58e07f705c156aa833|1680357789|1680357311'

# 手动设置每一个id翻页的最大页码，例如限制同一个id翻页请求时控制前50页，此处可设置为50；负数时为不限制最大页码，则此时获取全部翻页数据
MAX_PAGE = 5

# 字符大于1000的回答
MAX_CHARS = 500

# 截止时间（获取回答的时间段范围：当前时间->截止时间）
STOP_DATE = '2010-01-01 00:00:00'
