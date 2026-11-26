import json
from pathlib import Path
from typing import Any, Dict, List, Tuple, Set
from llm_common import _chat, _extract_json


class IPSM_Router:
    def __init__(self):
        """
        Router（IPSM 版）
        仅加载 index/prompt 结构的题库
        """
        self.records = {}
        # 仅两项：题库列表 + 索引集合
        self._CATALOG, self._INDEX_SET = self.load_items_json(
            str(Path(__file__).resolve().with_name("IPSM-CS_items.json"))
        )

    # --- local helpers (wrap llm_common & enforce json schema) ---
    def _chat(self, messages, temperature=0.2, max_tokens=400):
        """统一走 llm_common._chat，便于将来替换底模或打日志"""
        return _chat(messages=messages, temperature=temperature, max_tokens=max_tokens)

    def _safe_json(self, raw: str):
        """抽取大模型返回中的 JSON；失败时抛出可读错误"""
        data = _extract_json(raw)
        if not isinstance(data, dict):
            raise ValueError(f"[agent_router] 解析 JSON 失败：{raw[:200]}...")
        return data

    def _ensure_keys(self, data, required, ctx: str = "") -> None:
        """确保必填字段都存在"""
        missing = [k for k in required if k not in data]
        if missing:
            raise KeyError(f"[agent_router:{ctx}] 缺少字段：{missing}; 实际返回={list(data.keys())}")

    def _last_turns_as_text(self, history, tail: int = 8) -> str:
        """把最近 N 轮 history 扁平化为稳定文本；同时兼容列表[(role,content)]或[{"role":..,"content":..}]"""
        if not history:
            return ""
        seq = history[-tail:]
        lines = []
        for item in seq:
            if isinstance(item, dict):
                role = item.get("role", "")
                content = item.get("content", "")
            else:
                role, content = item
            lines.append(f"{role}: {str(content).strip()}")
        return "\n".join(lines)

    def load_items_json(self, path: str) -> Tuple[List[Dict[str, Any]], Set[int]]:
        """读取 IPSM-CS_items.json（数组），返回 catalog 与 index_set"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"找不到题库文件：{path}")

        if not isinstance(data, list):
            raise ValueError("IPSM-CS_items.json 应为数组格式：[{\"index\": int, \"prompt\": str}, ...]")

        catalog: List[Dict[str, Any]] = []
        for it in data:
            idx = int(it["index"])
            prm = (it.get("prompt") or "").strip()
            catalog.append({"index": idx, "prompt": prm})

        catalog.sort(key=lambda x: x["index"])
        index_set = {c["index"] for c in catalog}
        return catalog, index_set

    def route_itemflow_state(
            self,
            user_text: str,
            history: list,
            current_index: int | None = None,
    ) -> dict:
        # ---- 构造提示词 ----
        sys = (
            "你是一个面向会话式心理测量的状态分析智能体，具备心理测量、心理支持对话和人际互动分析方面的专业知识。"
            "你的任务是：根据最近上下文和本轮用户文本，判断是否已能对当前题目给出评分、是否抵触、是否跑题、是否结束，以及是否建议先进入安抚（仅限非抵触且出现明显情绪失稳的情况）。\n"
            "严格按如下定义输出一个 JSON：\n"
            "accept: 当本轮回复已体现“出现程度”或“明确倾向”，且足以将【当前条目】判入1–5分任一档时为 true；否则为 false。\n"
            "resistance: 明确不愿继续、拒答、强烈不适等。\n"
            "offtopic: 在 resistance=false 时，如果这轮没有回应本题核心（答非所问）。\n"
            "end_session: 是否表达结束对话（委婉表达也算）。\n"
            "need_soothe: 在 resistance=false 且 end_session=false 前提下，若出现明显情绪失稳、请求暂缓，或明显的生理性不适，可设为 true，表示切入安抚。\n"
            "【一致性约束】：\n"
            "resistance=true ⇒ accept=false, offtopic=false, need_soothe=false。\n"
            "offtopic=true ⇒ accept=false。\n"
            "end_session=true ⇒ 其它均为 false。\n"
            "【输出格式】：\n"
            "{"accept": bool, "resistance": bool, "offtopic": bool, "end_session": bool, "need_soothe": bool}"
        )
        # 尽量给出最少但必要的上下文（最后一轮问答）
        def _last_pair_text(h: list) -> str:
            last_u, last_a = "", ""
            for role, text in reversed(h):
                if not last_u and role == "user":
                    last_u = text
                elif not last_a and role == "assistant":
                    last_a = text
                if last_u and last_a:
                    break
            return f"上轮系统问/说：{last_a}\n来访者本轮回答：{user_text}"

        msgs = [
            {"role": "system", "content": sys},
            {"role": "user", "content": _last_pair_text(history)},
        ]

        # ---- 调 LLM 并解析 ----
        raw = self._chat(messages=msgs, temperature=0.2, max_tokens=400)
        data = self._safe_json(raw)

        # 必填键（已无 consent_granted）
        required = ("accept", "resistance", "offtopic", "end_session", "need_soothe")
        self._ensure_keys(data, required, ctx="route_itemflow_state")

        acc = bool(data.get("accept", False))
        res = bool(data.get("resistance", False))
        off = bool(data.get("offtopic", False))
        end_ = bool(data.get("end_session", False))
        soothe = bool(data.get("need_soothe", False))

        # ---- 一致性归一化（保险起见，再次规范）----
        if end_:
            acc, res, off, soothe = False, False, False, False
        if res:
            acc, off, soothe = False, False, False
        if off:
            acc = False
        if soothe and (res or end_):
            soothe = False

        # ---- 下一题建议（可选）----
        item_to_ask = []
        try:
            # 如果你实现了候选选择器，优先使用（例如基于 current_index 或历史）
            if hasattr(self, "_suggest_next_items") and callable(self._suggest_next_items):
                item_to_ask = self._suggest_next_items(current_index=current_index) or []
            # 退化策略：给出“current_index+1”占位（若提供了 current_index）
            elif isinstance(current_index, int):
                item_to_ask = [{"index": int(current_index) + 1}]
        except Exception:
            item_to_ask = []

        # 若抵触/结束/需要安抚，下一题建议清空
        if res or end_ or soothe:
            item_to_ask = []

        return {
            "accept": acc,
            "resistance": res,
            "offtopic": off,
            "end_session": end_,
            "need_soothe": soothe,
            "item_to_ask": item_to_ask,
        }

    def route_smalltalk_state(
            self,
            user_text: str,
            history: list,
            asked_indices: list | None = None,
            idle_smalltalk_rounds: int = 0,  # 已连续多少轮“非人际 & 非消极”
            idle_threshold: int = 3,  # 达到多少轮后，本轮建议征询
    ) -> dict:
        # ------- System 提示词：严格 JSON 输出 + 写作规范 -------
        sys = (
            "你是一个面向会话式心理测量的状态分析智能体，具备心理测量、心理支持对话和人际互动分析方面的专业知识。"
            "严格按如下定义输出一个 JSON：\n"
            "smalltalk_reply: 请自然地进行闲聊承接与回应。\n"
            "is_interpersonal: 若用户的表达涉及与他人相关的感受、沟通、交流、关系、互动、被理解、被评价、社交、孤独、冲突、依赖等内容，即视为人际线索。（不要求出现具体人物，只要表达中包含与他人有关的心理体验或互动含义，即可判断为 True。）\n"
            "neg_affect: 是否出现显著消极情绪（比如焦虑、崩溃、恐惧、愤怒等情绪）。\n"
            "end_session: 是否表达结束对话（委婉表达也算）。\n"
            "item_to_ask: 若 is_interpersonal=true，可给出下一题建议 [{\"index\": int}]（可为空）。\n"
            "【对话节奏规则】\n"
            "你会收到两个数值：[IDLE_ROUNDS] 与 [IDLE_THRESHOLD]。\n"
            "当 [IDLE_ROUNDS]<[IDLE_THRESHOLD] 时，正常小聊：smalltalk_reply 只需自然承接用户本轮内容。\n"
            "当 [IDLE_ROUNDS]>=[IDLE_THRESHOLD] 且 is_interpersonal=false 且 neg_affect=false 时：在 smalltalk_reply 里先承接，再自然地加一句轻柔邀请去聊最近的人际相处；邀请必须自然、非模板化、非命令式，避免重复同一语式。\n"
            "若 end_session=true，请用礼貌收尾。\n"
            "【输出格式】\n"
            "{"smalltalk_reply": str, "is_interpersonal": bool, "neg_affect": bool, "end_session": bool, "need_soothe": bool}"
        )
        # ------- 组合消息：使用“扁平历史文本”增强稳定性 -------
        htxt = self._last_turns_as_text(history, tail=8)
        msgs = [
            {"role": "system", "content": sys},
            {"role": "user", "content": f"{htxt}\n用户: {user_text}\n"
                                        f"[IDLE_ROUNDS]={idle_smalltalk_rounds},[IDLE_THRESHOLD]={idle_threshold}"}
        ]

        # ------- 调用 LLM 并解析严格 JSON -------
        raw = self._chat(messages=msgs, temperature=0.2, max_tokens=400)
        data = self._safe_json(raw)

        required = ("neg_affect", "is_interpersonal", "end_session", "smalltalk_reply")

        self._ensure_keys(data, required, ctx="route_smalltalk_state")

        neg_affect = bool(data.get("neg_affect", False))
        is_interpersonal = bool(data.get("is_interpersonal", False))
        end_session = bool(data.get("end_session", False))
        smalltalk_reply = (data.get("smalltalk_reply") or "").strip()

        # ------- 仅在人际且“确有下一题”时返回 item_to_ask -------
        asked_set = set(asked_indices or [])
        next_item = next((it for it in self._CATALOG if int(it["index"]) not in asked_set), None)
        if is_interpersonal and (next_item is not None):
            item_to_ask = [{"index": int(next_item["index"]), "prompt": str(next_item.get("prompt", ""))}]
        else:
            item_to_ask = []

        # ------- 结束优先：若用户已表示结束，本轮不应给出下一题或征询信号 -------
        if end_session:
            item_to_ask = []
            suggest_consent_ask = False

        return {
            "neg_affect": neg_affect,
            "is_interpersonal": is_interpersonal,
            "item_to_ask": item_to_ask,
            "smalltalk_reply": smalltalk_reply,
            "end_session": end_session
        }

    def route_soothe_state(self, user_text: str, history: list) -> dict:
        sys = (
            "你是一个具备心理支持、共情沟通与人际互动分析能力的对话智能体，当前处于【安抚 Soothe】阶段：只进行安抚与理解，不引导评估、测评或量表相关内容。"
            "严格按如下定义输出一个 JSON：\n"
            "continue_soothe：若情绪仍明显低落、紧绷等，或对方明确希望继续停留安抚 → true。\n"
            "return_to_smalltalk：若情绪已相对缓和，可回到随意聊天 → true。\n"
            "is_interpersonal：若用户的表达涉及与他人相关的感受、沟通、交流、关系、互动、被理解、被评价、社交、孤独、冲突、依赖等内容，即视为人际线索。（不要求出现具体人物，只要表达中包含与他人有关的心理体验或互动含义，即可判断为 true。）\n"
            "end_session：是否表达结束对话（委婉表达也算）。\n"
            "【soothe_reply 写作要求】：\n"
            "先以具体细节贴近来访者此刻的情绪体验或担忧，展现细腻的共情与理解。让对方感到被看见、被接纳（不评判、不急于安慰或解决）。\n"
            "共情后可以自然衔接一句轻柔提问，用来探索来访者所说感受背后的关系、互动或自我体验。\n"
            "提问必须自然、非模板化，避免使用相同句式或重复表达；不要命令式或追问式语气。\n"
            "整体语气保持柔和、细腻、具人味；让语言像真诚的陪伴而非程序化问答。字数控制在100以内。\n"
            "若 end_session=true，请用礼貌收尾。\n"
            "【输出格式】：\n"
            "{"continue_soothe": bool, "return_to_smalltalk": bool, "is_interpersonal": bool, "soothe_reply": str, "end_session": bool}"
        )
        # 使用“扁平历史文本”增强稳定性
        htxt = self._last_turns_as_text(history, tail=8)
        msgs = [
            {"role": "system", "content": sys},
            {"role": "user", "content": f"{htxt}\n用户: {user_text}"}
        ]

        # 调用模型并解析 JSON
        raw = self._chat(messages=msgs, temperature=0.5, max_tokens=400)
        data = self._safe_json(raw)

        required = ("continue_soothe", "return_to_smalltalk", "is_interpersonal",
                    "soothe_reply", "end_session")
        self._ensure_keys(data, required, ctx="route_soothe_state")

        # 读取字段
        cont = bool(data.get("continue_soothe", False))
        ret = bool(data.get("return_to_smalltalk", False))
        # 互斥校正：优先继续安抚
        if cont:
            ret = False

        return {
            "continue_soothe": cont,
            "return_to_smalltalk": ret,
            "is_interpersonal": bool(data.get("is_interpersonal", False)),
            "soothe_reply": (data.get("soothe_reply") or "").strip(),
            "end_session": bool(data.get("end_session", False))
        }









