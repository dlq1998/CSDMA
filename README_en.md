
# CSDMA: A State-Driven Multi-Agent Framework for Conversational Psychometrics

**English** | [中文](README_zh.md)

CSDMA (Conversational State-Driven Multi-Agent Framework) is a state-driven multi-agent dialogue framework designed for **conversational psychometrics**.

This study uses the **Chinese Version of the Short-Form of the Interpersonal Sensitivity Measure (IPSM-CS)** as the measurement task. It integrates a standardized psychological scale into natural multi-turn conversations and dynamically adjusts subsequent measurement behaviors according to users' current response states.

This repository provides supplementary materials for the manuscript during anonymous peer review.

---

## 📖 Project Overview

Existing approaches to conversational psychometrics primarily focus on integrating scale items into natural conversations and assigning scores based on users' responses. However, insufficient attention has been paid to how subsequent measurement behaviors should be adjusted according to users' actual response states.

Insufficient information does not always mean that the system should continue asking questions. When users exhibit resistance, refusal, pronounced negative affect, or an intention to end the conversation, persistent item probing may increase interaction pressure.

Therefore, CSDMA addresses not only:

> **"What should be asked next?"**

but also:

> **"Should the system continue asking questions now?"**

> **"When should it pause?"**

> **"When should it ask again?"**

CSDMA coordinates three agents—the **State Agent, Questioning Agent, and Scoring Agent**—to identify users' current response states and interpersonal cues, dynamically adjust subsequent dialogue behaviors, and obtain scale-related information for conversational scoring.

---

## 🧩 CSDMA Framework

CSDMA consists of three collaborative agents.

### 1. State Agent

The State Agent identifies users' current **response states** and **interpersonal cues** in their responses, and determines subsequent dialogue behaviors accordingly.

The response state primarily reflects:

- Response sufficiency;
- Resistance or refusal;
- Negative affect;
- Intention to end the conversation.

Based on the current response state and interpersonal cues, the system dynamically switches among four dialogue states:

- **Chat**: Establishes initial rapport with users or maintains natural conversation when item probing is temporarily paused;
- **Probe**: Explores the current scale item to obtain information sufficient for scoring and advance the measurement process;
- **Soothe**: Provides supportive and soothing responses when users exhibit pronounced negative affect;
- **End**: Generates a closing response and terminates the current conversation.

The State Agent reassesses the current state after receiving each user response. Therefore, the system does not advance through the measurement process according to a fixed sequence.

### 2. Questioning Agent

In the **Probe** state, the Questioning Agent generates initial item questions or follow-up questions based on the current target item.

To integrate item probing naturally into the ongoing conversation, the Questioning Agent adopts a three-stage generation strategy:

> **Empathy → Transition → Question**

Specifically:

1. **Empathy**: Provides a concise response based on the key content expressed by the user in the previous turn;
2. **Transition**: Naturally connects the current topic to the interpersonal experiences, attitudes, or response tendencies addressed by the target item;
3. **Question**: Generates a conversational, open-ended question centered on the core content of the item.

The generated questions primarily encourage users to describe their **general experiences over a recent period**, rather than focusing exclusively on a single specific incident.

The Questioning Agent is invoked in the following situations:

- When the system enters the Probe state, it generates the initial question for the current target item;
- When the current item has been scored and other items remain incomplete, it generates the question for the next item;
- When the user's response does not provide sufficient information for scoring, it generates one follow-up question targeting the current item.

If the response remains insufficient, the system may ask one follow-up question about the current item. If the subsequent response still does not provide sufficient information for scoring, the system stops repeatedly probing that item and marks it as **pending completion**. The system returns to this item for further probing after completing the remaining items.

### 3. Scoring Agent

When a user's response provides sufficient information to support scoring of the current item, the system invokes the Scoring Agent.

The Scoring Agent determines the score and corresponding rationale for the current item based on a predefined **scoring reference set**, considering:

- Dialogue history;
- The user's current response;
- The current item to be scored;
- The scoring references corresponding to that item.

The scoring reference set covers all 15 IPSM-CS items and their **1–5 scoring levels**, aiming to improve the standardization and consistency of the scoring process.

The reference set contains 750 scoring examples, with 10 examples for each item at each score level. During scoring, the Scoring Agent consults the 50 examples corresponding to the current item.

---

## 🔄 Conversational Measurement Workflow

