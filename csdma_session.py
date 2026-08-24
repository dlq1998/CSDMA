# ipsm36_q_questioner1.py
# -*- coding: utf-8 -*-

from typing import Dict, List, Tuple, Optional
import argparse
import json
import os
import builtins
from dataclasses import dataclass, field
import traceback
import logging


# —— 智能体 —— #
from agent_router import IPSM_Router
from agent_question_rewriter import rewrite_question
from agent_severity import score_severity_1_4, load_ipsm_levels
# from agent_severity_2 import score_severity_1_4

from datetime import datetime


# 仅保留“题号→题干”与“全部题号列表”
ITEM_PROMPTS: Dict[int, str] = {}
ALL_INDICES: List[int] = []

# ====== 统计模块（新增）========================================
@dataclass
class DialogueStats:
    # 轮次/字符统计
    user_turns: int = 0
    ai_turns: int = 0
    user_chars: int = 0
    ai_chars: int = 0

    # 阶段管理
    current_stage: str = "smalltalk"  # smalltalk | item_flow | soothe
    switch_to_smalltalk_count_total: int = 0
    switch_to_smalltalk_count_human: int = 0
    switch_itemflow_to_smalltalk: int = 0  # NEW: item_flow→smalltalk 次数
    switch_itemflow_to_soothe: int = 0  # NEW: item_flow→soothe 次数

    # 题目相关
    all_indices: list = field(default_factory=list)  # 全部题号
    index_to_prompt: dict = field(default_factory=dict)  # 题号->题干
    answered_indices: set = field(default_factory=set)  # 已成功评分题号

    # 原始 print/input 引用
    _orig_print: callable = None
    _orig_input: callable = None

    def bind_catalog(self, catalog: list):
        """catalog: [{'index': int, 'prompt': str}, ...]"""
        self.all_indices = [it["index"] for it in catalog]
        self.index_to_prompt = {it["index"]: it["prompt"] for it in catalog}

    def mark_answered(self, idx: int):
        self.answered_indices.add(idx)

    # —— 阶段切换 —— #
    def switch_to_smalltalk(self, reason: str = "system"):
        """
        reason: "human" | "system"
        只有发生阶段变化时才计数；
        - 总计数：总是 +1
        - 人为计数：仅当 reason == "human" 时 +1
        - item_flow→smalltalk：额外单独计数
        """
        if self.current_stage != "smalltalk":
            self.switch_to_smalltalk_count_total += 1
            if self.current_stage == "item_flow":
                self.switch_itemflow_to_smalltalk += 1
            if reason == "human":
                self.switch_to_smalltalk_count_human += 1
        self.current_stage = "smalltalk"

    def switch_to_item_flow(self):
        self.current_stage = "item_flow"

    def switch_to_soothe(self):
        # 只有从 item_flow 切过去才计数（smalltalk→soothe 不算）
        if self.current_stage == "item_flow":
            self.switch_itemflow_to_soothe += 1
        self.current_stage = "soothe"

    def set_stage_smalltalk_no_count(self):
        """只更新阶段，不做任何计数。用于‘问完&无跳过’的自然收束。"""
        self.current_stage = "smalltalk"

    # —— 封装 print/input —— #
    def patch_io(self):
        """全局替换 print/input，用于自动记 AI/用户说话与长度"""
        if self._orig_print is None:
            self._orig_print = builtins.print
        if self._orig_input is None:
            self._orig_input = builtins.input

        def _print_wrapper(*args, **kwargs):
            text = " ".join(str(a) for a in args)
            # 过滤掉形如 [ROUTER-1] / [DEBUG] 这类日志行
            if not text.lstrip().startswith("["):
                self.ai_turns += 1
                self.ai_chars += len(text)
            return self._orig_print(*args, **kwargs)

        def _input_wrapper(prompt=""):
            # 输入提示不计入 AI 发言/字数（避免抬高轮次与AI平均字数）
            if prompt:
                self._orig_print(prompt, end="")
            user_text = self._orig_input()
            self.user_turns += 1
            self.user_chars += len(user_text)
            return user_text

        builtins.print = _print_wrapper
        builtins.input = _input_wrapper

    def unpatch_io(self):
        if self._orig_print:
            builtins.print = self._orig_print
        if self._orig_input:
            builtins.input = self._orig_input

    # —— 导出统计 —— #
    def export_dialogue_stats(self) -> dict:
        # 平均字数（分母至少为 1，避免除零）
        avg_user = round(self.user_chars / max(1, self.user_turns), 2)
        avg_ai = round(self.ai_chars / max(1, self.ai_turns), 2)

        # 你的定义：总对话轮数 = AI 发言数 + 用户发言数
        total_turns = self.user_turns + self.ai_turns

        return {
            "total_turns": total_turns,  # (1) 总对话轮数
            "avg_user_chars_per_turn": avg_user,  # (2) 平均每轮用户文字数
            "avg_assistant_chars_per_turn": avg_ai,  # (3) 平均每轮AI文字数
            "itemflow_to_smalltalk_count": self.switch_itemflow_to_smalltalk,  # (4)
            "itemflow_to_soothe_count": self.switch_itemflow_to_soothe,  # (5)

            # 兼容保留你原来已有的几个统计键（如有下游脚本依赖不至于断）
            "switch_to_smalltalk_count": self.switch_to_smalltalk_count_human,
            "switch_to_smalltalk_count_total": self.switch_to_smalltalk_count_total,
            "total_user_rounds": self.user_turns,
        }

    def export_unanswered_items(self) -> list:
        unanswered = []
        ans = self.answered_indices
        for idx in self.all_indices:
            if idx not in ans:
                unanswered.append({
                    "index": idx,
                    "prompt": self.index_to_prompt.get(idx, "")
                })
        return unanswered




