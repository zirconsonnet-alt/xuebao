import re
import time
import random

compileUpper = re.compile(r'[A-Z]')
"""工具类"""


class Tool:

    def __init__(self):
        pass

    def get_format_time(self, timestamp=None, format=r"%Y-%m-%d %H:%M"):
        time_array = time.localtime(timestamp)
        return time.strftime(format, time_array)

    # 根据传入的时间，转换成秒的格式
    def get_mill_time(self, time_str, format=r'%Y-%m-%d %H:%M:%S'):
        timestamp = time.mktime(time.strptime(time_str, format))

        # 将时间戳转换为秒数
        return int(timestamp)

    def switch_status(self, bool):
        if bool:
            return '是'
        else:
            return '否'

    # 字段转换
    def name_to_snake(self, name, type):
        if type == 0:
            return name
        """驼峰转下划线"""
        if '_' not in name:
            name = re.sub(r'([a-z])([A-Z])', r'\1_\2', name)
        else:
            raise ValueError(f'{name}字符中包含下划线，无法转换')
        return name.lower()

    def translate_chars(self, str):
        if str:
            return str.replace("\n", "").replace(",", '，')
        return ''

    # 对象的key驼峰转换成下划线
    def translate_obj_chars(self, obj):
        temp_obj = {}
        for key in obj:
            if compileUpper.findall(key):
                key_line = re.sub(r"(?P<key>[A-Z])", r"_\g<key>", key)
                new_key = key_line.lower().strip('_')
            else:
                new_key = key
            temp_obj[new_key] = obj.get(key)
        return temp_obj

    # 组装首页数据
    def format_first_page_data(self, a_ids, a_map, q_id):
        print("开始-组装id为<{}>的数据...".format(q_id))
        for i in range(0, len(a_ids)):
            a_ids[i] = self.translate_obj_chars(a_ids[i])
            target_id = a_ids[i].get('target')
            target = a_map.get(str(target_id))
            a_ids[i]['target'] = self.translate_obj_chars(target)
        print("结束-共组装id为<{}>的数据{}条".format(q_id, len(a_ids)))
        return a_ids

    # 提取数组中的topic名称
    def format_array_data(self, topics):
        result = ''
        length = len(topics)
        for index in range(0, length):
            result += topics[index].get('name', '')
            if index < length - 1:
                result += '，'

        return result

    # 提取数组中的topic名称
    def get_question_id(self, url):
        if url:
            match = re.search(r'\d+', url)
            return match.group()
        else:
            return ''

    # 休眠几秒，防止封号
    def sleep_delay(self, start=5, end=10):
        sleep = random.randint(start, end)
        print('我要休眠几秒：%d秒...' % (sleep))
        time.sleep(sleep)  # 下次请求之前随机暂停几秒，防止被封号
        print('我醒了')