The overall measurement workflow of CSDMA can be summarized as follows:

```text
User Response
     ↓
State Agent
     ↓
Identify Response State and Interpersonal Cues
     ↓
Determine Dialogue State Dynamically
     │
     ├── Chat
     ├── Probe
     ├── Soothe
     └── End
            │
            ↓
    Questioning Agent / Scoring Agent
            ↓
       User Response
            ↓
      Return to State Agent
```

During item probing, the Questioning Agent generates initial or follow-up questions, while the Scoring Agent assigns item scores based on the scoring reference set. The system continuously adjusts its interaction state according to users' latest responses until all items have been scored or users choose to end the conversation.

---

## 💬 Complete Dialogue Example

The following example presents a complete interaction in its original Chinese form, illustrating how CSDMA integrates IPSM-CS-related item probing into natural multi-turn conversations.

<details>
<summary><b> Click to expand the complete dialogue</b></summary>

<br>

```json
{
  "history": [
    {
      "role": "assistant",
      "text": "你好～想和你聊聊生活，也想增进对你的了解，你愿意和我分享吗？你最近有什么让你开心或在意的事吗？"
    },
    {
      "role": "user",
      "text": "我的好朋友昨天和我绝交了"
    },
    {
      "role": "assistant",
      "text": "听到你提到好朋友和你绝交了，我能感受到这对你来说一定是件很不容易的事情，可能让你感到困惑或难过。在这样的情况下，我们难免会对自己和他人的关系产生一些思考。最近一段时间，你会不会常常担心别人对你的看法呢？"
    },
    {
      "role": "user",
      "text": "有点担心吧，毕竟是要经常相处的"
    },
    {
      "role": "assistant",
      "text": "我能理解你在朋友绝交后感到有些担心，特别是当我们需要与他人频繁互动时，这种感觉可能会更明显。人际关系中的变化确实会让我们更加关注自己在他人眼中的形象。最近一段时间，你会不会因为自己说的话或做的事而担心被他人批评呢？"
    },
    {
      "role": "user",
      "text": "还是有点担心，但是我会快速调整自己，然后吸取对自己有利的内容"
    },
    {
      "role": "assistant",
      "text": "听到你说会快速调整自己并吸取有利的内容，说明你在面对批评时有自己的应对方式，这很值得肯定。人际关系中的批评有时难免会让我们感到不安。最近一段时间，当有人对你做的事情提出批评时，你会不会觉得心情变得很糟糕呢？"
    },
    {
      "role": "user",
      "text": "不会，他们可以批评我，但是我不糟糕，我是最优秀的！"
    },
    {
      "role": "assistant",
      "text": "听到你说自己是最优秀的，我感受到你对自己的肯定和自信，这非常重要，尤其是在面对批评时。人际关系中，我们常常会思考自己在他人眼中的样子。最近一段时间，你有没有担心过如果别人了解你真实的样子，他们可能会怎么看待你呢？"
    },
    {
      "role": "user",
      "text": "可能会不容易接受我把，毕竟我也有很多不好的一面"
    },
    {
      "role": "assistant",
      "text": "我理解你内心的担忧，尤其是当你意识到自己并非完美的时候。不过，每个人都有各自的优缺点，这是非常正常的。人际关系中，我们的内心难免会产生一些不安，尤其是害怕让别人看到自己真实的一面。在最近的日子里，有没有出现过这样的时刻，让你觉得如果别人深入了解你的内心，他们可能就不会喜欢你呢？"
    },
    {
      "role": "user",
      "text": "也有可能吧"
    },
    {
      "role": "assistant",
      "text": "听到你说可能会不容易被接受，我感受到你对自己某些方面的顾虑，这种担忧在我们与他人交往时是很自然的。每个人都有不愿意被别人看到的部分，这可能让我们在关系中感到不安。最近一段时间，你有没有觉得不太愿意让别人了解你真实的样子呢？"
    },
    {
      "role": "user",
      "text": "我确实不太愿意，每一个人都有自己不善良的一面"
    },
    {
      "role": "assistant",
      "text": "我理解你对自己某些不完美之处的顾虑，这种感觉在我们与他人交往时是很常见的。尤其是在关系中，我们可能会担心别人对我们的看法。最近一段时间，当你和别人告别时，会不会感到有些不安呢？"
    },
    {
      "role": "user",
      "text": "不会啊，拜拜就拜拜，嘿嘿"
    },
    {
      "role": "assistant",
      "text": "听到你说“拜拜就拜拜”，我感受到你在面对分离时的轻松和洒脱，这种态度在处理人际关系变化时是很有力量的。即便如此，我们有时仍可能会对某些关系产生特别的依恋和担忧。最近一段时间，你会不会有些担心失去那些与你关系密切的人呢？"
    },
    {
      "role": "user",
      "text": "有点担心，和我亲密关系的人也不多"
    },
    {
      "role": "assistant",
      "text": "听到你说有点担心失去与自己关系密切的人，我感受到你对这些关系的珍视和在意，这是很自然的情感反应。人际关系中，这种担忧可能会在我们与他人分开时变得更加明显。最近一段时间，当你和别人分开时，会不会感到有些焦虑呢？"
    },
    {
      "role": "user",
      "text": "不会啊，我们还会再见面的"
    },
    {
      "role": "assistant",
      "text": "听到你说“我们还会再见面的”，我感受到你对关系的持续性和稳定性的信心，这种乐观的态度在面对分离时是非常积极的。即便如此，在人际交往中，我们有时可能会因为他人的评价而产生不同的情绪反应。最近一段时间，当别人赞美你时，你会感到高兴吗？"
    },
    {
      "role": "user",
      "text": "当然会啊，我挺开心滴！"
    },
    {
      "role": "assistant",
      "text": "听到你说收到赞美时会感到开心，我感受到你对他人积极评价的欣赏和重视，这种愉悦的情感在我们的人际互动中是很重要的。我们在关系中常常会希望通过自己的方式来维持和加强与他人的联系。最近一段时间，你有没有尝试用自己的方式去取悦那些与你关系密切的人呢？"
    },
    {
      "role": "user",
      "text": "有这样的情况，比如买一些小礼物的什么的"
    },
    {
      "role": "assistant",
      "text": "听到你说会通过买小礼物来取悦亲密的人，我感受到你在关系中付出的努力和用心，这种行为能让彼此感到温暖和被关心。每个人在与他人交往时都有自己独特的方式来表达关爱和维持联系。最近一段时间，你有没有觉得自己能够通过某些方式让别人感到开心呢？"
    },
    {
      "role": "user",
      "text": "有过这样的情况，我会特意讲一些梗来逗他们开心"
    },
    {
      "role": "assistant",
      "text": "听到你说通过讲一些梗来逗大家开心，我感受到你在关系中带来的欢乐和活力，这种互动方式让人际关系更加轻松愉快。在与他人相处时，我们有时也会遇到一些挑战，比如情绪上的波动。最近一段时间，你会不会觉得很难对别人产生生气的情绪呢？"
    },
    {
      "role": "user",
      "text": "有时候会的，还是需要给对方一些面子"
    },
    {
      "role": "assistant",
      "text": "听到你说有时候会给对方面子，我感受到你在关系中对他人感受的体贴和顾虑，这种考虑他人感受的态度在很多时候是很珍贵的。人际交往中，我们可能会因为不想伤害他人而压抑自己的情绪。最近一段时间，你会不会因为害怕可能会伤害到别人而避免表达自己的生气呢？"
    },
    {
      "role": "user",
      "text": "会有的，但是我不会过于委屈自己"
    },
    {
      "role": "assistant",
      "text": "听到你说虽然有时会避免表达生气，但不会过于委屈自己，我感受到你在平衡自我需求和他人感受之间的努力，这种自我保护和对他人的体贴都是很重要的。在人际关系中，我们有时可能会为了避免冲突而做出一些妥协。最近一段时间，你有没有因为不想让别人不高兴而去做一些自己其实不太愿意做的事情呢？"
    },
    {
      "role": "user",
      "text": "当然有过这样的情况，很难避免的"
    },
    {
      "role": "assistant",
      "text": "听到你说有时会做一些自己不太愿意做的事情以避免让别人不高兴，我感受到你在关系中对他人感受的关注和付出，这种考虑他人情绪的态度在很多时候是很值得尊重的。在人际交往中，我们有时可能会因为担心被拒绝或不被接受而调整自己的行为。最近一段时间，你会不会担心如果别人了解了你的真实想法或个性，他们可能就不再喜欢你了呢？"
    },
    {
      "role": "user",
      "text": "有可能啊，我真实的自己又不是完美的"
    },
    {
      "role": "assistant",
      "text": "是的，我们每个人都有自己的不完美之处，这也是我们独特的一部分。"
    },
    {
      "role": "user",
      "text": "我还有事情忙，下次聊"
    },
    {
      "role": "assistant",
      "text": "好的，那我们先到这里。如有需要，随时再来找我。"
    }
  ]
}
```

