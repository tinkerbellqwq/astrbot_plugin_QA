import os
from datetime import datetime

from aiohttp import ClientSession

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core import AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.core.star import StarTools
from astrbot.core.utils.session_waiter import session_waiter, SessionController
from astrbot.core.message.components import Image

from .QA import QASystem

async def download_image(url: str, save_path: str) -> str | None:
    """下载图片并保存到本地"""
    url = url.replace("https://", "http://")
    try:
        async with ClientSession() as client:
            response = await client.get(url)
            img_bytes = await response.read()

            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            with open(save_path, "wb") as img_file:
                img_file.write(img_bytes)

            logger.info(f"图片已保存: {save_path}")
            return save_path
    except Exception as e:
        logger.error(f"图片下载并保存失败: {e}")
        return None


import re
import jieba

def check_is_match(keyword: str, message: str) -> bool:
    """
    检查消息是否匹配关键词
    支持多种匹配策略：子串匹配、分词后部分匹配、正则表达式

    Args:
        keyword: 关键词，可能是普通文本或正则表达式
        message: 用户消息文本

    Returns:
        bool: 是否匹配成功
    """
    # 空字符串处理
    if not keyword or not message:
        return False

    # 1. 基本的子串匹配
    if keyword in message:
        return True

    # 2. 正则表达式匹配
    if keyword.startswith("re:"):
        pattern = keyword[3:]
        try:
            if re.search(pattern, message):
                return True
        except re.error:
            pass

    # 3. 分词后部分匹配
    # 对关键词和消息都进行分词，计算关键词分词结果在消息分词中的覆盖率
    keyword_words = list(jieba.cut(keyword))
    message_words = list(jieba.cut(message))

    # 如果关键词只有1-2个词，要求全部匹配
    if len(keyword_words) <= 2:
        if all(word in message_words for word in keyword_words):
            return True
    # 如果关键词较长，允许部分匹配（超过70%的词被匹配）
    else:
        matched_count = sum(1 for word in keyword_words if word in message_words)
        match_ratio = matched_count / len(keyword_words)
        if match_ratio >= 0.7:
            return True

    # 4. 处理特殊情况：检查核心词匹配
    # 对于某些词组可能包含核心词，如"地图"、"攻略"等
    important_words = ["地图", "攻略", "指南", "教程", "帮助", "说明"]
    for word in important_words:
        if word in keyword and word in message:
            keyword_without_core = keyword.replace(word, "")
            message_without_core = message.replace(word, "")
            # 检查剩余部分是否有足够相似度
            # 简单计算：至少有一个字符相同
            common_chars = set(keyword_without_core) & set(message_without_core)
            if len(common_chars) >= 1:
                return True

    return False

