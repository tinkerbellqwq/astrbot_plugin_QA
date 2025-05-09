import os
from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.utils.session_waiter import session_waiter, SessionController
from .QA import QASystem

@register("helloworld", "YourName", "一个简单的 Hello World 插件", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.QASystem = QASystem("data/qa.db")

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

    @filter.command("增加关键词")
    async def add_keyword(self, event: AstrMessageEvent, keyword: str):
        """添加关键词"""
        if event.is_private_chat():
            yield event.plain_result("私聊模式下不支持添加关键词")
            return
        try:
            yield event.plain_result("请输入关键词回复")

            @session_waiter(timeout=60, record_history_chains=False)
            async def wait_for_keyword_reply(controller: SessionController, event: AstrMessageEvent):
                """等待关键词回复"""
                reply = event.message_str
                group_id = event.get_group_id()
                result =  self.QASystem.add_qa(group_id, keyword, values=[
                    { 'type': 'TEXT', 'content': reply }
                ])
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
        group_id = event.get_group_id()
        result = self.QASystem.get_qa_by_group(group_id)
        logger.info(f"接收到消息: {message}, 关键词: {result}")
        #  {'你好': [{'type': 'TEXT', 'content': '你好呀', 'order': 0}]}
        for keyword in result:
            if keyword in message:
                reply = result[keyword]
                if isinstance(reply, list):
                    for item in reply:
                        if item['type'] == 'TEXT':
                            yield event.plain_result(item['content'])

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        self.QASystem.close()