</details>

---

## 🧪 Experimental Design

This study evaluates CSDMA at two levels: **different response conditions** and **real-world human–AI interaction**.

### Study 1: Simulated User Experiment

To investigate the conversational measurement performance of CSDMA under different user response conditions, we constructed two types of user simulators:

- **Cooperative Simulator**
- **Challenging Simulator**

The Cooperative Simulator responds directly to the system's questions, with its responses remaining consistent with the predefined interpersonal sensitivity level. It does not exhibit avoidance or refusal behaviors.

The Challenging Simulator initially provides information that deviates from its predefined interpersonal sensitivity level and dynamically adjusts its responses according to the system's subsequent dialogue behaviors. After multiple rounds of continuous item probing, it may also exhibit resistance.

Both simulators were configured with three interpersonal sensitivity levels: low, medium, and high.

We selected 30 initial dialogue scenarios across six topics: family, marriage, personal growth, career, romantic relationships, and campus life. These scenarios were generated using GPT-4o.

- The Cooperative Simulator used 5 scenarios, each configured at three sensitivity levels (low, medium, and high), resulting in 15 simulated conversations;
- The Challenging Simulator used all 30 scenarios, each configured at three sensitivity levels, resulting in 90 simulated conversations.

The simulated user responses were categorized into three types:

- `<core>`: Consistent with the predefined interpersonal sensitivity level;
- `<shell>`: Deviating from the predefined interpersonal sensitivity level;
- `<defense>`: Exhibiting avoidance, refusal, or resistance.

These labels were used exclusively for simulated experiment analysis and were not provided as system inputs.

**Baseline Methods:**

- Direct-Prompt GPT-4o;
- Single-Agent GPT-4o;
- CSDMA.

Two ablation experiments were also conducted:

- CSDMA w/o State: Removes the State Agent;
- CSDMA w/o Questioning: Removes the Questioning Agent.

### Study 2: Real-User Experiment

We further recruited real participants to engage in multi-turn human–AI interactions with CSDMA.

A total of 31 university students participated in the experiment (N = 31). After completing multi-turn conversations with CSDMA, participants completed the IPSM-CS self-report questionnaire and an interaction experience questionnaire.

The experiment primarily examined the relationships among:

- **CSDMA conversational scores**
- **Human evaluation results**
- **Participant self-reports**

Two psychology graduate students independently evaluated the conversations and subsequently established the final human evaluation results.

The study employed QWK, Spearman's ρ, ICC(2,1), MAE, Bland–Altman analysis, and Cronbach's α to examine the agreement and scoring performance of conversational assessments relative to human evaluations.

The study also examined state transitions during real interactions and collected participants' subjective evaluations of:

- Communication experience;
- Interaction comfort;
- Appropriateness of responses;
- Willingness to use the system again;
- Overall satisfaction.

---

## 📁 Repository Structure

```text
CSDMA/
├── Figure/
│   └── ...
├── LICENSE
├── README.md
└── README_zh.md
```

Code and other experimental resources related to the paper will be further organized in subsequent releases.

---

## 🔬 Reproducibility

This repository is currently maintained for anonymous peer review.

To comply with the requirements of anonymous peer review, information related to the authors' identities has been removed from the repository.

Supplementary materials related to the research methodology, experiments, and examples are provided during the review process. The complete source code and other experimental resources will be further organized and released after the review process.

---

## ⚠️ Intended Use

CSDMA is designed for research on **conversational psychometrics**, particularly dialogue state identification, measurement workflow regulation, item probing, and conversational scoring.

This study focuses on obtaining information related to standardized psychological scales through natural multi-turn conversations and using that information to generate item-level scores.

The system and its scoring results are intended for research purposes only. **They are not intended for clinical diagnosis and cannot replace professional psychological assessment or medical decision-making.**

---

## 📄 License

This project is licensed under the **Apache License 2.0**.

---

<p align="center">
  <i>Supplementary materials for anonymous peer review.</i>
</p>