@register("helloworld", "YourName", "一个简单的 Hello World 插件", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.QASystem = QASystem("data/qa.db")
        self.plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_QA")
        self.admins = config.get("admins", [])

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

    @filter.command("增加关键词", alias={ '添加关键词' })
    async def add_keyword(self, event: AstrMessageEvent, keyword: str):
        """添加关键词"""
        if event.is_private_chat():
            yield event.plain_result("私聊模式下不支持添加关键词")
            return
        sender_id = event.get_sender_id()
        assert isinstance(event, AiocqhttpMessageEvent), "Event must be AiocqhttpMessageEvent"
        bot = event.bot
        info = await event.bot.get_group_member_info(
            group_id=int(event.get_group_id()), user_id=int(sender_id), no_cache=True
        )
        role = info.get("role", "unknown")
        ok = False
        match role:
            case "owner":
                ok = True
            case "admin":
                ok = True
            case "member":
                ok = False
            case _:
                ok = False

        if sender_id not in self.admins or not ok:
            yield event.plain_result("你没有权限添加关键词")
            return
        try:
            yield event.plain_result("请输入关键词回复")

            @session_waiter(timeout=60, record_history_chains=False)
            async def wait_for_keyword_reply(controller: SessionController, event: AstrMessageEvent):
                """等待关键词回复"""
                group_id = event.get_group_id()
                now_sender_id = event.get_sender_id()
                if now_sender_id != sender_id:
                    # 跳过，等待正确的发送者
                    return
                message_obj = event.message_obj
                image_path = None
                if hasattr(message_obj, "message"):
                    for comp in message_obj.message:
                        if isinstance(comp, Image):
                            # 保存图片到本地，并且保存
                            reply_img = comp.url
                            temp_path = os.path.join(
                                self.plugin_data_dir,
                                f"reply_image_{group_id}_{keyword}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                            )
                            image_path = await download_image(reply_img, temp_path)
                reply_text = event.message_str
                values_list = []
                if reply_text:
                    values_list.append({ 'type': 'TEXT', 'content': reply_text })
                if image_path:
                    values_list.append({ 'type': 'IMAGE_URL', 'content': image_path })
                if values_list:
                    self.QASystem.add_qa(group_id, keyword, values=values_list)
                controller.stop()
            try:
                await wait_for_keyword_reply(event)
                yield event.plain_result("关键词添加成功")
            except Exception as e:
                logger.error(f"等待关键词回复失败: {e}")
                yield event.plain_result("等待关键词回复失败")
        except Exception as e:
            logger.error(f"添加关键词失败: {e}")
            yield event.plain_result("添加关键词失败")

    @filter.command("删除关键词")
    async def delete_keyword(self, event: AstrMessageEvent, keyword: str):
        """删除关键词"""
        if event.is_private_chat():
            yield event.plain_result("私聊模式下不支持删除关键词")
            return
        sender_id = event.get_sender_id()
        assert isinstance(event, AiocqhttpMessageEvent), "Event must be AiocqhttpMessageEvent"
        bot = event.bot
        info = await event.bot.get_group_member_info(
            group_id=int(event.get_group_id()), user_id=int(sender_id), no_cache=True
        )
        role = info.get("role", "unknown")
        ok = False
        match role:
            case "owner":
                ok = True
            case "admin":
                ok = True
            case "member":
                ok = False
            case _:
                ok = False
        if sender_id not in self.admins or not ok:
            yield event.plain_result("你没有权限添加关键词")
            return
        if sender_id not in self.admins:
            yield event.plain_result("你没有权限删除关键词")
            return
        try:
            group_id = event.get_group_id()
            result = self.QASystem.delete_qa(group_id, keyword)
            yield event.plain_result(result)
        except Exception as e:
            logger.error(f"删除关键词失败: {e}")
            yield event.plain_result("删除关键词失败")

    @filter.command("查询关键词")
    async def query_keyword(self, event: AstrMessageEvent, keyword: str):
        """查询关键词"""
        if event.is_private_chat():
            yield event.plain_result("私聊模式下不支持查询关键词")
            return
        try:
            group_id = event.get_group_id()
            result = self.QASystem.get_qa(group_id, keyword)
            message = f"关键词: {keyword}\n"
            if result:
                for i, item in enumerate(result):
                    message += f"回复{i + 1}: {item['content']}\n"
            else:
                message += "没有找到相关回复"
            yield event.plain_result(message)
        except Exception as e:
            logger.error(f"查询关键词失败: {e}")
            yield event.plain_result("查询关键词失败")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_all_message(self, event: AstrMessageEvent):
        """接收所有消息事件"""
        # logger.info(event.message_obj)
        if event.is_private_chat():
            return
        message = event.message_str
        if message.startswith('/'):
            # 忽略以斜杠开头的命令消息
            logger.info(f"Ignoring command message: {message}")
            return
        group_id = event.get_group_id()
        result = self.QASystem.get_qa_by_group(group_id)
        for keyword in result:
            if check_is_match(keyword, message):
                reply = result[keyword]
                if isinstance(reply, list):
                    for item in reply:
                        if item['type'] == 'TEXT':
                            yield event.plain_result(item['content'])
                        if item['type'] == 'IMAGE_URL':
                            yield event.image_result(item['content'])

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        self.QASystem.close()