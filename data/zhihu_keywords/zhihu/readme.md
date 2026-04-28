# 项目说明手册

## 依赖安装

1. scrapy
2. bs4
3. PyExecJS
4. pymysql
5. DBUtils

> 安装方式举例：pip install scrapy

> 上述安装需要确保 python 已经正确安装

## 如何运行

1. 需要确认电脑是否安装了 python 的运行环境，如果没有安装请安装并保证环境无异常。快捷安装方案：下载 vscode 编辑器，插件>python>安装即可；
2. 控制台进入目录./zhihu/spiders/，运行命令 scrapy crawl 爬虫名称
   > 爬虫名称在 xxSpider.py 文件中的 name 字段名称，例如 fqSpider.py 文件中的 name = 'fqSpider'，运行命令 scrapy crawl fqSpider

## 注意事项

1. qaSpider.py 运行该爬虫前，请先运行 fqSpider.py 、thSpider.py，因为 qaSpider.py 这个需要前两个爬虫的结果(问题 id)
2. 爬取速度不要太快，快了容易封号，建议设置每次请求完后的延时不低于 2s，时间阀值设置位置./settings.py > DOWNLOAD_DELAY = 2， 代表延时 2 秒再发起下一个请求
3. 如果 fqSpider.py 、thSpider.py 获取到很多的问题 id 需要爬，建议把这些 id 几十个分成一组，这样中途失败后知道哪个失败了容易重启爬虫。由于分布式、多线程爬虫，数据回来的顺序也是随机的，一旦账号被反扒之后，可能会出现多个请求无数据的情况，因此建议分组获取数据，如果请求异常影响范围会比较小；
4. fqSpider.py 、thSpider.py 的结果保存在两个不同的文件名下，所以当 qaSpider.py 爬完一个文件的问题 id 后需要更换到另一个，更换位置 qaSpider.py 文件中的` with open("./data_file/topic_hot_question_ids.csv", "r",` 中的`topic_hot_question_ids.csv`名称即可

## 目录、文件

从该 readme.md 所在目录说起，顺序由上至下

1. zhihu: 项目文件夹目录
2. spiders: 爬虫文件目录

   2.1 data_file 爬虫获取到的结果目录

   > 2.1.1 answer.csv 回答结果文件

   > 2.1.2 question_info.csv 问题详情文件

   > 2.1.3 topic_hot_question_ids.csv 话题问题列表 id 文件

   > 2.1.4 user_info.csv 参与回答的用户文件

   2.2 \_\_init\_\_: 项目自带文件，忽略

   2.3 fqSpider.py: 全称 following questions，问题 id 列表 爬虫

   2.4 qaSpider.py: 问题详情、回答、用户信息 爬虫

   2.5 thSpider.py: th 全称 topic hot，话题 id 列表 爬虫

3. \_\_init\_\_: 项目自带文件，忽略
4. author_ids.csv: 待爬用户的 urlToken
5. item.py: 项目文件
6. middlewares.py: 项目文件
7. pipelines.py: 项目文件
8. readme.md: 说明文件
9. settings.py: 项目配置文件
10. Signature.js: 加密文件
11. SignTool.py: 格式化验签字符串工具类
12. topic_ids.py: 待爬话题的 id
13. Utils.py: 工具类

# 个人中心

1. 个人中心 https://www.zhihu.com/people/zhao-hang-2-26/following/questions
2. 问题列表 https://www.zhihu.com/api/v4/members/zhao-hang-2-26/following-questions?include=data%5B*%5D.created%2Canswer_count%2Cfollower_count%2Cauthor&offset=20&limit=20
3. 保存问题 ID 到 csv 文件
4. 根据 csv 文件的 id 请求问题详情，得到问题回答列表 https://www.zhihu.com/question/345788671
5. 回答内容翻页（第一页没有） https://www.zhihu.com/api/v4/questions/384272973/feeds

# 话题

1. 话题>讨论 https://www.zhihu.com/topic/19554143/hot
2. 问题列表 https://www.zhihu.com/api/v5.1/topics/19554143/feeds/essence?offset=10&limit=10&
3. 保存问题 ID 到 csv 文件
4. 根据 csv 文件的 id 请求问题详情，得到问题回答列表 https://www.zhihu.com/question/345788671
5. 回答内容翻页（第一页没有） https://www.zhihu.com/api/v4/questions/384272973/feeds

---

# 迭代版本

1. spiders 文件夹中新增 xxxRun.py，该文件是对应爬虫的执行文件，控制台直接 python xxxRun.py 即可执行；
2. answerSpider.py 是单个回答详情爬虫，获取对应回答的详细数据，例如：评论，点赞，发布日期，编辑日期；该文件需要读取 answer_urls.csv 文件中的链接；
3. novelSpider.py 是获取小说信息详情的爬虫，获取对应的点赞，评论数据。该爬虫读取 novel_urls.csv 文件中的链接；
4. settings.py 文件中的 STOP_DATE 字段，用于设置 qaSpider.py 中的日期，早于该日期的回答将被放弃；
5. answerSpider.py、novelSpider.py 的运行，需要配置 mysql 数据库，配置信息在 settings.py 中的 MYSQL 对象
6. 数据库需要先建表， answer_info、novel_info，字段如下：

   > answer_info: id,data_time,voteup_count,comment_count,updated_time,created_time

   > novel_info: id,title,data_time,voteup_count,comment_count,updated_time,created_time

   > 注意：上面的两个表建立不要设置 id 唯一、不要设置 id 是主键约束，因为每一条数据按天更新，同一个 id 的数据每天可能都有一份
