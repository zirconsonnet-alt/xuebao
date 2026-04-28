from typing import Dict, Optional

from .manager import VoteManager


class Strategy:
    TIME_DICT = {
        "1": ("1分钟", 60),
        "2": ("5分钟", 300),
        "3": ("10分钟", 600),
    }

    def setup_options(self, vote_manager: VoteManager) -> None:
        raise NotImplementedError

    def get_vote_prompt(self, vote_manager: VoteManager, topic: Dict, vote_time: int) -> str:
        raise NotImplementedError

    def get_full(self) -> int:
        raise NotImplementedError

    def result_text(
        self,
        vote_manager: VoteManager,
        topic: Dict,
        *,
        side_effect_applied: Optional[bool] = None,
    ) -> str:
        raise NotImplementedError

    def passed(self, vote_manager: VoteManager) -> bool:
        raise NotImplementedError


class TopicStrategy(Strategy):
    def setup_options(self, vote_manager: VoteManager) -> None:
        vote_manager.set_option(1, "同意")
        vote_manager.set_option(2, "不同意")

    def get_vote_prompt(self, vote_manager: VoteManager, topic: Dict, vote_time: int) -> str:
        return (
            f"关于议题“{topic['content']}”的投票已开启！请选择序号进行投票：\n1. 同意；\n2. 不同意。\n"
            f"投票将在{vote_time}秒内结束，请各位成员及时采取决定！"
        )

    def get_full(self):
        return 5

    def passed(self, vote_manager: VoteManager) -> bool:
        if len(vote_manager.voted_users) < self.get_full():
            return False
        max_votes_index = max(vote_manager.options, key=lambda k: vote_manager.options[k]["votes"])
        max_votes_value = vote_manager.options[max_votes_index]["votes"]
        top_options = [
            idx
            for idx, option_info in vote_manager.options.items()
            if option_info["votes"] == max_votes_value
        ]
        return len(top_options) == 1 and max_votes_index == 1

    def result_text(
        self,
        vote_manager: VoteManager,
        topic: Dict,
        *,
        side_effect_applied: Optional[bool] = None,
    ) -> str:
        result = f"关于议题：{topic['content']}的投票结果：\n"
        for idx, option_info in vote_manager.options.items():
            result += f"选项 {idx}: {option_info['option']} - 投票数：{option_info['votes']}票\n"
        max_votes_index = max(vote_manager.options, key=lambda k: vote_manager.options[k]["votes"])
        max_votes_value = vote_manager.options[max_votes_index]["votes"]
        top_options = [
            idx
            for idx, option_info in vote_manager.options.items()
            if option_info["votes"] == max_votes_value
        ]
        if len(vote_manager.voted_users) >= self.get_full():
            if len(top_options) == 0:
                result += "最终结果：\n投票取消。"
            elif len(top_options) == 2:
                result += "最终结果：\n平票，请管理员裁定。"
            elif len(top_options) == 1:
                if max_votes_index == 1:
                    result += "最终结果：\n议题通过!"
                    if side_effect_applied is False:
                        result += "\n(该结果已执行过)"
                else:
                    result += "最终结果：\n议题不通过!"
        else:
            result = "本次投票人数不足5人，议题无效。"
        return result


class SetStrategy(Strategy):
    def setup_options(self, vote_manager: VoteManager) -> None:
        vote_manager.set_option(1, "同意")
        vote_manager.set_option(2, "不同意")

    def get_vote_prompt(self, vote_manager: VoteManager, topic: Dict, vote_time: int) -> str:
        return (
            "关于是否将本条消息设为精华的投票已开启！请选择序号进行投票：\n1. 同意；\n2. 不同意。\n"
            f"投票将在{vote_time}秒内结束，请各位成员及时采取决定！"
        )

    def get_full(self):
        return 3

    def passed(self, vote_manager: VoteManager) -> bool:
        if len(vote_manager.voted_users) < self.get_full():
            return False
        max_votes_index = max(vote_manager.options, key=lambda k: vote_manager.options[k]["votes"])
        max_votes_value = vote_manager.options[max_votes_index]["votes"]
        top_options = [
            idx
            for idx, option_info in vote_manager.options.items()
            if option_info["votes"] == max_votes_value
        ]
        return len(top_options) == 1 and max_votes_index == 1

    def result_text(
        self,
        vote_manager: VoteManager,
        topic: Dict,
        *,
        side_effect_applied: Optional[bool] = None,
    ) -> str:
        result = ""
        max_votes_index = max(vote_manager.options, key=lambda k: vote_manager.options[k]["votes"])
        max_votes_value = vote_manager.options[max_votes_index]["votes"]
        top_options = [
            idx
            for idx, option_info in vote_manager.options.items()
            if option_info["votes"] == max_votes_value
        ]
        if len(vote_manager.voted_users) >= self.get_full():
            if len(top_options) == 1 and max_votes_index == 1:
                result += "设置成功!"
                if side_effect_applied is False:
                    result += "\n(该结果已执行过)"
            else:
                result += "设置失败!"
        else:
            result = "本次投票人数不足3人，投票无效。"
        return result


