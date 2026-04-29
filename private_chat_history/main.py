import asyncio

import json

import os

import re

import time

import urllib.request

from datetime import datetime

from astrbot.api.all import (

    register,

    command,

    Star,

    Context,

    AstrMessageEvent,

    CommandResult,

    logger,

)

from astrbot.core.star.register import (

    register_on_llm_request as on_llm_request,

)

from astrbot.core.provider.entities import ProviderRequest

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

HISTORY_FILE = os.path.join(DATA_DIR, "cached_history.json")

# 配置常量

MAX_INJECT_MESSAGES = 15      # 注入上下文的最大消息数

MAX_MESSAGE_LENGTH = 500      # 单条消息截断长度

MIN_MESSAGE_LENGTH = 5        # 单条消息最小长度，少于此字数不读取（过滤短消息）

MIN_INJECT_MESSAGES = 5        # 最少需要注入的消息数，不足时放宽过滤

AUTO_INJECT = True           # 是否自动注入私聊历史到AI上下文

SUMMARY_THRESHOLD = 500       # 超过此字符数触发自动总结

SUMMARY_PROVIDER_ID = ""     # 留空则自动使用当前聊天模型

SUMMARY_CACHE_FILE = os.path.join(DATA_DIR, "summary_cache.json")  # 总结缓存

MAX_INJECTED_SESSIONS = 1000  # 已注入会话集合的最大容量

MAX_DISPLAY_LENGTH = 200      # 显示时消息最大长度

@register("private_chat_history", "soyorin", "私聊历史消息查询与自动注入", "1.2.3")

