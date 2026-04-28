import os
import json
import shutil
import nonebot
import tempfile
import matplotlib.font_manager as fm
from pathlib import Path
from typing import Union, Optional
from graphviz import Digraph
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from .tools import wait_for_plus
from .exception import SystemExitException


class TreeNode:
    def __init__(self, title, is_leaf=False, solution=None, path=""):
        self.title = title
        self.is_leaf = is_leaf
        self.solution = solution
        self.children = {}
        self.path = path

    def display(self) -> str:
        msg = f"{self.title}"
        if not self.is_leaf:
            for opt, child in self.children.items():
                msg += f"\n{opt}. {child.title}"
        return msg

    def visualize(self, graph=None, parent_id=None):
        if graph is None:
            graph = Digraph(comment='Problem Tree', format='png')
            chinese_font = self.find_chinese_font()
            if not chinese_font:
                chinese_font = 'Arial Unicode MS'
            graph.attr(
                'graph',
                rankdir='TB',
                fontname=chinese_font
            )
            graph.attr(
                'node',
                shape='box',
                style='rounded,filled',
                fillcolor='#F0F8FF',
                fontname=chinese_font,
                fontsize='12'
            )
            graph.attr(
                'edge',
                arrowhead='vee',
                arrowsize='0.5'
            )
        node_id = str(id(self))
        label = f"{self.path} {self.title}" if self.path else self.title
        if self.is_leaf:
            graph.node(
                node_id,
                label=label,
                fillcolor='#FFE4B5',
                shape='ellipse'
            )
        else:
            graph.node(node_id, label=label)
        if parent_id:
            graph.edge(parent_id, node_id)
        for child in self.children.values():
            child.visualize(graph, node_id)
        return graph

    @staticmethod
    def find_chinese_font():
        font_candidates = ['Microsoft YaHei', 'SimHei', 'STHeiti', 'WenQuanYi Micro Hei', 'Noto Sans CJK SC']
        system_fonts = [f.name for f in fm.fontManager.ttflist]
        for font in font_candidates:
            if font in system_fonts:
                return font
        return None


