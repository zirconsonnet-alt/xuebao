import os
from itemadapter import ItemAdapter
from .settings import DATA_URI, DATA_URI


class QuestionIdPipeline():

    def open_spider(self, spider):
        if spider.name == 'searchSpider':

            data_dir = os.path.join(DATA_URI)
            #判断文件夹存放的位置是否存在，不存在则新建文件夹
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)
            file_path = data_dir + '/question_ids.csv'
            # 'w'模式每次运行爬虫后数据会覆盖，'a'是追加
            self.file = open(file_path, 'w', encoding='utf-8')

    def close_spider(self, spider):  # 在关闭一个spider的时候自动运行
        if spider.name == 'searchSpider':
            self.file.close()

    def process_item(self, item, spider):
        try:
            if spider.name == 'searchSpider' and item['key'] == 'questionId':
                question_line = '{}\n'.format(
                    item.get('item').get('question_id', ''))
                self.file.write(question_line)
        except BaseException as e:
            print("QuestionId错误在这里>>>>>>>>>>>>>", e, "<<<<<<<<<<<<<错误在这里")
        return item


class KnowledeAdPipeline():

    def open_spider(self, spider):
        if spider.name == 'searchSpider':
            data_dir = os.path.join(DATA_URI)
            #判断文件夹存放的位置是否存在，不存在则新建文件夹
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)
            file_path = data_dir + '/knowledeAd_urls.csv'
            # 'w'模式每次运行爬虫后数据会覆盖，'a'是追加
            self.file = open(file_path, 'w', encoding='utf-8')

    def close_spider(self, spider):  # 在关闭一个spider的时候自动运行
        if spider.name == 'searchSpider':
            self.file.close()

    def process_item(self, item, spider):
        try:
            if spider.name == 'searchSpider' and item['key'] == 'knowledge_ad':
                url = '{}\n'.format(item.get('item').get('url', ''))
                self.file.write(url)
        except BaseException as e:
            print("KnowledeAd错误在这里>>>>>>>>>>>>>", e, "<<<<<<<<<<<<<错误在这里")
        return item


class SearchResultPipeline():

    def open_spider(self, spider):
        if spider.name == 'searchSpider':
            data_dir = os.path.join(DATA_URI)
            #判断文件夹存放的位置是否存在，不存在则新建文件夹
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)
            file_path = data_dir + '/search_result_urls.csv'
            # 'w'模式每次运行爬虫后数据会覆盖，'a'是追加
            self.file = open(file_path, 'w', encoding='utf-8')

    def close_spider(self, spider):  # 在关闭一个spider的时候自动运行
        if spider.name == 'searchSpider':
            self.file.close()

    def process_item(self, item, spider):
        try:
            if spider.name == 'searchSpider' and item['key'] == 'search_result':
                url = '{}\n'.format(item.get('item').get('url', ''))
                self.file.write(url)
        except BaseException as e:
            print("KnowledeAd错误在这里>>>>>>>>>>>>>", e, "<<<<<<<<<<<<<错误在这里")
        return item