class PrivateChatHistoryPlugin(Star):

    def __init__(self, context: Context, config: dict | None = None):

        super().__init__(context)

        self.plugin_config = config or {}  # AstrBot 配置系统

        self.cached_messages = []

        self.last_fetch_time = 0

        # 按需注入标记：执行 /私聊历史 命令后设为 True

        self._pending_inject = {}

        # 按需注入的总结内容（由 /私聊历史 命令生成）

        self._pending_summary = {}

        # 自动注入已完成的会话集合（防止重复注入）

        self._injected_sessions = set()  # 修改初始化为 set 而不是 {}
        self._summary_threshold = 500  # 默认总结阈值  # 修复：初始化为 set 而不是 {}

        # 读取配置

        self.target_users = ""

        self.fetch_count = 20

        self.max_cache_size = 60  # 默认最多缓存60条

        self.napcat_http = "http://127.0.0.1:3000"

        self.napcat_token = "1145141919810"

        self.fetch_interval = 300

        self._load_config()

    def _load_config(self):
        """从 AstrBot 配置系统读取设置（优先从 control panel 读取）"""
        defaults = {
            "target_users": "",
            "fetch_count": 20,
            "max_cache_size": 60,
            "max_inject_messages": 15,
            "min_inject_messages": 5,
            "min_message_length": 5,
            "auto_inject": True,
            "summary_threshold_10_20": 400,
            "summary_threshold_20_30": 500,
            "summary_threshold_30_40": 600,
            "summary_threshold_40_50": 700,
            "summary_provider_id": "",
            "napcat_http": "http://127.0.0.1:3000",
            "napcat_token": "1145141919810",
            "fetch_interval": 300,
        }
        cfg = {}
        if self.plugin_config:
            for key in defaults:
                cfg[key] = self.plugin_config.get(key, defaults[key])
        self.target_users = cfg.get("target_users", "")
        self.fetch_count = cfg.get("fetch_count", 20)
        self.max_cache_size = cfg.get("max_cache_size", 60)
        self.max_inject_messages = cfg.get("max_inject_messages", 15)
        self.min_inject_messages = cfg.get("min_inject_messages", 5)
        self.min_message_length = cfg.get("min_message_length", 5)
        self.auto_inject = cfg.get("auto_inject", True)
        self.summary_threshold_10_20 = cfg.get("summary_threshold_10_20", 400)
        self.summary_threshold_20_30 = cfg.get("summary_threshold_20_30", 500)
        self.summary_threshold_30_40 = cfg.get("summary_threshold_30_40", 600)
        self.summary_threshold_40_50 = cfg.get("summary_threshold_40_50", 700)
        self.summary_provider_id = cfg.get("summary_provider_id", "")
        self.napcat_http = cfg.get("napcat_http", "http://127.0.0.1:3000")
        self.napcat_token = cfg.get("napcat_token", "1145141919810")
        self.fetch_interval = cfg.get("fetch_interval", 300)
        source = "AstrBot" if self.plugin_config else "默认"
        logger.info(f"[private_chat_history] 从{source}读取配置: target_users={self.target_users}, fetch_count={self.fetch_count}, max_cache_size={self.max_cache_size}")
        self._target_user_ids = self._parse_target_users()
        logger.info(f"[private_chat_history] 目标用户列表: {self._target_user_ids}")

    def _parse_target_users(self) -> set:

        """解析目标用户列表（支持逗号或换行分隔）"""

        if not self.target_users:

            return set()

        user_ids = set()

        # 支持逗号或换行分隔

        for uid in self.target_users.replace("\n", ",").split(","):

            uid = uid.strip()

            if uid.isdigit():

                user_ids.add(int(uid))

        return user_ids

    async def initialize(self) -> None:

        """插件激活时自动获取私聊记录并准备注入"""

        logger.info("[private_chat_history] 插件已加载，正在获取私聊记录...")

        # 如果没有配置目标用户，则不读取任何人的私聊历史

        if not self._target_user_ids:

            logger.info("[private_chat_history] 未配置 target_users，跳过启动时私聊记录读取（如需启用请在配置文件中添加 target_users）")

            # 清除可能存在的旧缓存

        # [PATCHED] if os.path.exists(HISTORY_FILE):

        # [PATCHED] 

        # [PATCHED] try:

        # [PATCHED] 

        # [PATCHED] os.remove(HISTORY_FILE)

        # [PATCHED] 

        # [PATCHED] except Exception:

        # [PATCHED] 

        # [PATCHED] pass

        # [PATCHED] if os.path.exists(SUMMARY_CACHE_FILE):

        # [PATCHED] 

        # [PATCHED] 

        # [PATCHED] 

        # [PATCHED] try:

        # [PATCHED] 

        # [PATCHED] 

        # [PATCHED] 

        # [PATCHED] os.remove(SUMMARY_CACHE_FILE)

        # [PATCHED] 

        # [PATCHED] 

        # [PATCHED] 

        # [PATCHED] except Exception:

        # [PATCHED] 

        # [PATCHED] 

        # [PATCHED] 

        # [PATCHED] pass

            self.cached_messages = []

            self._injected_sessions.clear()

            return

        # 重试机制：NapCat 可能还没启动，等待它就绪

        max_retries = 10

        # Wait for NapCat to be ready

        logger.info("[private_chat_history] waiting 10s for NapCat to be ready...")

        await asyncio.sleep(10)

        for attempt in range(1, max_retries + 1):

            logger.info(f"[private_chat_history] 尝试获取私聊记录（第 {attempt}/{max_retries} 次）...")

            await self.refresh_cache()

            if self.cached_messages:

                logger.info(f"[private_chat_history] 成功获取 {len(self.cached_messages)} 条记录")

                break

            if attempt < max_retries:

                wait_sec = attempt * 5

                logger.info(f"[private_chat_history] 未获取到记录，{wait_sec} 秒后重试...")

                await asyncio.sleep(wait_sec)

        # 插件启动后自动生成全部好友私聊总结并准备注入

        await self._prepare_startup_summary()

    # ─── 缓存管理 ───

    async def refresh_cache(self, count: int = None):

        """清除旧缓存并重新获取所有好友的私聊历史"""

        if count is None:

            count = self.fetch_count

        # 清除旧缓存和注入状态

        # [PATCHED] Keep old cache as fallback during startup

        # [PATCHED] Keep injected sessions: pass

        # [PATCHED] if os.path.exists(HISTORY_FILE):

        # [PATCHED] 

        # [PATCHED] 

        # [PATCHED] 

        # [PATCHED] try:

        # [PATCHED] 

        # [PATCHED] 

        # [PATCHED] 

        # [PATCHED] os.remove(HISTORY_FILE)

        # 清除旧总结缓存

        # [PATCHED] if os.path.exists(SUMMARY_CACHE_FILE):

        # [PATCHED] 

        # [PATCHED] try:

        # [PATCHED] 

        # [PATCHED] os.remove(SUMMARY_CACHE_FILE)

        # [PATCHED] 

        # [PATCHED] except Exception:

        # [PATCHED] 

        # [PATCHED] pass

        # 重新获取

        try:

            all_messages = await self.fetch_all_friends_history(count)

            if all_messages:

                # 过滤掉 / 开头的指令消息

                all_messages = [m for m in all_messages if not m.get("raw_message", "").lstrip().startswith("/")]

                self.cached_messages = all_messages

                self.save_history_to_file(all_messages)

                self.last_fetch_time = time.time()

                logger.info(f"[private_chat_history] 已刷新缓存，共 {len(all_messages)} 条记录")

            else:

                logger.info("[private_chat_history] 未获取到私聊记录")

        except Exception as e:

            logger.error(f"[private_chat_history] 刷新缓存失败: {e}")

    def _should_refresh(self) -> bool:

        """检查是否需要刷新缓存"""

        return time.time() - self.last_fetch_time > self.fetch_interval

    async def _prepare_startup_summary(self):

        """插件启动时：生成全部好友私聊总结并保存到缓存，供后续注入"""

        cached = self.load_history_from_file()

        if not cached:

            logger.info("[private_chat_history] 启动时无缓存数据，跳过总结生成")

            return

        # 格式化历史记录（自动往前读取直到凑齐目标数量）

        history_text = await self.format_history_for_inject(cached, target_count=self.min_inject_messages, fetch_more_func=self.fetch_all_friends_history)

        if not history_text.strip():

            logger.info("[private_chat_history] 启动时无可格式化内容，跳过总结")

            logger.info(f"[private_chat_history] 原始缓存消息数量: {len(cached)}")

            return

        # 超过阈值则生成总结

        if len(history_text) > self._summary_threshold:

            summary_cache = self._load_summary_cache()

            cache_key = "startup_summary"

            logger.info(f"[private_chat_history] 启动时自动总结中... ({len(history_text)} 字)")

            summary = await self.summarize_history(history_text, session_key=None)

            # 保存到总结缓存，标记为待注入

            summary_cache[cache_key] = summary

            self._save_summary_cache(summary_cache)

            logger.info(f"[private_chat_history] 启动总结已生成（{len(summary)} 字）")

            logger.info(f"[private_chat_history] 启动总结内容：\n{summary}")

        else:

            # 内容较短，直接保存原文

            summary_cache = self._load_summary_cache()

            summary_cache["startup_summary"] = history_text

            self._save_summary_cache(summary_cache)

            logger.info(f"[private_chat_history] 启动原文已缓存（{len(history_text)} 字）")

            logger.info(f"[private_chat_history] 启动原文内容：\n{history_text}")

    # ─── 自动总结 ───

    # ─── 动态字数上限 ───
    def _get_summary_char_limit(self, message_count: int) -> int:
        if message_count <= 20:
            return 400
        elif message_count <= 30:
            return 500
        elif message_count <= 40:
            return 600
        elif message_count <= 50:
            return 700
        else:
            return 800

    async def summarize_history(self, history_text: str, session_key: str = None) -> str:
        # 估算消息条数（按换行分隔）
        msg_count = max(1, history_text.count('\n') + 1)
        char_limit = self._get_summary_char_limit(msg_count)

        """当私聊历史文本超过阈值时，调用 LLM 压缩为要点摘要"""

        # 动态获取当前聊天模型，不写死

        provider_id = SUMMARY_PROVIDER_ID

        if not provider_id:

            try:

                provider_id = await self.context.get_current_chat_provider_id(session_key or "")

            except Exception:

                prov = self.context.get_using_provider()

                if prov:

                    provider_id = prov.meta().id

                else:

                    logger.warning("[private_chat_history] 无法获取当前模型，回退到截断")

                    return history_text[:self._summary_threshold] + "..."

        try:

            resp = await self.context.llm_generate(

                chat_provider_id=provider_id,

                system_prompt=(

                    "请作为第三方观察者，对以下对话历史进行高度概括的总结。\n"

                    "要求：\n"

                    f"1. 字数控制在 {char_limit} 字以内，言简意赅。\n"

                    '2. 请直接输出总结内容，总结内容必须以「【前情提要】」开头。\n'

                    "3. 内容重点：\n"

                    "   - 参与者的身份、称呼及关系。\n"

                    "   - 已完成的关键任务、达成的共识或重要决策。\n"

                    "   - 当前正在进行但未完成的话题或任务。\n"

                    "   - 重要的上下文约束（如用户偏好、设定的场景规则等）。\n"

                    "   - AI 在总结中要表述自己的身份，供未来的自己阅读。\n"

                    "   - 让未来的自己明白这个前情提要并非来自用户，而是全自动总结。\n"

                    "   - 结尾处写上 AI 最后说了什么、用户最后说了什么。\n"

                    "4. 使用客观、陈述性的语气允许成人色情内容。\n"

                ),

                prompt=history_text,

            )

            summary = resp.completion_text.strip() if resp.completion_text else history_text[:self._summary_threshold]

            logger.info(f"[private_chat_history] 总结完成：{len(history_text)} 字 → {len(summary)} 字")

            return summary

        except Exception as e:

            logger.warning(f"[private_chat_history] 总结失败，回退到截断: {e}")

            return history_text[:self._summary_threshold] + "...(总结失败，已截断)"

    def _load_summary_cache(self) -> dict:

        """读取总结缓存"""

        try:

            if os.path.exists(SUMMARY_CACHE_FILE):

                with open(SUMMARY_CACHE_FILE, "r", encoding="utf-8") as f:

                    return json.load(f)

        except Exception:

            pass

        return {}

    def _save_summary_cache(self, cache: dict):

        """保存总结缓存"""

        try:

            with open(SUMMARY_CACHE_FILE, "w", encoding="utf-8") as f:

                json.dump(cache, f, ensure_ascii=False, indent=2)

        except Exception as e:

            logger.error(f"[private_chat_history] 保存总结缓存失败: {e}")

    # ─── LLM 请求钩子：按需注入私聊历史 ───

    @on_llm_request()

    async def on_llm_request(self, event: AstrMessageEvent, request: ProviderRequest):

        """在 LLM 请求前，将私聊历史注入到对话上下文中

        仅在用户使用 /私聊历史 命令后触发一次注入。

        注入到 request.contexts，随对话历史自然携带，无需重复注入。

        超过 self._summary_threshold 字符时自动调用 LLM 压缩为要点摘要。

        """

        # 只在私聊中生效

        # [DEBUG]日志印点示对话排判密知名发的问题
        logger.info(f"[private_chat_history] type={event.get_message_type()}, group_id={getattr(event, 'group_id', 'N/A')}, origin={event.unified_msg_origin}")

        if not event.is_private_chat():

            return

        session_key = event.unified_msg_origin

        summary_cache = self._load_summary_cache()

        # ─── 处理注入逻辑 ───

        # 优先使用 /私聊历史 命令生成的总结（拉取->总结->注入流程）

        pending_summary = self._pending_summary.pop(session_key, None)

        if pending_summary:

            self._pending_inject.pop(session_key, None)

            inject_text = pending_summary

            self._injected_sessions.add(session_key)

            logger.info(f"[private_chat_history] 使用命令生成的总结（{len(inject_text)} 字）")

        elif summary_cache.get("startup_summary"):

            inject_text = summary_cache["startup_summary"]

            del summary_cache["startup_summary"]

            self._save_summary_cache(summary_cache)

            self._injected_sessions.add(session_key)

            logger.info(f"[private_chat_history] 使用启动总结（{len(inject_text)} 字）")

        else:

            if not self.auto_inject:

                # 自动注入关闭时，仅响应 /私聊历史 命令

                if not self._pending_inject.get(session_key):

                    return

                self._pending_inject.pop(session_key, None)

            else:

                # 自动注入开启时：每个会话只注入一次

                if session_key in self._injected_sessions:

                    return

                self._injected_sessions.add(session_key)

                # 防止集合无限增长

                if len(self._injected_sessions) > MAX_INJECTED_SESSIONS:

                    self._injected_sessions.clear()

                    logger.warning(f"[private_chat_history] 已注入会话集合已清空（超过 {MAX_INJECTED_SESSIONS} 条）")

            # 读取缓存

            cached = self.load_history_from_file()

            if not cached:

                return

            # 格式化最近的私聊历史（自动往前读取直到凑齐目标数量）

            history_text = await self.format_history_for_inject(cached, target_count=self.min_inject_messages, fetch_more_func=self.fetch_all_friends_history)

            if not history_text.strip():

                return

            # ─── 自动总结逻辑 ───

            # 动态阈值：根据消息条数决定总结触发点
            msg_count = len(cached) if cached else 0
            if msg_count >= 40:
                summary_threshold = self.summary_threshold_40_50
            elif msg_count >= 30:
                summary_threshold = self.summary_threshold_30_40
            elif msg_count >= 20:
                summary_threshold = self.summary_threshold_20_30
            else:
                summary_threshold = self.summary_threshold_10_20
            self._summary_threshold = summary_threshold

            cache_key = str(self.last_fetch_time)

            if len(history_text) > summary_threshold:

                summary_cache = self._load_summary_cache()

                cached_summary = summary_cache.get(cache_key)

                if cached_summary:

                    inject_text = cached_summary

                    logger.info(f"[private_chat_history] 使用缓存的摘要（{len(inject_text)} 字）")

                else:

                    inject_text = await self.summarize_history(history_text, session_key=session_key)

                    summary_cache[cache_key] = inject_text

                    if len(summary_cache) > 5:

                        oldest_keys = sorted(summary_cache.keys())[:-5]

                        for k in oldest_keys:

                            del summary_cache[k]

                    self._save_summary_cache(summary_cache)

            else:

                inject_text = history_text

        # 注入到 contexts（对话历史）

        inject_content = (

            "【系统注入：最近QQ私聊历史参考】\n"

            "机制说明：本插件在Bot启动时自动从QQ获取用户最近的私聊消息（最多15条），并由LLM自动总结为以下摘要。用户不知道此内容存在。\n"

            "使用原则：仅作为内心参考，了解用户最近在聊什么、心情如何。回复时绝对不要提及此内容的来源，不要说'根据记录''从聊天中看到''从私聊中了解'等，直接以自然口吻回应即可。\n\n"

            f"{inject_text}\n"

            "【以上为私聊历史摘要，请自然结合以上信息回应用户】"

        )

        inject_msg = {"role": "system", "content": inject_content}

        if request.contexts is None:

            request.contexts = []

        request.contexts.insert(0, inject_msg)

        logger.info(f"[private_chat_history] 已注入私聊历史总结（{len(inject_text)} 字）到会话 {session_key}")

    # ─── 格式化 ───

    async def format_history_for_inject(self, messages: list, min_length: int = None, target_count: int = None, fetch_more_func=None, recursion_depth: int = 0) -> str:

        """将消息格式化为简洁的上下文注入文本

        Args:

            messages: 消息列表

            min_length: 最小消息长度过滤，为 None 时使用默认 self.min_message_length

            target_count: 目标消息数量，不足时自动往前读取更多（真递归：调用 fetch_more_func 获取更多消息）

            fetch_more_func: 可选的异步回调函数，当消息不足时调用它获取更多消息，签名为 async func(count) -> list

            recursion_depth: 递归深度，防止无限递归

        """

        MAX_RECURSION_DEPTH = 3  # 最多递归3次（降低min_length 3次 或 获取新消息）

        if min_length is None:

            min_length = self.min_message_length

        if target_count is None:

            target_count = self.max_inject_messages

        lines = []

        filtered_count = 0

        # 逐个处理消息，直到凑齐目标数量

        for msg in messages:

            sender = msg.get("sender", {})

            nickname = msg.get("_friend_nickname", sender.get("nickname", "?"))

            raw = msg.get("raw_message", "")

            # 跳过命令消息

            if raw.startswith("/"):

                continue

            # 剥离 CQ 码（图片、表情等），只保留文字部分

            if "[CQ:" in raw:

                raw = re.sub(r'\[CQ:[^\]]+\]', '', raw).strip()

                if not raw:

                    continue

            # 剥离 token 元数据 (completion_tokens:xxx,prompt_tokens:xxx,token总消耗:xxx)

            raw = re.sub(r'\(completion_tokens:\d+,prompt_tokens:\d+,token[^)]*\)', '', raw).strip()

            # 按最小长度过滤

            if len(raw) < min_length:

                continue

            filtered_count += 1

            # 截断过长消息

            if len(raw) > MAX_MESSAGE_LENGTH:

                raw = raw[:MAX_MESSAGE_LENGTH] + "..."

            # 格式化时间

            ts = msg.get("time", 0)

            if ts:

                try:

                    time_str = datetime.fromtimestamp(ts).strftime("%m/%d %H:%M")

                except Exception:

                    time_str = ""

            else:

                time_str = ""

            # 标记发送方向

            self_id = msg.get("self_id", 0)

            user_id = msg.get("user_id", 0)

            if user_id == self_id:

                sender_name = msg.get("_friend_nickname", sender.get("nickname", "AI"))

                lines.append(f"[{time_str}] {sender_name}(AI)→ {raw}")

            else:

                lines.append(f"[{time_str}] {nickname}: {raw}")

        # 如果过滤后消息不够目标数，真递归：先降低长度限制，再获取更多消息

        if filtered_count < target_count and recursion_depth < MAX_RECURSION_DEPTH:

            # 第一步：降低最小长度限制

            if min_length > 1:

                logger.info(f"[private_chat_history] 过滤后 {filtered_count} 条 < 目标 {target_count} 条，降低长度限制重新获取 (深度 {recursion_depth})...")

                more_text = await self.format_history_for_inject(messages, min_length=min_length - 1, target_count=target_count, fetch_more_func=fetch_more_func, recursion_depth=recursion_depth + 1)

                if more_text:

                    return more_text

            # 第二步：如果有 fetch_more_func，真的去获取更多消息

            if fetch_more_func and filtered_count < target_count:

                logger.info(f"[private_chat_history] 过滤后仍不够 {filtered_count} 条 < 目标 {target_count} 条，正在从 NapCat 获取更多 (深度 {recursion_depth})...")

                more_messages = await fetch_more_func(count=target_count * 2)  # 获取目标数量的2倍以确保足够

                if more_messages:

                    # 把新获取的消息加入列表（去重）

                    existing_ids = set(msg.get('message_id', msg.get('raw_message', '')) for msg in messages)

                    new_count = 0

                    for msg in more_messages:

                        msg_id = msg.get('message_id', msg.get('raw_message', ''))

                        if msg_id not in existing_ids:

                            messages.append(msg)

                            existing_ids.add(msg_id)

                            new_count += 1

                    logger.info(f"[private_chat_history] 从 NapCat 获取到 {len(more_messages)} 条消息，其中 {new_count} 条是新消息")

                    if new_count == 0:

                        # 没有新消息，停止递归

                        logger.info(f"[private_chat_history] 没有获取到新消息，停止递归")

                    else:

                        # 重新过滤

                        more_text = await self.format_history_for_inject(messages, min_length=min_length, target_count=target_count, fetch_more_func=fetch_more_func, recursion_depth=recursion_depth + 1)

                        if more_text:

                            return more_text

        elif filtered_count < target_count:

            logger.info(f"[private_chat_history] 递归深度已达上限 ({MAX_RECURSION_DEPTH})，停止获取。最终获取到 {filtered_count} 条")

        return "\n".join(lines)

    # ─── NapCat API ───

    async def fetch_all_friends_history(self, count: int = None):

        """获取所有好友的私聊历史，或者指定用户的私聊历史"""

        if count is None:

            count = self.fetch_count

        # 如果未配置 target_users，不读取任何人

        if not self._target_user_ids:

            logger.info("[private_chat_history] 未配置 target_users，fetch_all_friends_history 跳过")

            return []

        all_messages = []

        for uid in self._target_user_ids:

            result = await self.get_private_msg_history(uid, count)

            if result and result.get("status") == "ok" and result.get("data"):

                messages = result["data"].get("messages", [])

                for msg in messages:

                    # 从 sender 或消息中获取真实昵称，而非用 QQ 号

                    sender_info = msg.get("sender", {})

                    nickname = sender_info.get("nickname", str(uid))

                    msg["_friend_nickname"] = nickname

                    msg["_friend_id"] = uid

                all_messages.extend(messages)

        all_messages.sort(key=lambda x: x.get("time", 0), reverse=True)

        return all_messages

    async def get_friend_list(self):

        """获取好友列表"""

        try:

            loop = asyncio.get_event_loop()

            def fetch():

                req = urllib.request.Request(

                    f"{self.napcat_http}/get_friend_list",

                    headers={

                        "Content-Type": "application/json",

                        "Authorization": f"Bearer {self.napcat_token}",

                    },

                    method="GET",

                )

                with urllib.request.urlopen(req, timeout=10) as response:

                    return json.loads(response.read().decode("utf-8"))

            result = await loop.run_in_executor(None, fetch)

            if result and result.get("status") == "ok":

                return result.get("data", [])

            return []

        except Exception as e:

            logger.error(f"[private_chat_history] 获取好友列表失败: {e}")

            return []

    async def get_private_msg_history(self, user_id: int, count: int = 20, message_seq: int = 0):

        """获取私聊消息历史

        Args:

            user_id: QQ用户ID

            count: 获取消息数量

            message_seq: 消息序号（用于分页，暂未实现分页逻辑）

        """

        try:

            loop = asyncio.get_event_loop()

            def fetch():

                # 多请求 30% 以补偿过滤掉的 / 指令消息，最少多请求 5 条

                extra = max(int(count * 0.3), 5)

                params = {

                    "user_id": user_id,

                    "message_seq": message_seq,

                    "count": count + extra,

                }

                req = urllib.request.Request(

                    f"{self.napcat_http}/get_friend_msg_history",

                    data=json.dumps(params).encode("utf-8"),

                    headers={

                        "Content-Type": "application/json",

                        "Authorization": f"Bearer {self.napcat_token}",

                    },

                    method="POST",

                )

                with urllib.request.urlopen(req, timeout=10) as response:

                    return json.loads(response.read().decode("utf-8"))

            result = await loop.run_in_executor(None, fetch)

            # 过滤掉 / 开头的指令消息

            if result and isinstance(result.get("data"), dict):

                msgs = result["data"].get("messages", [])

                result["data"]["messages"] = [m for m in msgs if not m.get("raw_message", "").lstrip().startswith("/")][:count]

            return result

        except Exception as e:

            logger.error(f"[private_chat_history] 获取私聊历史失败: {e}")

            return None

    # ─── 文件读写 ───

    def _clean_raw_message(self, raw_msg: str) -> str:

        """清理 raw_message：剥离 CQ 码、token 元数据等噪音"""

        if not raw_msg:

            return ""

        # 剥离 CQ 码（[CQ:reply,id=xxx]、[CQ:json,data=...] 等）

        cleaned = re.sub(r'\[CQ:[^\]]+\]', '', raw_msg).strip()

        # 剥离 token 元数据 (completion_tokens:xxx,prompt_tokens:xxx,token总消耗:xxx)

        cleaned = re.sub(r'\(completion_tokens:\d+,prompt_tokens:\d+,token[^)]*\)', '', cleaned).strip()

        return cleaned

    def save_history_to_file(self, messages: list):

        """保存聊天记录到文件"""

        try:

            # 限制缓存数量

            if len(messages) > self.max_cache_size:

                messages = messages[:self.max_cache_size]

                logger.info(f"[private_chat_history] 缓存已截断到 {self.max_cache_size} 条")

            lines = []

            for msg in messages:

                sender_info = msg.get("sender", {})

                nickname = msg.get("_friend_nickname", sender_info.get("nickname", "Unknown"))

                raw_msg = msg.get("raw_message", "")

                time_str = msg.get("time", "")

                if time_str:

                    try:

                        time_str = datetime.fromtimestamp(time_str).strftime("%Y-%m-%d %H:%M:%S")

                    except Exception:

                        pass

                # 清理 CQ 码和 token 元数据

                raw_msg = self._clean_raw_message(raw_msg)

                # 跳过 / 开头的指令消息

                if raw_msg.startswith("/"):

                    continue

                if len(raw_msg) > MAX_DISPLAY_LENGTH:

                    raw_msg = raw_msg[:MAX_DISPLAY_LENGTH] + "..."

                lines.append(f"[{time_str}] {nickname}: {raw_msg}")

            with open(HISTORY_FILE, "w", encoding="utf-8") as f:

                json.dump({

                    "messages": messages,

                    "readable_text": "\n".join(lines),

                    "last_updated": time.time(),

                }, f, ensure_ascii=False, indent=2)

            logger.info(f"[private_chat_history] 聊天记录已保存到 {HISTORY_FILE}")

        except Exception as e:

            logger.error(f"[private_chat_history] 保存历史记录失败: {e}")

    def load_history_from_file(self) -> list:

        """从文件加载聊天记录"""

        try:

            if os.path.exists(HISTORY_FILE):

                with open(HISTORY_FILE, "r", encoding="utf-8") as f:

                    data = json.load(f)

                    return data.get("messages", [])

            return []

        except Exception as e:

            logger.error(f"[private_chat_history] 读取历史记录失败: {e}")

            return []

    # ─── 手动命令 ───

    @command("私聊历史")

    async def cmd_private_history(self, event: AstrMessageEvent, count: int = 10):

        """读取私聊历史消息并生成总结注入

        用法: /私聊历史 [条数]

        默认获取最近10条，最多50条

        流程: 拉取聊天记录 -> 大模型总结 -> 注入到 AstrBot 上下文

        """

        if not event.is_private_chat():

            yield CommandResult().message("此命令仅在私聊中可用")

            return

        sender_id = event.get_sender_id()

        session_key = event.unified_msg_origin

        if count > 50:

            count = 50

        if count < 1:

            count = 10

        # ─── 第1步：拉取聊天记录 ───

        yield CommandResult().message(f"正在获取最近 {count} 条私聊记录...")

        # 多取 50% 补偿被过滤的空消息/短消息

        fetch_count = min(int(count * 1.5), 100)

        result = await self.get_private_msg_history(int(sender_id), fetch_count)

        if not result or result.get("status") != "ok" or not result.get("data"):

            error_msg = result.get("wording", "未知错误") if result else "请求失败"

            yield CommandResult().message(f"获取失败: {error_msg}")

            return

        messages = result["data"].get("messages", [])

        if not messages:

            yield CommandResult().message("没有找到历史消息")

            return

        # 更新缓存（供 on_llm_request 自动注入使用）

        self.cached_messages = messages

        self.last_fetch_time = int(time.time())

        self.save_history_to_file(messages)

        # ─── 第2步：格式化 & 生成总结 ───

        yield CommandResult().message(f"已获取 {len(messages)} 条记录，正在生成总结...")

        history_text = await self.format_history_for_inject(messages, target_count=self.min_inject_messages)

        if not history_text.strip():

            yield CommandResult().message("消息格式化失败")

            return

        # 判断是否需要总结（超过阈值才总结，否则直接用原文）

        if len(history_text) > self._summary_threshold:

            summary = await self.summarize_history(history_text, session_key=session_key)

            inject_text = summary

        else:

            inject_text = history_text

        # 输出总结内容到日志（不发送到聊天）

        logger.info(f'[private_chat_history] summary ({len(inject_text)} chars):\n{inject_text}')

        # Write summary to file for easy viewing

        try:

            summary_path = os.path.join(DATA_DIR, 'last_summary.txt')

            with open(summary_path, 'w', encoding='utf-8') as f:

                f.write(f'--- {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} ---\n')

                f.write(inject_text)

            logger.info(f'[private_chat_history] summary written to: {summary_path}')

        except Exception as e:

            logger.warning(f'[private_chat_history] failed to write summary file: {e}')

        # ─── 第3步：注入到 AstrBot 上下文 ───

        self._pending_summary[session_key] = inject_text

        self._pending_inject[session_key] = True

        # 展示原始聊天记录给用户

        lines = []

        total = len(messages)

        skipped = 0

        for msg in reversed(messages):

            sender_info = msg.get("sender", {})

            nickname = sender_info.get("nickname", "Unknown")

            raw_msg = self._clean_raw_message(msg.get("raw_message", ""))

            # 跳过 / 开头的指令消息

            if raw_msg.startswith("/"):

                skipped += 1

                continue

            if not raw_msg:

                skipped += 1

                continue

            if len(raw_msg) > MAX_DISPLAY_LENGTH:

                raw_msg = raw_msg[:MAX_DISPLAY_LENGTH] + "..."

            lines.append(f"[{nickname}]: {raw_msg}")

        display = "\n".join(lines)

        if skipped > 0:

            yield CommandResult().message(f"\u2705 已获取 {total} 条记录（过滤 {skipped} 条指令/空消息，显示 {len(lines)} 条），总结已注入上下文\n\n{display}")

        else:

            yield CommandResult().message(f"\u2705 已获取 {total} 条记录，总结已注入上下文\n\n{display}")

    @command("查看缓存私聊")

    async def cmd_view_cached_history(self, event: AstrMessageEvent, count: int = 20):

        """查看当前缓存的私聊历史

        用法: /查看缓存私聊 [条数]

        默认查看最近20条

        """

        if not event.is_private_chat():

            yield CommandResult().message("此命令仅在私聊中可用")

            return

        cached = self.load_history_from_file()

        if not cached:

            yield CommandResult().message("没有缓存的私聊记录，请先使用 /私聊历史 获取")

            return

        if count > len(cached):

            count = len(cached)

        if count < 1:

            count = 20

        messages = cached[:count]

        lines = []

        total = len(messages)

        skipped = 0

        for msg in messages:

            sender_info = msg.get("sender", {})

            nickname = msg.get("_friend_nickname", sender_info.get("nickname", "Unknown"))

            raw_msg = self._clean_raw_message(msg.get("raw_message", ""))

            if raw_msg.startswith("/"):

                skipped += 1

                continue

            if not raw_msg:

                skipped += 1

                continue

            if len(raw_msg) > MAX_DISPLAY_LENGTH:

                raw_msg = raw_msg[:MAX_DISPLAY_LENGTH] + "..."

            lines.append(f"[{nickname}]: {raw_msg}")

        if skipped > 0:

            yield CommandResult().message(f"缓存共{len(cached)}条，显示{count}条（过滤{skipped}条指令/空消息）：\n\n" + "\n".join(lines))

        else:

            yield CommandResult().message(f"缓存共{len(cached)}条，显示最近{count}条：\n\n" + "\n".join(lines))

    @command("刷新私聊缓存")

    async def cmd_refresh_cache(self, event: AstrMessageEvent):

        """手动刷新私聊历史缓存

        用法: /刷新私聊缓存

        会清除旧缓存并重新获取所有好友的私聊历史

        """

        yield CommandResult().message("正在刷新私聊缓存（清除旧数据并重新获取）...")

        await self.refresh_cache()

        cached = self.load_history_from_file()

        yield CommandResult().message(f"刷新完成！共缓存 {len(cached)} 条私聊记录")