# 全局实例
STATS = DialogueStats()
STATS.patch_io()
# ====== 统计模块（新增）========================================


def load_items_json(path: str) -> int:
    """
    读取 IPSM-CS_items.json（纯数组）并初始化全局索引与题干映射。
    格式要求：[{ "index": int, "prompt": str }, ...]
    返回：题目总数
    """
    global ITEM_PROMPTS, ALL_INDICES
    ITEM_PROMPTS, ALL_INDICES = {}, []

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("IPSM-CS_items.json 必须是数组：[{\"index\": int, \"prompt\": str}, ...]")

    for it in data:
        idx = int(it["index"])
        prm = (it.get("prompt") or "").strip() or f"第{idx}条"
        ITEM_PROMPTS[idx] = prm
        ALL_INDICES.append(idx)

    ALL_INDICES.sort()
    return len(ALL_INDICES)

def _all_item_indices() -> List[int]:
    return sorted(ITEM_PROMPTS.keys())

def _lookup_prompt(idx: int) -> str:
    return ITEM_PROMPTS.get(idx, f"第{idx}条")


class ChatSession:
    def __init__(self, items_file: str, auto_follow: bool = False):
        """
        :param items_file: IPSM-CS_items.json 的文件路径。
        :param auto_follow: 未出现抵触时是否自动连续提问（True 更流畅；False 一问一停）。
        """
        if not os.path.exists(items_file):
            raise FileNotFoundError(f"未找到题干文件：{items_file}")

        n = load_items_json(items_file)
        print(f"[已载入题干] {items_file} ；共 {n} 条")

        STATS.bind_catalog([
            {"index": idx, "prompt": ITEM_PROMPTS.get(idx, f"第{idx}条")}
            for idx in ALL_INDICES
        ])

        # 预热评分参考（与 agent_severity 内部保持一致的加载方式）
        try:
            load_ipsm_levels()
        except Exception as e:
            print("[警告] 未找到 ipsm-cs_level.json，严重度评分时可能失败")

        # 顺序提问：不使用 Q-learning
        self.history: List[Tuple[str, str]] = []  # (role, text)
        self.records: Dict[int, int] = {}          # index -> score
        self.score_reasons: Dict[int, str] = {}    # index -> reason（新增）
        self.mode: str = "smalltalk"  # smalltalk | item_flow
        self.auto_follow = bool(auto_follow)


        # 与 agent_router 对齐——使用类实例
        self.router = IPSM_Router()
        self.already_asked = set()  # 本次会话已问/准备问的题号
        self.skipped_items: List[int] = []  # 记录“暂缓/跳过，稍后回访”的题号（按加入顺序）
        self.last_sev: int = 0  # 记录上一题的评分

        # ==== 新增：smalltalk 征询与“第3轮征询”计数 ====
        self.idle_smalltalk_rounds = 0    # 连续“非人际 & 非消极”的轮数
        self.idle_threshold = 2           # 两轮后，第3轮征询
        self.awaiting_consent = False     # 刚发了“愿意聊人际吗？”等待答复
        self._first_item_suggested = None # smalltalk 路由给的首题索引（如有）

        self._already_replied_this_turn = False  # 本轮是否已经输出过自然回复

    def _coerce_score(self, val) -> int:
        """
        将 score_severity_1_4 的返回统一转成 int。
        - 支持两种返回：dict（含 "score"）或直接 int
        - 异常时返回 0
        """
        try:
            if isinstance(val, dict):
                return int(val.get("score", 0))
            return int(val)
        except Exception:
            return 0

    # —— 小工具 —— #
    def _emit_smalltalk_now(self) -> dict:
        # 取最近一条用户输入
        last_user = self._last_user_text()

        # —— 量表是否已全部问完：问完则临时把阈值拉到极大，等价于关闭“第3轮征询” —— #
        all_done = len(self.already_asked) >= len(ALL_INDICES)
        effective_idle_threshold = (10 ** 9) if all_done else int(self.idle_threshold)

        try:
            route = self.router.route_smalltalk_state(
                user_text=last_user,
                history=self.history[-8:],  # 用近窗口历史，判别更稳
                asked_indices=sorted(self.already_asked),
                idle_smalltalk_rounds=int(self.idle_smalltalk_rounds),
                idle_threshold=effective_idle_threshold,  # ← 用有效阈值
            )
        except Exception as e:
            print("[FATAL] pipeline crashed:", e)
            traceback.print_exc()
            # 兜底：极简一句（仅在 LLM 崩溃时使用）
            self._say("我在，先缓一缓，慢慢来。")
            self.mode = "smalltalk"
            return {}

        # 结束优先
        if route.get("end_session"):
            self._say("好的，那我们先到这里。如有需要，随时再来找我。")
            self.mode = "end"
            return route

        # —— 判定阶段：只看本轮文本（两票复判，避免被上一轮助手话术带偏）——
        neg = self._llm_neg_affect_consensus(last_user)
        interpersonal = self._llm_interpersonal_consensus(last_user)
        next_item = route.get("item_to_ask") or []

        # 规则0：需“谨慎确认”的消极且非人际 → 两票复判后才切 soothe（只看本轮文本）
        if neg and (not interpersonal):
            STATS.switch_to_soothe()
            self.mode = "soothe"
            self.idle_smalltalk_rounds = 0
            try:
                s = self.router.route_soothe_state(user_text=last_user, history=self.history[-8:])
                brief = (s.get("soothe_reply") or "").strip()
                if brief:
                    self._say(brief)
                if not s.get("continue_soothe") and not s.get("return_to_smalltalk"):
                    s["continue_soothe"] = True
                return s
            except Exception as e:
                print("[ERROR][smalltalk->soothe dispatch] LLM failed:", e)
                traceback.print_exc()
                self._say("我在，先缓一缓，慢慢来。")
                return {"continue_soothe": True, "return_to_smalltalk": False, "end_session": False}

        # 规则1：只要有人际 → 直接切 item_flow；不输出 smalltalk
        if interpersonal:
            STATS.switch_to_item_flow()
            self.mode = "item_flow"
            try:
                self._first_item_suggested = int(next_item[0]["index"]) if next_item else None
            except Exception:
                self._first_item_suggested = None
            self.idle_smalltalk_rounds = 0
            self.awaiting_consent = False
            return route

        # —— 常规闲聊：只输出 LLM 的 smalltalk_reply（其中若到达阈值，LLM 会自己把邀请合进去） —— #
        bot = (route.get("smalltalk_reply") or "").strip()
        if bot:
            self._say(bot)

        # 仅在“非人际 & 非消极”的纯闲聊回合里计数，否则清零
        if (not interpersonal) and (not neg):
            self.idle_smalltalk_rounds += 1
        else:
            self.idle_smalltalk_rounds = 0

        self.mode = "smalltalk"
        return route

    def _llm_interpersonal_consensus(self, user_text: str, history: list | None = None) -> bool:
        """
        对同一输入做两次 smalltalk 路由；两次都判 is_interpersonal=True 才算真。
        —— 重要：history 仅包含“本轮用户文本”，避免被助手上一轮话术干扰。
        """
        minimal_hist = [("user", user_text)]
        r1 = self.router.route_smalltalk_state(
            user_text=user_text,
            history=minimal_hist,
            asked_indices=sorted(self.already_asked),
            idle_smalltalk_rounds=int(self.idle_smalltalk_rounds),
            idle_threshold=int(self.idle_threshold),
        )
        r2 = self.router.route_smalltalk_state(
            user_text=user_text,
            history=minimal_hist,
            asked_indices=sorted(self.already_asked),
            idle_smalltalk_rounds=int(self.idle_smalltalk_rounds),
            idle_threshold=int(self.idle_threshold),
        )
        return bool(r1.get("is_interpersonal")) and bool(r2.get("is_interpersonal"))

    def _llm_neg_affect_consensus(self, user_text: str) -> bool:
        """
        smalltalk 路由做两次判定；只有两次都判定“本轮用户文本”存在显著消极情绪，才返回 True。
        注意：history 只放本轮用户文本，避免被上一轮助手话术污染。
        """
        minimal_hist = [("user", user_text)]
        r1 = self.router.route_smalltalk_state(
            user_text=user_text,
            history=minimal_hist,
            asked_indices=sorted(self.already_asked),
            idle_smalltalk_rounds=int(self.idle_smalltalk_rounds),
            idle_threshold=int(self.idle_threshold),
        )
        r2 = self.router.route_smalltalk_state(
            user_text=user_text,
            history=minimal_hist,
            asked_indices=sorted(self.already_asked),
            idle_smalltalk_rounds=int(self.idle_smalltalk_rounds),
            idle_threshold=int(self.idle_threshold),
        )
        return bool(r1.get("neg_affect")) and bool(r2.get("neg_affect"))

    # ——— 统一写入到 history（问卷题目时可带 index） ———
    def _push_history(self, role: str, text: str, index: int | None = None):
        rec = {"role": role, "text": text}
        if index is not None:
            rec["index"] = int(index)
        self.history.append(rec)

    # ——— 兼容：把 history 中的元素（元组/字典）统一成 (role, text) ———
    def _iter_history_pairs(self):
        for h in self.history:
            if isinstance(h, dict):
                yield (h.get("role", ""), h.get("text", ""))
            else:
                # 兼容旧格式: ("assistant", "文本")
                yield (h[0], h[1])

    def _history_context(self, tail: int = 12) -> str:
        lines = []
        pairs = list(self._iter_history_pairs())[-tail:]
        for r, t in pairs:
            prefix = "用户" if r == "user" else "助手"
            lines.append(f"{prefix}: {t}")
        return "\n".join(lines) or "(无)"

    def _last_user_text(self) -> str:
        """返回 history 中最近一条用户文本（兼容字典格式与旧的('user', text)元组格式）"""
        for h in reversed(self.history):
            if isinstance(h, dict):
                if h.get("role") == "user":
                    return h.get("text", "")
            else:
                # 兼容旧格式: ("user", "文本")
                try:
                    if h[0] == "user":
                        return h[1]
                except Exception:
                    continue
        return ""

    def _say(self, text: str):
        """统一的输出口：打印 + 写入历史 + 标记本轮已回复"""
        text = (text or "").strip()
        if not text:
            return
        print(text)
        self._push_history("assistant", text)  # 小聊/安抚等不带 index
        self._already_replied_this_turn = True

    # —— 选题策略 —— #
    def select_item_to_ask(self, asked: List[int], skipped: List[int]) -> Optional[int]:
        """按顺序提问；先完成未跳过条目，最后按加入顺序回访 skipped。"""
        # 先返回尚未问过且未被标记跳过的条目
        for item in ALL_INDICES:
            if item not in asked and item not in skipped:
                return item

        # 所有常规条目都问完后，再回来提问跳过的条目（保持加入顺序）
        for item in skipped:
            if item not in asked:
                return item

        return None

    # —— 单题流程（仅在 item_flow 执行） —— #
    def ask_item_and_score(self, idx: int) -> bool:
        """单题流程（仅在 item_flow 执行）：首问→判定→必要时二次追问→评分/跳过→顺序选下一题"""
        if self.mode != "item_flow":
            return False

        # 每次调用时，直接使用最新的已问和跳过列表
        asked = sorted(self.already_asked)  # 已问条目
        skipped = self.skipped_items  # 跳过条目

        base = _lookup_prompt(idx)
        context = self._history_context(tail=12)

        # print(f"[DEBUG] 开始条目流 -> 当前题序号:{idx}, 已问集合:{sorted(self.already_asked)}")

        # 1) 首问改写
        try:
            question = rewrite_question(base, context=context, mode="first")
        except Exception as e:
            print(f"[问句改写失败] {e}")
            question = f"想请你聊聊：{base}（如果方便的话）"

        print(question)
        self._push_history("assistant", question, index=idx)  # ✅ 首问带 index
        self.last_assistant_text = question  # 记录本题问法，供评分/二问使用

        # 2) 首答
        reply1 = input("你的回复：").strip()
        self._push_history("user", reply1)

        # 3) 首判
        try:
            chk1 = self.router.route_itemflow_state(
                user_text=reply1,
                history=[("assistant", question), ("user", reply1)],
                current_index=idx
            )
            # print(f"[ROUTER-1] idx={idx} accept={bool(chk1.get('accept'))} "
            #       f"offtopic={bool(chk1.get('offtopic'))} resistance={bool(chk1.get('resistance'))}")
        except Exception as e:
            print(f"[router 解析失败] {e}，先回到随意聊聊。")
            STATS.switch_to_smalltalk()
            self.mode = "smalltalk"
            return True

        res1 = bool(chk1.get("resistance", False))
        off1 = bool(chk1.get("offtopic", False))
        acc1 = bool(chk1.get("accept", False))
        # print(f"[DEBUG] 首判 -> accept={acc1}, resistance={res1}, offtopic={off1}")
        # st1 = chk1.get("smalltalk_reply") or "理解你的感受，我们先随便聊聊也可以。"
        st1 = chk1.get("smalltalk_reply")

        if chk1.get("end_session"):
            self.summarize_and_exit()
            raise SystemExit

        # —— 先处理“可评分” —— #
        if acc1:
            try:
                sev_val = score_severity_1_4(
                    reply1,
                    item_index=idx,
                    question_text=self.last_assistant_text,
                    context_text=self._history_context(tail=6)
                )
                score = self._coerce_score(sev_val)
                # 新增：从返回的 dict 中拿出 reason（如果有）
                reason = ""
                if isinstance(sev_val, dict):
                    reason = str(sev_val.get("reason", "")).strip()
            except Exception as e:
                print(f"[评分失败] {e}")
                score = 0
                reason = ""

            if 1 <= score <= 4:
                self.last_sev = score
                self.records[idx] = score
                self.score_reasons[idx] = reason  # ⭐ 新增：保存理由
                STATS.mark_answered(idx)
                if idx not in self.already_asked:
                    self.already_asked.add(idx)
                # print(f"[SEV] 序号 {idx}｜分数 {score}")
            else:
                # 标记稍后回访：不记为已答，加入 skipped 列表以便回访轮处理
                if idx not in self.skipped_items:
                    self.skipped_items.append(idx)
                print(f"[DEFER] 序号 {idx}｜评分无效，稍后回访")

            nxt = self.select_item_to_ask(
                asked=sorted(self.already_asked),
                skipped=self.skipped_items
            )
            # print(f"[FOLLOWUP] next={'None' if not nxt else nxt}")

            # ==== 🧩 修复：若没有下一题，自动切换到闲聊模式 ==== #
            if nxt is None:
                print("[ITEMFLOW] 所有题目已完成，系统切换至 smalltalk。")
                STATS.set_stage_smalltalk_no_count()  # 同步阶段但不累加
                self.mode = "smalltalk"
                self.idle_smalltalk_rounds = 0
                route = self._emit_smalltalk_now() or {}
                if route.get("item_to_ask") or route.get("is_interpersonal"):
                    # 若 smalltalk 又想触发问答，则忽略，保持 smalltalk
                    STATS.set_stage_smalltalk_no_count()
                    self.mode = "smalltalk"
                return True

            # 若还有题目，继续问下一题
            return self.ask_item_and_score(nxt)


        # —— 再处理“抵触” —— #
        if res1:
            r0 = self.router.route_smalltalk_state(
                user_text=reply1,
                history=self.history[-8:],  # 生成承接用近窗口即可
                asked_indices=sorted(self.already_asked),
                idle_smalltalk_rounds=int(self.idle_smalltalk_rounds),
                idle_threshold=int(self.idle_threshold),
            )
            self._say((r0.get("smalltalk_reply") or "").strip())
            STATS.switch_to_smalltalk("human")
            self.mode = "smalltalk"
            self.idle_smalltalk_rounds = 0
            return True

        # —— 再处理“跑题→二次追问”的入口（保留你原逻辑）——
        effective_reply = reply1
        if off1:
            try:
                re_q = rewrite_question(base, context=self._history_context(12),
                                        mode="reask", last_question=question)
            except Exception as e:
                print(f"[二次追问改写失败] {e}")
                re_q = f"那我换个问法：关于“{base}”，这类情况大概在什么场景更常出现呢？"

            print(re_q)
            self._push_history("assistant", re_q, index=idx)  # ✅ 再次提问也带 index

            reply2 = input("你的回复：").strip()
            self._push_history("user", reply2)

            try:
                chk2 = self.router.route_itemflow_state(
                    user_text=reply2,
                    history=[("assistant", re_q), ("user", reply2)],
                    current_index=idx
                )
                # print(f"[ROUTER-2] idx={idx} accept={bool(chk2.get('accept'))} "
                #       f"offtopic={bool(chk2.get('offtopic'))} resistance={bool(chk2.get('resistance'))}")
            except Exception as e:
                print(f"[router 解析失败] {e}，先回到随意聊聊。")
                STATS.switch_to_smalltalk()
                self.mode = "smalltalk"
                return True
            # —— 注意：后面还有二次判定的分支处理（保持你原有的逻辑）——
            # 这里不 return，让后续代码继续处理 chk2
            # （如果你的代码后面本来就在这里 return，请按你的结构保留）
            # --------------- 到此为止，首判分支的顺序调整完成 ---------------

            # 二判：读取路由信号（仅看本轮回复）
            res2 = bool(chk2.get("resistance", False))
            off2 = bool(chk2.get("offtopic", False))
            acc2 = bool(chk2.get("accept", False))
            # print(f"[DEBUG] 二判 -> accept={acc2}, resistance={res2}, offtopic={off2}")

            if chk2.get("end_session"):
                self.summarize_and_exit()
                raise SystemExit

            # —— 先处理“可评分”（二判） —— #
            if acc2:
                try:
                    sev_val = score_severity_1_4(
                        reply2,
                        item_index=idx,
                        question_text=re_q,
                        context_text=self._history_context(tail=6)
                    )
                    sev = self._coerce_score(sev_val)
                    # ⭐ 新增：从返回的 dict 中拿 reason（若有）
                    reason2 = ""
                    if isinstance(sev_val, dict):
                        reason2 = str(sev_val.get("reason", "")).strip()
                except Exception as e:
                    print(f"[评分失败] {e}")
                    sev = 0
                    reason2 = ""  # ⭐ 异常时把 reason 也置空，防止引用未定义变量

                if 1 <= sev <= 4:
                    self.last_sev = sev
                    self.records[idx] = sev
                    self.score_reasons[idx] = reason2   # ⭐ 同步保存二次评分的理由
                    STATS.mark_answered(idx)
                    if idx not in self.already_asked:
                        self.already_asked.add(idx)
                    # print(f"[SEV] 序号 {idx}｜分数 {sev}")
                else:
                    if idx not in self.skipped_items:
                        self.skipped_items.append(idx)
                    print(f"[DEFER] 序号 {idx}｜评分无效，稍后回访")

                nxt = self.select_item_to_ask(
                    asked=sorted(self.already_asked),
                    skipped=self.skipped_items
                )
                # print(f"[FOLLOWUP] next={'None' if not nxt else nxt}")

                # ==== 🧩 修复：若没有下一题，自动切换到闲聊模式 ==== #
                if nxt is None:
                    print("[ITEMFLOW] 所有题目已完成，系统切换至 smalltalk。")
                    STATS.set_stage_smalltalk_no_count()  # 同步阶段但不累加
                    self.mode = "smalltalk"
                    self.idle_smalltalk_rounds = 0
                    route = self._emit_smalltalk_now() or {}
                    if route.get("item_to_ask") or route.get("is_interpersonal"):
                        STATS.set_stage_smalltalk_no_count()
                        self.mode = "smalltalk"
                    return True

                # 若还有题目，继续问下一题
                return self.ask_item_and_score(nxt)

            # —— 再处理“抵触”（二判） —— #
            if res2:
                r0 = self.router.route_smalltalk_state(
                    user_text=reply2,
                    history=self.history[-8:],
                    asked_indices=sorted(self.already_asked),
                    idle_smalltalk_rounds=int(self.idle_smalltalk_rounds),
                    idle_threshold=int(self.idle_threshold),
                )
                self._say((r0.get("smalltalk_reply") or "").strip())
                STATS.switch_to_smalltalk("human")
                self.mode = "smalltalk"
                self.idle_smalltalk_rounds = 0
                return True

            # —— 再处理“跑题”（二判） —— #
            if off2:
                if idx not in self.skipped_items:
                    self.skipped_items.append(idx)
                nxt = self.select_item_to_ask(asked=sorted(self.already_asked), skipped=self.skipped_items)
                if nxt is not None:
                    return self.ask_item_and_score(nxt)
                STATS.switch_to_smalltalk("human")
                self.mode = "smalltalk"
                self.idle_smalltalk_rounds = 0
                self._emit_smalltalk_now()
                return True

            # —— 最后才考虑“安抚”（二判；仅当不可评分且非抵触/跑题）—— #
            if bool(chk2.get("need_soothe", False)):
                STATS.switch_to_soothe()
                self.mode = "soothe"
                # 当轮立刻输出安抚话术（用二次触发文本 reply2）
                try:
                    s = self.router.route_soothe_state(user_text=reply2, history=self.history[-8:])
                    brief = (s.get("soothe_reply") or "").strip()
                    if brief:
                        self._say(brief)
                except Exception:
                    self._say("我在，先缓一缓，慢慢来。")
                return True

            # —— 仍非 acc/res/off 且也不 soothe（兜底，二判）—— #
            if idx not in self.skipped_items:
                self.skipped_items.append(idx)
            nxt = self.select_item_to_ask(asked=sorted(self.already_asked), skipped=self.skipped_items)
            if nxt is not None:
                return self.ask_item_and_score(nxt)
            STATS.switch_to_smalltalk("human")
            self.mode = "smalltalk"
            self.idle_smalltalk_rounds = 0
            self._emit_smalltalk_now()
            return True

        # —— 首判兜底：仅当 acc1/res1/off1 都为 False 时才会走到这里 —— #
        neg1 = bool(chk1.get("need_soothe", False))  # 路由判断的“需安抚”信号（代表显著消极）

        if neg1:
            STATS.switch_to_soothe()
            self.mode = "soothe"
            # 当轮立刻输出安抚话术（用本次触发文本 reply1）
            try:
                s = self.router.route_soothe_state(user_text=reply1, history=self.history[-8:])
                brief = (s.get("soothe_reply") or "").strip()
                if brief:
                    self._say(brief)
            except Exception:
                self._say("我在，先缓一缓，慢慢来。")
            return True

        # 否则：没有消极情绪 → 不退安抚，直接跳过当前条目并“继续 item_flow”
        if idx not in self.skipped_items:
            self.skipped_items.append(idx)

        nxt = self.select_item_to_ask(
            asked=sorted(self.already_asked),
            skipped=self.skipped_items
        )
        if nxt is not None:
            # 继续在 item_flow 里问下一题（不回 smalltalk）
            return self.ask_item_and_score(nxt)

        # 若没有剩余条目了 → 才回到 smalltalk（清零闲聊计数）
        STATS.switch_to_smalltalk("human")
        self.mode = "smalltalk"
        self.idle_smalltalk_rounds = 0
        self._emit_smalltalk_now()
        return True

    def maybe_followup_next(self) -> bool:
        """顺序续问：按顺序挑下一题；若无剩余则回到 smalltalk 并自然过渡。"""
        asked = sorted(self.already_asked)  # 已问条目
        skipped = self.skipped_items  # 跳过的条目

        # 优先选择未跳过的问题
        nxt = self.select_item_to_ask(asked=asked, skipped=skipped)

        if nxt is None:
            # 检查是否有未问过的条目
            if len(ALL_INDICES) == len(self.already_asked):  # 所有条目都已经问过了
                # 若所有问题都已经问过，检查是否有跳过的题目需要回访
                if skipped:
                    nxt = skipped[0]  # 回访跳过的第一个题目
                else:
                    # —— 所有题目均完成，无跳过 → 自然收束到 smalltalk —— #
                    STATS.set_stage_smalltalk_no_count()
                    self.mode = "smalltalk"
                    self.idle_smalltalk_rounds = 0

                    # 调用 smalltalk，但禁止它再次触发 item_flow
                    route = self._emit_smalltalk_now() or {}
                    if route.get("is_interpersonal") or route.get("item_to_ask"):
                        # 若 smalltalk 想再次触发问答，忽略并强制留在 smalltalk
                        STATS.set_stage_smalltalk_no_count()
                        self.mode = "smalltalk"
                        self.idle_smalltalk_rounds = 0
                    return False
            else:
                # 如果还有其他未问的题目，则继续提问
                nxt = self.select_item_to_ask(asked=asked, skipped=skipped)

        # print(f"[DEBUG] 顺序续问 -> 序号:{nxt}")
        if nxt is None:
            return False
        return self.ask_item_and_score(nxt)

    # —— 结束汇总 —— #
    def summarize_and_exit(self):
        # STATS._orig_print("【本次对话小结】")

        if not self.records:
            # STATS._orig_print("本次暂未形成可用评分记录。感谢你的分享！")
            self._save_session_json(total=0, avg=0.0)
            return

        total = 0
        items_out = []
        for idx in sorted(self.records.keys()):
            sc = int(self.records[idx])
            prompt = ITEM_PROMPTS.get(idx, f"第{idx}条")
            # STATS._orig_print(f"- 序号 {idx:>2}｜分数 {sc}｜{prompt}")
            total += sc
            items_out.append({"index": idx, "prompt": prompt, "score": sc})

        avg = total / len(self.records)
        max_total = 4 * len(self.records)  # 4分制
        # STATS._orig_print(f"—— 共 {len(self.records)} 条，平均分 {avg:.2f}；总分 {total}/{max_total}（仅供参考，不具诊断意义）")
        STATS._orig_print("感谢你的分享。如果以后想继续，我们随时可以再聊。")

        self._save_session_json(total=total, avg=avg)

    def _save_session_json(self, total: int, avg: float):
        try:
            out_dir = os.path.join(os.path.dirname(__file__), "sessions")
            os.makedirs(out_dir, exist_ok=True)
            fname = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            path = os.path.join(out_dir, fname)

            items = [
                {
                    "index": idx,
                    "prompt": ITEM_PROMPTS.get(idx, f"第{idx}条"),
                    "score": int(self.records[idx]),
                    "reason": self.score_reasons.get(idx, "")  # ⭐ 新增字段
                }
                for idx in sorted(self.records.keys())
            ]

            payload = {
                "meta": {
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "item_count": len(items),
                    "total_score": int(total),
                    "max_total": 4 * len(items),
                    "average": float(avg),
                    "mode_end": self.mode,
                },
                "records": items,
                "history": [
                    (h if isinstance(h, dict) else {"role": h[0], "text": h[1]})
                    for h in self.history
                ]
            }

            # ===== 新增：对话统计 =====
            payload["dialogue_stats"] = STATS.export_dialogue_stats()

            # ===== 新增：未回答题目清单 =====
            payload.setdefault("scores", {})
            payload["scores"]["unanswered_items"] = STATS.export_unanswered_items()

            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            print(f"[保存] 会话已保存：{path}")
        except Exception as e:
            print(f"[WARN] 保存会话 JSON 失败：{e}")

    # —— 主循环 —— #
    def run(self) -> None:
        self._say("你好～想和你聊聊生活，也想增进对你的了解，你愿意和我分享吗？你最近有什么让你开心或在意的事吗？")

        # 初始进入 smalltalk；_emit_smalltalk_now 内部会根据 LLM 判断是否切换为 item_flow
        if not getattr(self, "mode", None):
            self.mode = "smalltalk"

        while True:
            # === 读取用户输入（按模式切换提示语）===
            if self.mode == "item_flow":
                prompt_label = "你的回复："
            elif self.mode == "soothe":
                prompt_label = "你（此刻的感受）："
            else:
                prompt_label = "你："

            user = input(prompt_label).strip()
            if not user:
                continue

            # 记录用户输入
            self._push_history("user", user)
            # —— 重置“本轮已说话”标记（新一轮从未说话开始）——
            self._already_replied_this_turn = False

            # === soothe：只安抚，不发题（需放在 smalltalk 之前）===
            if self.mode == "soothe":
                try:
                    # 用“触发安抚”的最近一条用户文本，而不是外层 user 变量
                    last_user2 = self._last_user_text()
                    s = self.router.route_soothe_state(user_text=last_user2, history=self.history[-8:])
                except Exception as e:
                    print("[ERROR][soothe] crashed:", e)
                    traceback.print_exc()
                    # 宽松兜底：留在 soothe，给一条轻安抚
                    s = {"continue_soothe": True, "soothe_reply": "我在，先缓一缓，慢慢来。",
                         "end_session": False, "is_interpersonal": False, "return_to_smalltalk": False}

                # 结束会话
                if s.get("end_session"):
                    self.summarize_and_exit()
                    break

                # 取本轮用户原话（用于两票复判）
                last_user = self._last_user_text()

                # [A] 强人际优先：两票一致判为人际 -> 当轮“直接入题”（不再先发安抚句，避免同轮双回复）
                if s.get("is_interpersonal") and self._llm_interpersonal_consensus(last_user, history=[("user", last_user)]):
                    STATS.switch_to_item_flow()  # ← 同步阶段，保证后续 item_flow→soothe 计数
                    self.mode = "item_flow"
                    target_idx = self.select_item_to_ask(
                        asked=sorted(self.already_asked),
                        skipped=self.skipped_items
                    )
                    if target_idx is None:
                        # 无题可问则回小聊（只打一条 smalltalk）
                        STATS.set_stage_smalltalk_no_count()  # 自然收束；同步阶段但不+1
                        self.mode = "smalltalk"
                        self.idle_smalltalk_rounds = 0
                        _ = self._emit_smalltalk_now() or {}
                    else:
                        self.ask_item_and_score(target_idx)
                        # 一问一停：发题后回小聊
                        if self.mode == "item_flow":
                            STATS.set_stage_smalltalk_no_count()  # ← 同步阶段但不计数
                            self.mode = "smalltalk"
                    continue

                # [B] 回小聊优先（非强人际时）：不要再输出 soothe_reply，直接回小聊（只打一条 smalltalk）
                if s.get("return_to_smalltalk"):
                    STATS.set_stage_smalltalk_no_count()  # 同步阶段，仍不计数
                    self.mode = "smalltalk"
                    self.idle_smalltalk_rounds = 0  # 重新进入闲聊 → 阈值计数重置
                    _ = self._emit_smalltalk_now() or {}
                    continue

                # [C] 正常安抚输出（留在 soothe 态，仅打一条安抚句）
                # ✦ 节流：若本轮已经在条目流里“立即安抚”回过一句，则本分支不再重复输出
                if not self._already_replied_this_turn:
                    brief = (s.get("soothe_reply") or "").strip()
                    if brief:
                        self._say(brief)
                continue

            # smalltalk 阶段（内部会打印 bot，并依据 trigger 设置 self.mode）
            route = self._emit_smalltalk_now() or {}
            # 若 smalltalk 内切换成 soothe，则本轮直接进入 soothe 分支处理，避免兜底报“未知模式”
            if self.mode == "soothe":
                continue

            # 若用户表达想结束，则收尾并退出
            if route.get("end_session"):
                self.summarize_and_exit()  # 结束并总结
                break  # 退出对话

            # ===== 进入条目流 =====
            if self.mode == "item_flow":
                target_idx = None
                cand = route.get("item_to_ask") or []
                if cand:
                    try:
                        idx = int(cand[0].get("index"))
                        # 避免重复问已经问过/被跳过的条目（可按需放宽）
                        if idx not in self.already_asked:
                            target_idx = idx
                    except Exception:
                        target_idx = None

                # 若路由未给题或不适用，则按顺序策略选择
                if target_idx is None:
                    asked = sorted(self.already_asked)
                    skipped = self.skipped_items
                    target_idx = self.select_item_to_ask(asked=asked, skipped=skipped)

                # 若没有可问条目，则回到 smalltalk
                if target_idx is None:
                    # 后台日志，不给用户看到
                    logging.getLogger(__name__).info("所有条目已问完，回到小聊模式。")
                    STATS.set_stage_smalltalk_no_count()  # 自然收束，不+1
                    self.mode = "smalltalk"
                    self.idle_smalltalk_rounds = 0  # 重新进入闲聊 → 计数清零
                    self.awaiting_consent = False  # 清理等待同意状态（若之前用过）
                    self._first_item_suggested = None  # 清理上轮缓存（可选）
                    continue

                # print(f"[DEBUG] 本轮选题 -> 序号:{target_idx}, 条目:{ITEM_PROMPTS.get(target_idx, str(target_idx))}")

                # 执行一题并评分
                ok = self.ask_item_and_score(target_idx)

                # 如果条目流中触发了安抚切换，当轮立即给一条安抚回复
                if self.mode == "soothe":
                    try:
                        s = self.router.route_soothe_state(user_text=user, history=self.history)

                        # 结束优先
                        if s.get("end_session"):
                            self.summarize_and_exit()
                            break

                        # —— 回小聊优先：不要再输出安抚句，直接切回并只打一条 smalltalk —— #
                        if s.get("return_to_smalltalk"):
                            if s.get("is_interpersonal"):
                                last_user2 = self._last_user_text()
                                # 两票复判：仅本轮用户文本参与判断，避免被历史助手话术干扰
                                if self._llm_interpersonal_consensus(last_user2, history=[("user", last_user2)]):
                                    STATS.switch_to_item_flow()  # ← 同步阶段
                                    self.mode = "item_flow"
                                    t2 = self.select_item_to_ask(
                                        asked=sorted(self.already_asked),
                                        skipped=self.skipped_items
                                    )
                                    if t2 is not None:
                                        self.ask_item_and_score(t2)
                                        if self.mode == "item_flow":
                                            STATS.set_stage_smalltalk_no_count()
                                            self.mode = "smalltalk"
                                    else:
                                        # 无题可问：当轮回小聊（只打一条 smalltalk），避免下一轮直接让用户输入
                                        STATS.set_stage_smalltalk_no_count()
                                        self.mode = "smalltalk"
                                        self.idle_smalltalk_rounds = 0
                                        _ = self._emit_smalltalk_now() or {}
                                    continue  # 已处理本轮

                            # 严格回小聊：并清零闲聊计数
                            STATS.set_stage_smalltalk_no_count()  # 同步阶段但不+1（保持 stage 与 mode 一致）
                            self.mode = "smalltalk"
                            self.idle_smalltalk_rounds = 0
                            _ = self._emit_smalltalk_now() or {}
                            continue

                        # —— 留在 soothe：此时才输出安抚句（只打一条） —— #
                        brief = (s.get("soothe_reply") or "").strip()
                        # ✦ 节流：如果本轮已在条目流里“立即安抚”说过一句，就不再重复输出
                        if brief and not self._already_replied_this_turn:
                            self._say(brief)
                    except Exception as e:
                        print("[ERROR][item_flow->soothe immediate] ", e)
                        traceback.print_exc()
                        STATS.switch_to_soothe()
                        self.mode = "soothe"
                    continue

                # 自动连续提问（按顺序，遇到跑题/抵触等由内部逻辑切回 smalltalk）
                if ok and self.mode == "item_flow" and self.auto_follow:
                    while self.mode == "item_flow":
                        if not self.maybe_followup_next():
                            break

                # 一轮结束后，若仍在 item_flow 则回到 smalltalk；并当轮给一句 smalltalk 回复
                if self.mode == "item_flow":
                    STATS.set_stage_smalltalk_no_count()  # 仅同步阶段，不+1（自然的一问一停）
                    self.mode = "smalltalk"
                    self.idle_smalltalk_rounds = 0  # 重新进入闲聊 → 阈值计数重置

                # 只有当本轮还没输出过自然回复时，才补一条小聊承接，避免同轮“闲聊+安抚”连发
                if self.mode == "smalltalk" and not self._already_replied_this_turn:
                    route = self._emit_smalltalk_now() or {}
                    if self.mode == "soothe":
                        continue
                continue

            # ===== 仍在 smalltalk：等待下一次用户输入 =====
            if self.mode == "smalltalk":
                continue

            # ===== 兜底：未知模式时回退到 smalltalk，避免直接退出 =====
            print(f"[ERROR] 未知模式: {self.mode}，已回退到 smalltalk。")
            self.mode = "smalltalk"
            continue


# =========================
#  CLI
# =========================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--items_file",
        type=str,
        default=os.path.join(os.path.dirname(__file__), "IPSM-CS_items.json"),
        help="题库文件路径（必需）。应为完整的 IPSM-CS_items.json。"
    )
    parser.add_argument(
        "--auto_follow",
        action="store_true",
        help = "开启：未出现抵触时自动连续提问；关闭：一问一停（默认）。"
    )
    args = parser.parse_args()
    ChatSession(items_file=args.items_file, auto_follow=args.auto_follow).run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
