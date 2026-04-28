import scrapy


# 搜集的问题
class QuestionIdItem(scrapy.Item):

    question_id = scrapy.Field()  # 问题ID


class KnowledeAdItem(scrapy.Item):

    url = scrapy.Field()


class QuestionInfoItem(scrapy.Item):

    question_id = scrapy.Field()  # 问题ID
    question_name = scrapy.Field()  # 问题名称


class AnswerItem(scrapy.Item):

    question_id = scrapy.Field()  # 问题 ID
    content = scrapy.Field()  # 回答的内容
