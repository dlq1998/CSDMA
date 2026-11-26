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
from agent_severity import score_severity_1_5, load_ipsm_levels
from datetime import datetime

ITEM_PROMPTS: Dict[int, str] = {}
ALL_INDICES: List[int] = []

@dataclass
class DialogueStats:
    user_turns: int = 0
    ai_turns: int = 0
    user_chars: int = 0
    ai_chars: int = 0

    # 阶段管理
    current_stage: str = "smalltalk"  # smalltalk | item_flow | soothe
    switch_to_smalltalk_count_total: int = 0
    switch_to_smalltalk_count_human: int = 0
    switch_itemflow_to_smalltalk: int = 0  
    switch_itemflow_to_soothe: int = 0  

    # 题目相关
    all_indices: list = field(default_factory=list)  
    index_to_prompt: dict = field(default_factory=dict) 
    answered_indices: set = field(default_factory=set) 

    # 原始 print/input 引用
    _orig_print: callable = None
    _orig_input: callable = None

    def bind_catalog(self, catalog: list):
        """catalog: [{'index': int, 'prompt': str}, ...]"""
        self.all_indices = [it["index"] for it in catalog]
        self.index_to_prompt = {it["index"]: it["prompt"] for it in catalog}

    def mark_answered(self, idx: int):
        self.answered_indices.add(idx)

    def switch_to_smalltalk(self, reason: str = "system"):
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
        if self.current_stage == "item_flow":
            self.switch_itemflow_to_soothe += 1
        self.current_stage = "soothe"

    def set_stage_smalltalk_no_count(self):
        self.current_stage = "smalltalk"

    def patch_io(self):
        """全局替换 print/input，用于自动记 AI/用户说话与长度"""
        if self._orig_print is None:
            self._orig_print = builtins.print
        if self._orig_input is None:
            self._orig_input = builtins.input

        def _print_wrapper(*args, **kwargs):
            text = " ".join(str(a) for a in args)
            if not text.lstrip().startswith("["):
                self.ai_turns += 1
                self.ai_chars += len(text)
            return self._orig_print(*args, **kwargs)

        def _input_wrapper(prompt=""):
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
        total_turns = self.user_turns + self.ai_turns

        return {
            "total_turns": total_turns, 
            "avg_user_chars_per_turn": avg_user,  
            "avg_assistant_chars_per_turn": avg_ai, 
            "itemflow_to_smalltalk_count": self.switch_itemflow_to_smalltalk,  
            "itemflow_to_soothe_count": self.switch_itemflow_to_soothe,  
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

STATS = DialogueStats()
STATS.patch_io()

def load_items_json(path: str) -> int:
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
        if not os.path.exists(items_file):
            raise FileNotFoundError(f"未找到题干文件：{items_file}")

        n = load_items_json(items_file)
        print(f"[已载入题干] {items_file} ；共 {n} 条")

        STATS.bind_catalog([
            {"index": idx, "prompt": ITEM_PROMPTS.get(idx, f"第{idx}条")}
            for idx in ALL_INDICES
        ])

        try:
            load_ipsm_levels()
        except Exception as e:
            print("[警告] 未找到 ipsm-cs_level.json，严重度评分时可能失败")

        self.history: List[Tuple[str, str]] = []  # (role, text)
        self.records: Dict[int, int] = {}          # index -> score
        self.score_reasons: Dict[int, str] = {}    # index -> reason（新增）
        self.mode: str = "smalltalk"  # smalltalk | item_flow
        self.auto_follow = bool(auto_follow)

        self.router = IPSM_Router()
        self.already_asked = set()  
        self.skipped_items: List[int] = []  
        self.last_sev: int = 0  # 记录上一题的评分

        self.idle_smalltalk_rounds = 0    
        self.idle_threshold = 2           
        self.awaiting_consent = False    
        self._first_item_suggested = None

        self._already_replied_this_turn = False

    def _coerce_score(self, val) -> int:
        try:
            if isinstance(val, dict):
                return int(val.get("score", 0))
            return int(val)
        except Exception:
            return 0

    # —— 小工具 —— #
    def _emit_smalltalk_now(self) -> dict:
        last_user = self._last_user_text()
        all_done = len(self.already_asked) >= len(ALL_INDICES)
        effective_idle_threshold = (10 ** 9) if all_done else int(self.idle_threshold)

        try:
            route = self.router.route_smalltalk_state(
                user_text=last_user,
                history=self.history[-8:], 
                asked_indices=sorted(self.already_asked),
                idle_smalltalk_rounds=int(self.idle_smalltalk_rounds),
                idle_threshold=effective_idle_threshold,  
            )
        except Exception as e:
            print("[FATAL] pipeline crashed:", e)
            traceback.print_exc()
            # 兜底：极简一句（仅在 LLM 崩溃时使用）
            self._say("我在，先缓一缓，慢慢来。")
            self.mode = "smalltalk"
            return {}

        if route.get("end_session"):
            self._say("好的，那我们先到这里。如有需要，随时再来找我。")
            self.mode = "end"
            return route

        neg = self._llm_neg_affect_consensus(last_user)
        interpersonal = self._llm_interpersonal_consensus(last_user)
        next_item = route.get("item_to_ask") or []

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

        bot = (route.get("smalltalk_reply") or "").strip()
        if bot:
            self._say(bot)

        if (not interpersonal) and (not neg):
            self.idle_smalltalk_rounds += 1
        else:
            self.idle_smalltalk_rounds = 0

        self.mode = "smalltalk"
        return route

    def _llm_interpersonal_consensus(self, user_text: str, history: list | None = None) -> bool:
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

    def _push_history(self, role: str, text: str, index: int | None = None):
        rec = {"role": role, "text": text}
        if index is not None:
            rec["index"] = int(index)
        self.history.append(rec)

    def _iter_history_pairs(self):
        for h in self.history:
            if isinstance(h, dict):
                yield (h.get("role", ""), h.get("text", ""))
            else:
                yield (h[0], h[1])

    def _history_context(self, tail: int = 12) -> str:
        lines = []
        pairs = list(self._iter_history_pairs())[-tail:]
        for r, t in pairs:
            prefix = "用户" if r == "user" else "助手"
            lines.append(f"{prefix}: {t}")
        return "\n".join(lines) or "(无)"

    def _last_user_text(self) -> str:
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
        text = (text or "").strip()
        if not text:
            return
        print(text)
        self._push_history("assistant", text)  
        self._already_replied_this_turn = True

    def select_item_to_ask(self, asked: List[int], skipped: List[int]) -> Optional[int]:
        for item in ALL_INDICES:
            if item not in asked and item not in skipped:
                return item

        for item in skipped:
            if item not in asked:
                return item

        return None

    def ask_item_and_score(self, idx: int) -> bool:
        if self.mode != "item_flow":
            return False

        asked = sorted(self.already_asked)  
        skipped = self.skipped_items  

        base = _lookup_prompt(idx)
        context = self._history_context(tail=12)

        try:
            question = rewrite_question(base, context=context, mode="first")
        except Exception as e:
            print(f"[问句改写失败] {e}")
            question = f"想请你聊聊：{base}（如果方便的话）"

        print(question)
        self._push_history("assistant", question, index=idx) 
        self.last_assistant_text = question 

        reply1 = input("你的回复：").strip()
        self._push_history("user", reply1)

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

        if acc1:
            try:
                sev_val = score_severity_1_4(
                    reply1,
                    item_index=idx,
                    question_text=self.last_assistant_text,
                    context_text=self._history_context(tail=6)
                )
                score = self._coerce_score(sev_val)
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
                self.score_reasons[idx] = reason
                STATS.mark_answered(idx)
                if idx not in self.already_asked:
                    self.already_asked.add(idx)
            else:
                if idx not in self.skipped_items:
                    self.skipped_items.append(idx)
                print(f"[DEFER] 序号 {idx}｜评分无效，稍后回访")

            nxt = self.select_item_to_ask(
                asked=sorted(self.already_asked),
                skipped=self.skipped_items
            )
        
            if nxt is None:
                print("[ITEMFLOW] 所有题目已完成，系统切换至 smalltalk。")
                STATS.set_stage_smalltalk_no_count()  
                self.mode = "smalltalk"
                self.idle_smalltalk_rounds = 0
                route = self._emit_smalltalk_now() or {}
                if route.get("item_to_ask") or route.get("is_interpersonal"):
                    STATS.set_stage_smalltalk_no_count()
                    self.mode = "smalltalk"
                return True

            return self.ask_item_and_score(nxt)

        if res1:
            r0 = self.router.route_smalltalk_state(
                user_text=reply1,
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

        effective_reply = reply1
        if off1:
            try:
                re_q = rewrite_question(base, context=self._history_context(12),
                                        mode="reask", last_question=question)
            except Exception as e:
                print(f"[二次追问改写失败] {e}")
                re_q = f"那我换个问法：关于“{base}”，这类情况大概在什么场景更常出现呢？"

            print(re_q)
            self._push_history("assistant", re_q, index=idx)  

            reply2 = input("你的回复：").strip()
            self._push_history("user", reply2)

            try:
                chk2 = self.router.route_itemflow_state(
                    user_text=reply2,
                    history=[("assistant", re_q), ("user", reply2)],
                    current_index=idx
                )
            except Exception as e:
                print(f"[router 解析失败] {e}，先回到随意聊聊。")
                STATS.switch_to_smalltalk()
                self.mode = "smalltalk"
                return True

            res2 = bool(chk2.get("resistance", False))
            off2 = bool(chk2.get("offtopic", False))
            acc2 = bool(chk2.get("accept", False))
    
            if chk2.get("end_session"):
                self.summarize_and_exit()
                raise SystemExit

            if acc2:
                try:
                    sev_val = score_severity_1_4(
                        reply2,
                        item_index=idx,
                        question_text=re_q,
                        context_text=self._history_context(tail=6)
                    )
                    sev = self._coerce_score(sev_val)
                    reason2 = ""
                    if isinstance(sev_val, dict):
                        reason2 = str(sev_val.get("reason", "")).strip()
                except Exception as e:
                    print(f"[评分失败] {e}")
                    sev = 0
                    reason2 = ""  

                if 1 <= sev <= 4:
                    self.last_sev = sev
                    self.records[idx] = sev
                    self.score_reasons[idx] = reason2  
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

                if nxt is None:
                    print("[ITEMFLOW] 所有题目已完成，系统切换至 smalltalk。")
                    STATS.set_stage_smalltalk_no_count() 
                    self.mode = "smalltalk"
                    self.idle_smalltalk_rounds = 0
                    route = self._emit_smalltalk_now() or {}
                    if route.get("item_to_ask") or route.get("is_interpersonal"):
                        STATS.set_stage_smalltalk_no_count()
                        self.mode = "smalltalk"
                    return True

                return self.ask_item_and_score(nxt)

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

            if bool(chk2.get("need_soothe", False)):
                STATS.switch_to_soothe()
                self.mode = "soothe"
                try:
                    s = self.router.route_soothe_state(user_text=reply2, history=self.history[-8:])
                    brief = (s.get("soothe_reply") or "").strip()
                    if brief:
                        self._say(brief)
                except Exception:
                    self._say("我在，先缓一缓，慢慢来。")
                return True

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

        neg1 = bool(chk1.get("need_soothe", False)) 

        if neg1:
            STATS.switch_to_soothe()
            self.mode = "soothe"
            try:
                s = self.router.route_soothe_state(user_text=reply1, history=self.history[-8:])
                brief = (s.get("soothe_reply") or "").strip()
                if brief:
                    self._say(brief)
            except Exception:
                self._say("我在，先缓一缓，慢慢来。")
            return True

        if idx not in self.skipped_items:
            self.skipped_items.append(idx)

        nxt = self.select_item_to_ask(
            asked=sorted(self.already_asked),
            skipped=self.skipped_items
        )
        if nxt is not None:
            return self.ask_item_and_score(nxt)

        STATS.switch_to_smalltalk("human")
        self.mode = "smalltalk"
        self.idle_smalltalk_rounds = 0
        self._emit_smalltalk_now()
        return True

    def maybe_followup_next(self) -> bool:
        asked = sorted(self.already_asked)  # 已问条目
        skipped = self.skipped_items  # 跳过的条目

        nxt = self.select_item_to_ask(asked=asked, skipped=skipped)

        if nxt is None:
            if len(ALL_INDICES) == len(self.already_asked): 
                if skipped:
                    nxt = skipped[0]  
                else:
                    STATS.set_stage_smalltalk_no_count()
                    self.mode = "smalltalk"
                    self.idle_smalltalk_rounds = 0

                    route = self._emit_smalltalk_now() or {}
                    if route.get("is_interpersonal") or route.get("item_to_ask"):
                        STATS.set_stage_smalltalk_no_count()
                        self.mode = "smalltalk"
                        self.idle_smalltalk_rounds = 0
                    return False
            else:
                nxt = self.select_item_to_ask(asked=asked, skipped=skipped)

        if nxt is None:
            return False
        return self.ask_item_and_score(nxt)

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
                    "reason": self.score_reasons.get(idx, "")  
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

            payload["dialogue_stats"] = STATS.export_dialogue_stats()

            payload.setdefault("scores", {})
            payload["scores"]["unanswered_items"] = STATS.export_unanswered_items()

            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            print(f"[保存] 会话已保存：{path}")
        except Exception as e:
            print(f"[WARN] 保存会话 JSON 失败：{e}")

    def run(self) -> None:
        self._say("你好～想和你聊聊生活，也想增进对你的了解，你愿意和我分享吗？你最近有什么让你开心或在意的事吗？")

        if not getattr(self, "mode", None):
            self.mode = "smalltalk"

        while True:
            if self.mode == "item_flow":
                prompt_label = "你的回复："
            elif self.mode == "soothe":
                prompt_label = "你（此刻的感受）："
            else:
                prompt_label = "你："

            user = input(prompt_label).strip()
            if not user:
                continue

            self._push_history("user", user)
            self._already_replied_this_turn = False

            if self.mode == "soothe":
                try:
                    last_user2 = self._last_user_text()
                    s = self.router.route_soothe_state(user_text=last_user2, history=self.history[-8:])
                except Exception as e:
                    print("[ERROR][soothe] crashed:", e)
                    traceback.print_exc()
                    s = {"continue_soothe": True, "soothe_reply": "我在，先缓一缓，慢慢来。",
                         "end_session": False, "is_interpersonal": False, "return_to_smalltalk": False}

                if s.get("end_session"):
                    self.summarize_and_exit()
                    break

                last_user = self._last_user_text()

                if s.get("is_interpersonal") and self._llm_interpersonal_consensus(last_user, history=[("user", last_user)]):
                    STATS.switch_to_item_flow() 
                    self.mode = "item_flow"
                    target_idx = self.select_item_to_ask(
                        asked=sorted(self.already_asked),
                        skipped=self.skipped_items
                    )
                    if target_idx is None:
                        STATS.set_stage_smalltalk_no_count()  
                        self.mode = "smalltalk"
                        self.idle_smalltalk_rounds = 0
                        _ = self._emit_smalltalk_now() or {}
                    else:
                        self.ask_item_and_score(target_idx)
                        if self.mode == "item_flow":
                            STATS.set_stage_smalltalk_no_count() 
                            self.mode = "smalltalk"
                    continue

                if s.get("return_to_smalltalk"):
                    STATS.set_stage_smalltalk_no_count() 
                    self.mode = "smalltalk"
                    self.idle_smalltalk_rounds = 0  
                    _ = self._emit_smalltalk_now() or {}
                    continue

                if not self._already_replied_this_turn:
                    brief = (s.get("soothe_reply") or "").strip()
                    if brief:
                        self._say(brief)
                continue

            route = self._emit_smalltalk_now() or {}
            if self.mode == "soothe":
                continue

            if route.get("end_session"):
                self.summarize_and_exit() 
                break  

            if self.mode == "item_flow":
                target_idx = None
                cand = route.get("item_to_ask") or []
                if cand:
                    try:
                        idx = int(cand[0].get("index"))
                        if idx not in self.already_asked:
                            target_idx = idx
                    except Exception:
                        target_idx = None

                if target_idx is None:
                    asked = sorted(self.already_asked)
                    skipped = self.skipped_items
                    target_idx = self.select_item_to_ask(asked=asked, skipped=skipped)

                if target_idx is None:
                    # 后台日志，不给用户看到
                    logging.getLogger(__name__).info("所有条目已问完，回到小聊模式。")
                    STATS.set_stage_smalltalk_no_count() 
                    self.mode = "smalltalk"
                    self.idle_smalltalk_rounds = 0 
                    self.awaiting_consent = False  
                    self._first_item_suggested = None  
                    continue

                ok = self.ask_item_and_score(target_idx)

                if self.mode == "soothe":
                    try:
                        s = self.router.route_soothe_state(user_text=user, history=self.history)

                        if s.get("end_session"):
                            self.summarize_and_exit()
                            break

                        if s.get("return_to_smalltalk"):
                            if s.get("is_interpersonal"):
                                last_user2 = self._last_user_text()
                                if self._llm_interpersonal_consensus(last_user2, history=[("user", last_user2)]):
                                    STATS.switch_to_item_flow() 
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
                                        STATS.set_stage_smalltalk_no_count()
                                        self.mode = "smalltalk"
                                        self.idle_smalltalk_rounds = 0
                                        _ = self._emit_smalltalk_now() or {}
                                    continue  

                            STATS.set_stage_smalltalk_no_count()  
                            self.mode = "smalltalk"
                            self.idle_smalltalk_rounds = 0
                            _ = self._emit_smalltalk_now() or {}
                            continue

                        brief = (s.get("soothe_reply") or "").strip()
                        if brief and not self._already_replied_this_turn:
                            self._say(brief)
                    except Exception as e:
                        print("[ERROR][item_flow->soothe immediate] ", e)
                        traceback.print_exc()
                        STATS.switch_to_soothe()
                        self.mode = "soothe"
                    continue

                if ok and self.mode == "item_flow" and self.auto_follow:
                    while self.mode == "item_flow":
                        if not self.maybe_followup_next():
                            break

                if self.mode == "item_flow":
                    STATS.set_stage_smalltalk_no_count() 
                    self.mode = "smalltalk"
                    self.idle_smalltalk_rounds = 0 

                if self.mode == "smalltalk" and not self._already_replied_this_turn:
                    route = self._emit_smalltalk_now() or {}
                    if self.mode == "soothe":
                        continue
                continue

            if self.mode == "smalltalk":
                continue

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
