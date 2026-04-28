import os
import sqlite3
from pathlib import Path
import matplotlib as mpl
from datetime import datetime, timedelta
from typing import Optional, Union
import matplotlib.dates as mdates
from matplotlib import pyplot as plt
from nonebot import get_bot
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from .tools import wait_for_plus
from .exception import SystemExitException
from matplotlib.font_manager import FontProperties


class UserScoreDatabase:
    MAX_RETRIES = 3

    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = Path(db_path) if db_path is not None else (Path("data") / "user_scores.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._create_tables()

    def _create_tables(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS user_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    timestamp DATETIME NOT NULL,
                    score REAL
                )
            """)
            self.conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_user_timestamp 
                ON user_scores (user_id, timestamp)
            """)

    def update_score(self, user_id: int, timestamp: datetime, score: float):
        with self.conn:
            timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            cursor = self.conn.execute(
                "SELECT * FROM user_scores WHERE user_id = ? AND timestamp = ?",
                (user_id, timestamp_str)
            )
            existing = cursor.fetchone()
            if existing:
                query = """
                    UPDATE user_scores 
                    SET score = ?
                    WHERE user_id = ? AND timestamp = ?
                """
                self.conn.execute(query, (score, user_id, timestamp_str))
            else:
                query = """
                    INSERT INTO user_scores (user_id, timestamp, score)
                    VALUES (?, ?, ?)
                """
            self.conn.execute(query, (user_id, timestamp_str, score))
            self.conn.commit()

    def get_today_scores(self, user_id: int):
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        start_str = today_start.strftime("%Y-%m-%d %H:%M:%S")
        end_str = today_end.strftime("%Y-%m-%d %H:%M:%S")
        cursor = self.conn.execute(
            "SELECT timestamp, score FROM user_scores "
            "WHERE user_id = ? AND timestamp >= ? AND timestamp < ? "
            "ORDER BY timestamp",
            (user_id, start_str, end_str))
        timestamps = []
        scores = []
        for row in cursor.fetchall():
            timestamp_str = row[0]
            score_val = row[1]
            if score_val is not None:
                timestamps.append(datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S"))
                scores.append(score_val)
        return {'timestamps': timestamps, 'scores': scores}


class ScoringSystem:
    def __init__(
        self,
        user_id: int = 3125049051,
        group_id: int = 1049391740,
        *,
        db_path: Optional[Path | str] = None,
    ):
        self.user_id = int(user_id)
        self.group_id = int(group_id)
        self.db = UserScoreDatabase(db_path=db_path)
        self.evaluation_levels = {
            (0, 10): ("⚰️ 地狱级灾难日", "今天简直是世界末日！各项指标全面崩溃，建议立即启动紧急恢复程序！"),
            (11, 20): ("💥 灾难性表现", "天啊！这是系统检测到的最低能量水平！明天必须触底反弹！"),
            (21, 30): ("🌧️ 艰难挣扎日", "乌云密布的一天！您在与自我对抗的战争中艰难求生，需要立即调整战略！"),
            (31, 40): ("⛅ 平稳过渡日", "平凡中带着微光！虽然不够耀眼，但至少没有沉船，继续保持！"),
            (41, 50): ("✨ 超凡掌控日", "天选之日！您就像精密运行的瑞士手表，每个齿轮都完美咬合！"),
            (51, 60): ("🚀 宇宙级超神日", "警告！检测到突破人类极限的能量波动！您今天是被神明亲吻了吗？")
        }

    async def wait_for(self, timeout: int):
        event = await wait_for_plus(self.user_id, self.group_id, timeout)
        msg = event.get_message().extract_plain_text().strip() if event else ''
        return msg

    async def calculate_daily_total(self) -> float:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        start_str = today_start.strftime("%Y-%m-%d %H:%M:%S")
        end_str = today_end.strftime("%Y-%m-%d %H:%M:%S")
        cursor = self.db.conn.execute(
            "SELECT score FROM user_scores "
            "WHERE user_id = ? AND timestamp >= ? AND timestamp < ? "
            "AND score IS NOT NULL",
            (self.user_id, start_str, end_str))
        scores = [row[0] for row in cursor.fetchall()]
        if not scores:
            return 0.0
        avg_score = sum(scores) / len(scores)
        return avg_score * 6

    async def score(self):
        """记录用户满意度评分"""
        score = await self.get_score_input(
            "请为您当前的整体满意度评分（0-10分，0表示非常不满意，10表示非常满意）："
        )
        if score is not None:
            timestamp = datetime.now()
            self.db.update_score(self.user_id, timestamp, score)
            await self.send(f"✅ 满意度评分 {score} 已记录！")
        return score

    async def daily_evaluation(self):
        total_score = await self.calculate_daily_total()
        evaluation = "🛸 神秘未知领域"
        description = "系统无法识别今日的能量信号，这可能是历史性突破！"
        for (min_score, max_score), (title, desc) in self.evaluation_levels.items():
            if min_score <= total_score <= max_score:
                evaluation = title
                description = desc
                break
        report = (
            f"🌠【今日最终战报】🌠\n"
            f"最终得分：{total_score:.1f}/60\n"
            f"能量评级：{evaluation}\n"
            f"系统诊断：{description}\n"
            f"{self.generate_emoji_bar(total_score)}\n"
            f"{self.generate_improvement_tips(total_score)}"
        )
        await self.send(report)

    def generate_emoji_bar(self, score: float) -> str:
        filled_count = max(0, min(10, int(round(score / 6))))
        filled = "⭐" * filled_count
        empty_count = 10 - filled_count
        empty = "🌑" * empty_count
        percentage = min(100, max(0, int(round(score * 100 / 60))))
        return f"能量条：\n[{filled}{empty}] {percentage}%"

    def generate_improvement_tips(self, score: float) -> str:
        if score <= 10:
            return "💣 紧急行动：立即进行深度冥想，切断所有干扰源，明日必须重置系统！"
        elif score <= 20:
            return "⚠️ 危机警报：建议启动24小时恢复协议，明天是新的战场！"
        elif score <= 30:
            return "🔧 优化建议：分析今日主要失分项，制定明日三项重点改进目标"
        elif score <= 40:
            return "📈 提升空间：找出1-2个可突破的领域，明天争取进入超凡区"
        elif score <= 50:
            return "🏆 王者风范：保持这种统治级表现，您正在创造个人历史！"
        else:
            return "🚨 异常警告：检测到超常能量波动！建议备份今日数据以供研究！"

    async def send(self, message: Union[str, Message]):
        await get_bot().send_group_msg(group_id=self.group_id, message=message)

    async def handle_input(self, timeout=30):
        response = await self.wait_for(timeout)
        if response == '':
            raise SystemExitException("用户输入为空，退出系统")
        return response

    async def get_score_input(self, prompt: str) -> Optional[int]:
        retries = 0
        while retries < UserScoreDatabase.MAX_RETRIES:
            await self.send(prompt if retries == 0 else "输入错误，请重新输入评分（0-10分）：")
            try:
                response = await self.handle_input()
                num = int(response.strip())
                if 0 <= num <= 10:
                    return num
                else:
                    raise ValueError
            except ValueError:
                retries += 1
                if retries >= UserScoreDatabase.MAX_RETRIES:
                    await self.send("错误次数过多，自我评分取消")
            except SystemExitException:
                await self.send("⏱️ 输入超时，自我评分取消")
                return None
        return None

    async def show_today_scores_chart(self):
        try:
            mpl.rcParams['font.family'] = 'Microsoft YaHei'
            mpl.rcParams['font.size'] = 10
        except:
            try:
                font_path = Path(__file__).parent.parent / "data" / "fonts" / "msyh.ttc"
                prop = FontProperties(fname=str(font_path))
                mpl.rcParams['font.family'] = prop.get_name()
            except:
                mpl.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
        mpl.rcParams['axes.unicode_minus'] = False
        data = self.db.get_today_scores(self.user_id)
        if not data['scores']:
            await self.send("今日尚无评分记录")
            return
        plt.figure(figsize=(12, 7), dpi=100)
        ax = plt.gca()
        date_format = mdates.DateFormatter('%H:%M')
        ax.xaxis.set_major_formatter(date_format)
        sorted_indices = sorted(range(len(data['timestamps'])), key=lambda i: data['timestamps'][i])
        sorted_timestamps = [data['timestamps'][i] for i in sorted_indices]
        sorted_scores = [data['scores'][i] for i in sorted_indices]
        ax.plot(
            mdates.date2num(sorted_timestamps),
            sorted_scores,
            '-o',
            label='满意度评分',
            color='#1f77b4',
            markersize=8,
            linewidth=2.5,
            alpha=0.9
        )
        ax.set_title('今日满意度评分趋势', fontsize=16, pad=15)
        ax.set_xlabel('时间', fontsize=12, labelpad=10)
        ax.set_ylabel('满意度 (0-10分)', fontsize=12, labelpad=10)
        ax.set_ylim(0, 10.5)
        ax.grid(True, linestyle='--', alpha=0.6)
        ax.legend(loc='best', fontsize=10, framealpha=0.9)
        if len(sorted_timestamps) > 1:
            min_time = min(sorted_timestamps)
            max_time = max(sorted_timestamps)
            time_diff = (max_time - min_time).total_seconds() / 60
            if time_diff < 30:
                locator = mdates.MinuteLocator(interval=5)
            elif time_diff < 120:
                locator = mdates.MinuteLocator(interval=10)
            else:
                locator = mdates.HourLocator()
            ax.xaxis.set_major_locator(locator)
        plt.xticks(rotation=30)
        plt.tight_layout(pad=2.0)
        chart_dir = Path("data") / "charts"
        chart_dir.mkdir(parents=True, exist_ok=True)
        image_path = chart_dir / "today_satisfaction_chart.png"
        plt.savefig(image_path, dpi=100, bbox_inches='tight')
        plt.close()
        await self.send(Message(MessageSegment.image(f"file:///{os.path.abspath(image_path)}")))
        try:
            os.remove(image_path)
        except Exception as e:
            print(f"删除临时文件失败: {e}")