class BanStrategy(Strategy):
    def setup_options(self, vote_manager: VoteManager) -> None:
        vote_manager.set_option(1, "同意")
        vote_manager.set_option(2, "不同意")

    def get_vote_prompt(self, vote_manager: VoteManager, topic: Dict, vote_time=None) -> str:
        return (
            f"关于禁言群成员“{topic['content']}”的投票已开启！请选择序号进行投票：\n"
            "1. 同意；\n2. 不同意。\n投票将在60秒内结束，请各位成员及时采取决定！\n"
            "注：只有投票人数大于3人时，投票结果才有效力！"
        )

    def get_full(self):
        return 3

    def passed(self, vote_manager: VoteManager) -> bool:
        if len(vote_manager.voted_users) < self.get_full():
            return False
        max_votes_index = max(vote_manager.options, key=lambda k: vote_manager.options[k]["votes"])
        max_votes_value = vote_manager.options[max_votes_index]["votes"]
        top_options = [
            idx
            for idx, option_info in vote_manager.options.items()
            if option_info["votes"] == max_votes_value
        ]
        return len(top_options) == 1 and max_votes_index == 1

    def result_text(
        self,
        vote_manager: VoteManager,
        topic: Dict,
        *,
        side_effect_applied: Optional[bool] = None,
    ) -> str:
        max_votes_index = max(vote_manager.options, key=lambda k: vote_manager.options[k]["votes"])
        max_votes_value = vote_manager.options[max_votes_index]["votes"]
        top_options = [
            idx
            for idx, option_info in vote_manager.options.items()
            if option_info["votes"] == max_votes_value
        ]
        if len(top_options) == 1 and max_votes_index == 1 and len(vote_manager.voted_users) >= self.get_full():
            if side_effect_applied:
                return f"禁言成功，用户{topic['content']} 被禁言 1 小时。"
            return "禁言已执行，本次请求已被幂等拦截。"
        return "禁言未通过，不执行任何操作。"


class KickStrategy(Strategy):
    def setup_options(self, vote_manager: VoteManager) -> None:
        vote_manager.set_option(1, "同意")
        vote_manager.set_option(2, "不同意")

    def get_vote_prompt(self, vote_manager: VoteManager, topic: Dict, vote_time: int = None) -> str:
        return (
            f"关于放逐群成员“{topic['content']}”的投票已开启！请选择序号进行投票：\n"
            "1. 同意；\n2. 不同意。\n投票将在300秒内结束，请各位成员及时采取决定！\n"
            "注：只有投票人数大于5人时，投票结果才有效力！"
        )

    def get_full(self) -> int:
        return 5

    def passed(self, vote_manager: VoteManager) -> bool:
        if len(vote_manager.voted_users) < self.get_full():
            return False
        max_votes_index = max(vote_manager.options, key=lambda k: vote_manager.options[k]["votes"])
        max_votes_value = vote_manager.options[max_votes_index]["votes"]
        top_options = [
            idx
            for idx, option_info in vote_manager.options.items()
            if option_info["votes"] == max_votes_value
        ]
        return len(top_options) == 1 and max_votes_index == 1

    def result_text(
        self,
        vote_manager: VoteManager,
        topic: Dict,
        *,
        side_effect_applied: Optional[bool] = None,
    ) -> str:
        max_votes_index = max(vote_manager.options, key=lambda k: vote_manager.options[k]["votes"])
        max_votes_value = vote_manager.options[max_votes_index]["votes"]
        top_options = [
            idx
            for idx, option_info in vote_manager.options.items()
            if option_info["votes"] == max_votes_value
        ]
        if len(top_options) == 1 and max_votes_index == 1 and len(vote_manager.voted_users) >= self.get_full():
            if side_effect_applied:
                return f"放逐成功，用户 {topic} 已被移出本群。"
            return "放逐已执行，本次请求已被幂等拦截。"
        return "放逐未通过，不执行任何操作。"


class GeneralStrategy(Strategy):
    def setup_options(self, vote_manager: VoteManager) -> None:
        return None

    def get_vote_prompt(self, vote_manager: VoteManager, topic: Dict, vote_time: int):
        options_prompt = "\n".join(
            [f"{idx}. {option_info['option']}" for idx, option_info in vote_manager.options.items()]
        )
        return (
            f"关于主题“{topic['content']}”的投票已开启！请选择序号进行投票：\n{options_prompt}\n投票"
            f"将在{vote_time}内结束，请各位成员及时采取决定！"
        )

    def get_full(self):
        return 100

    def passed(self, vote_manager: VoteManager) -> bool:
        return len(vote_manager.voted_users) >= self.get_full()

    def result_text(
        self,
        vote_manager: VoteManager,
        topic: Dict,
        *,
        side_effect_applied: Optional[bool] = None,
    ) -> str:
        result = f"关于主题：{topic['content']}的投票结果：\n"
        for idx, option_info in vote_manager.options.items():
            result += f"选项 {idx}: {option_info['option']} - 投票数：{option_info['votes']}票\n"
        max_votes_value = max(option_info["votes"] for option_info in vote_manager.options.values())
        top_options = [
            idx
            for idx, option_info in vote_manager.options.items()
            if option_info["votes"] == max_votes_value
        ]
        if len(top_options) == 0:
            result += "最终结果：投票取消。"
        elif len(top_options) > 1:
            result += "最终结果：\n票数最高的是："
            result += "\n, ".join([f"选项 {idx}: {vote_manager.options[idx]['option']}" for idx in top_options])
            result += f"，票数为：{max_votes_value}票。\n平票，由管理员裁定。"
        else:
            result += f"最终结果：\n得票最高的是：{vote_manager.options[top_options[0]]['option']}！"
        return result