class ProblemSolverSystem:
    def __init__(
        self,
        user_id: int = 3125049051,
        group_id: int = 1049391740,
        config_file: Optional[Path | str] = None,
    ):
        self.group_id = int(group_id)
        self.user_id = int(user_id)
        self.config_file = str(config_file or (Path("data") / "problem_tree.json"))
        self.root = self.load_config()
        self.current_node = self.root

    async def wait_for(self, timeout: int):
        event = await wait_for_plus(self.user_id, self.group_id, timeout)
        msg = event.get_message().extract_plain_text().strip() if event else ''
        return msg

    async def send(self, msg: Union[Message, str]):
        await nonebot.get_bot().send_group_msg(
            group_id=self.group_id,
            message=msg
        )

    async def handle_input(self, timeout=30, prompt=None):
        if prompt:
            await self.send(prompt)
        response = await self.wait_for(timeout)
        if response == '':
            raise SystemExitException("用户输入为空，退出系统")
        return response

    def load_config(self):
        with open(self.config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return self.build_tree_from_config(config)

    def build_tree_from_config(self, config, path=""):
        node = TreeNode(
            title=config['title'],
            is_leaf=config.get('is_leaf', False),
            solution=config.get('solution', None),
            path=path
        )
        if 'children' in config and not node.is_leaf:
            for opt, child_config in config['children'].items():
                child_path = f"{path}.{opt}" if path else opt
                child_node = self.build_tree_from_config(child_config, child_path)
                node.children[opt] = child_node
        node.children = self.reindex_children(node.children)
        return node

    def reset(self):
        self.current_node = self.root

    @staticmethod
    def reindex_children(children):
        if not children:
            return {}
        sorted_keys = sorted(children.keys(), key=int)
        new_children = {}
        for i, key in enumerate(sorted_keys, 1):
            new_children[str(i)] = children[key]
        return new_children

    async def edit_mode(self):
        msg = (
            f"📝 编辑模式 - {self.current_node.title}\n"
            f"节点路径: {self.current_node.path if self.current_node.path else '根节点'}\n"
        )
        if self.current_node.is_leaf:
            msg += (
                "1. 修改节点标题\n"
                "2. 修改解决方案\n"
                "3. 删除当前节点\n"
                "4. 移动当前节点\n"
                "0. 返回\n"
            )
        else:
            msg += (
                "1. 修改节点标题\n"
                "2. 添加子节点\n"
                "3. 删除当前节点\n"
                "4. 移动当前节点\n"
                "5. 编辑子节点\n"
                "0. 返回\n"
            )
        msg += "请选择操作: "
        try:
            choice = await self.handle_input(30, msg)
        except SystemExitException:
            return
        if choice == "0":
            return
        if choice == "1":
            await self.send("请输入新标题: ")
            new_title = await self.wait_for(30)
            if new_title:
                self.current_node.title = new_title
                await self.send("标题已更新!")
                await self.save_config()
            else:
                await self.send("标题不能为空!")
        elif choice == "2":
            if self.current_node.is_leaf:
                await self.send("请输入新解决方案: ")
                new_solution = await self.wait_for(30)
                if new_solution:
                    self.current_node.solution = new_solution
                    await self.send("解决方案已更新!")
                    await self.save_config()
                else:
                    await self.send("解决方案不能为空!")
            else:
                await self.add_child_node()
        elif choice == "3":
            if self.current_node == self.root:
                await self.send("不能删除根节点!")
                return
            await self.send("确定要删除此节点及其所有子节点吗? (y/n): ")
            confirm = await self.wait_for(30)
            if confirm == 'y':
                parent = self.find_parent(self.root, self.current_node)
                if parent:
                    for key, child in parent.children.items():
                        if child == self.current_node:
                            del parent.children[key]
                            parent.children = ProblemSolverSystem.reindex_children(parent.children)
                            await self.send("节点已删除!")
                            await self.save_config()
                            self.reset()
                            return
                await self.send("删除失败: 未找到父节点")
        if choice == "4":
            await self.move_node()
            return
        if choice == "5" and not self.current_node.is_leaf:
            await self.edit_child_node()
            return

    async def move_node(self):
        if self.current_node == self.root:
            await self.send("不能移动根节点!")
            return
        try:
            new_path = await self.handle_input(30, "请输入新的父节点路径 (如 '1.2'): ")
        except SystemExitException:
            return
        new_parent = self.root
        if new_path:
            parts = new_path.split('.')
            for part in parts:
                if part in new_parent.children:
                    new_parent = new_parent.children[part]
                else:
                    await self.send(f"路径无效: 在 '{'.'.join(parts[:parts.index(part) + 1])}' 处找不到子节点")
                    return
        if self.is_descendant(new_parent, self.current_node):
            await self.send("不能将节点移动到自己的子树中!")
            return
        old_parent = self.find_parent(self.root, self.current_node)
        for key, child in list(old_parent.children.items()):
            if child == self.current_node:
                del old_parent.children[key]
                old_parent.children = self.reindex_children(old_parent.children)
        new_key = str(len(new_parent.children) + 1)
        new_parent.children[new_key] = self.current_node
        self.update_node_paths(self.root)
        await self.save_config()
        await self.send(f"节点已移动到路径: {new_path}.{new_key}")
        self.reset()

    async def edit_child_node(self):
        if not self.current_node.children:
            await self.send("当前节点没有子节点!")
            return
        await self.send("\n当前子节点:")
        for key, child in self.current_node.children.items():
            await self.send(f"{key}. {child.title} ({child.path})")
        try:
            child_key = await self.handle_input(30, "请选择要编辑的子节点编号: ")
        except SystemExitException:
            return
        await self.send("请选择要编辑的子节点编号: ")
        child_key = await self.wait_for(30)
        if child_key in self.current_node.children:
            previous_node = self.current_node
            self.current_node = self.current_node.children[child_key]
            await self.edit_mode()
            self.current_node = previous_node
        else:
            await self.send("无效的选择!")

    def is_descendant(self, parent, child):
        if parent == child:
            return True
        for grandchild in child.children.values():
            if self.is_descendant(parent, grandchild):
                return True
        return False

    def update_node_paths(self, node, path=""):
        node.path = path
        if node.children:
            for i, (key, child) in enumerate(node.children.items(), 1):
                child_path = f"{path}.{str(i)}" if path else str(i)
                self.update_node_paths(child, child_path)

    async def add_child_node(self):
        if self.current_node.is_leaf:
            await self.send("叶子节点不能添加子节点!")
            return
        await self.send(
            "添加新子节点:"
            "1. 添加非叶子节点 (可继续添加子节点)\n"
            "2. 添加叶子节点 (最终解决方案)\n"
        )
        try:
            choice = await self.handle_input(30, "请选择节点类型: ")
        except SystemExitException:
            return
        if choice not in ("1", "2"):
            await self.send("无效选择!")
            return
        try:
            title = await self.handle_input(30, "请输入节点标题: ")
        except SystemExitException:
            return
        if not title:
            await self.send("标题不能为空!")
            return
        new_key = str(len(self.current_node.children) + 1)
        is_leaf = (choice == "2")
        solution = ""
        if is_leaf:
            try:
                solution = await self.handle_input(10, "请输入解决方案: ")
            except SystemExitException:
                return
            if not solution:
                await self.send("解决方案不能为空!")
                return
        self.current_node.children[new_key] = TreeNode(
            title=title,
            is_leaf=is_leaf,
            solution=solution
        )
        await self.send("子节点已添加!")
        await self.save_config()

    def find_parent(self, current, target, parent=None):
        if current == target:
            return parent
        for child in current.children.values():
            result = self.find_parent(child, target, current)
            if result:
                return result
        return None

    async def save_config(self):
        self.update_node_paths(self.root)
        config = self.tree_to_dict(self.root)
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        await self.send(f"配置已保存到 {self.config_file}")

    def tree_to_dict(self, node):
        node_dict = {
            "title": node.title,
            "is_leaf": node.is_leaf
        }
        if node.solution:
            node_dict["solution"] = node.solution
        if not node.is_leaf and node.children:
            children_dict = {}
            for key, child in node.children.items():
                children_dict[key] = self.tree_to_dict(child)
            node_dict["children"] = children_dict
        return node_dict

    async def get_user_input(self):
        while True:
            choices = list(self.current_node.children.keys())
            prompt = f"请选择问题编号 ({'/'.join(choices)}): " if choices else "问题已解决: "
            try:
                choice = await self.handle_input(30, prompt)
            except SystemExitException:
                return None
            if choice.lower() == 'j':
                return 'jump'
            if choice.lower() == 'e':
                return 'edit'
            if choice.lower() == 'q':
                return None
            if choice.lower() == 'r':
                self.reset()
                return 'reset'
            if choice.lower() == 'v':
                return 'visualize'
            if choice in choices:
                return choice
            await self.send(
                f"无效输入! 请从{choices}中选择或使用控制命令 (q=退出, r=重置, v=可视化, e=编辑, j=跳转到节点)")

    async def jump_to_node(self, path_str):
        if not path_str:
            return False
        parts = path_str.split('.')
        current = self.root
        for part in parts:
            if part in current.children:
                current = current.children[part]
            else:
                await self.send(f"路径无效: 在 '{'.'.join(parts[:parts.index(part) + 1])}' 处找不到子节点")
                return False
        self.current_node = current
        return True

    async def edit_node_by_path(self):
        await self.send(
            "节点路径编辑模式\n"
            f"当前节点路径: {self.current_node.path if self.current_node.path else '根节点'}"
        )
        try:
            path_str = await self.handle_input(30, "请输入要编辑的节点路径 (如 '1.2.3'): ")
        except SystemExitException:
            return
        if await self.jump_to_node(path_str):
            await self.edit_mode()
            self.reset()
        else:
            await self.send("跳转失败，请检查路径是否正确")

    async def run(self):
        await self.send(
            "【智能问题诊断系统】已启动\n"
            "提示: 输入 q 退出, r 重置, v 可视化问题树, e 编辑当前节点, j 跳转到指定节点\n"
            "注意: 在任何输入提示处直接按回车可退出系统"
        )
        try:
            while True:
                await self.send(self.current_node.display())
                if self.current_node.is_leaf:
                    await self.send(f"⭐ 解决方案: \n{self.current_node.solution}")
                    break
                choice = await self.get_user_input()
                if choice is None:
                    await self.send("系统已退出")
                    break
                if choice == 'reset':
                    await self.send("会话已重置")
                    continue
                if choice == 'visualize':
                    await self.visualize_tree()
                    continue
                if choice == 'edit':
                    await self.edit_mode()
                    continue
                if choice == 'jump':
                    await self.edit_node_by_path()
                    continue
                self.current_node = self.current_node.children[choice]
        except SystemExitException:
            await self.send("系统已退出")

    async def visualize_tree(self):
        await self.send("正在生成问题树可视化...")
        temp_dir = tempfile.mkdtemp()
        file_path = os.path.join(temp_dir, "problem_tree")
        try:
            graph = self.root.visualize()
            graph.render(file_path, format='png', cleanup=True)
            image_path = f"{file_path}.png"
            print(f"file:///{os.path.abspath(image_path)}")
            await self.send(Message(MessageSegment.image(f"file:///{os.path.abspath(image_path)}")))
            await self.send(
                "提示: 节点前的数字表示路径，如 '1.2.1' 表示根节点 -> 第一个子节点 -> 第二个子节点 -> 第一个叶子节点")
        except Exception as e:
            await self.send(f"生成可视化失败: {str(e)}")
        finally:
            try:
                shutil.rmtree(temp_dir)
            except Exception as cleanup_error:
                print(f"清理临时目录失败: {cleanup_error}")


if __name__ == "__main__":
    system = ProblemSolverSystem()
    system.run()
