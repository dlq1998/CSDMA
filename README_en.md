# CSDMA: A State-Driven Multi-Agent Framework for Conversational Psychometrics

CSDMA is a **state-driven multi-agent framework for conversational psychometric assessment**.
Instead of administering standardized questionnaire items in a rigid question-by-question manner, CSDMA integrates psychometric assessment into natural multi-turn dialogue and dynamically adapts its conversational behavior according to the user's responses.

This repository is provided as supplementary material for anonymous peer review.

---

## Overview

Conventional conversational assessment methods often focus primarily on **question generation** and **response scoring**, while paying limited attention to how the system should react when users provide incomplete, indirect, resistant, or emotionally sensitive responses.

CSDMA introduces a state-driven interaction mechanism that coordinates multiple specialized agents to:

* identify the user's current response state;
* dynamically determine whether to continue probing, provide supportive responses, or end the assessment;
* generate context-aware and natural follow-up questions;
* extract assessment-relevant information from multi-turn conversations;
* produce conversational psychometric scores based on collected evidence.

The framework is designed to preserve the structure of standardized psychometric assessment while allowing the interaction itself to remain flexible and conversational.

---

## Framework

CSDMA consists of three major components:

### State Agent

The State Agent analyzes the latest conversational context and determines the appropriate interaction strategy according to the user's response state.

Possible actions include:

* **Chat** — maintain natural conversational interaction;
* **Probe** — continue collecting assessment-relevant information;
* **Soothe** — respond supportively when resistance or emotional discomfort is detected;
* **End** — terminate the assessment when appropriate.

### Questioning Agent

The Questioning Agent generates context-aware follow-up questions based on both the assessment target and the current conversational state.

Rather than directly presenting questionnaire items, it integrates assessment-related probing into natural dialogue.

### Scoring Agent

The Scoring Agent maps the information collected during the conversation to the corresponding psychometric item scores.

---

## Example Conversation

The following example illustrates how the system integrates interpersonal-sensitivity-related assessment questions into a natural multi-turn conversation.

<details>
<summary><b>▶ View example dialogue</b></summary>

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
      "text": "听到你提到好朋友和你绝交了，我能感受到这对你来说一定是件很不容易的事情，可能让你感到困惑或难过。在这样的情况下，我们难免会对自己和他人的关系产生一些思考。最近一段时间，你会不会常常担心别人对你的看法呢？",
    },
    {
      "role": "user",
      "text": "有点担心吧，毕竟是要经常相处的"
    },
    {
      "role": "assistant",
      "text": "我能理解你在朋友绝交后感到有些担心，特别是当我们需要与他人频繁互动时，这种感觉可能会更明显。人际关系中的变化确实会让我们更加关注自己在他人眼中的形象。最近一段时间，你会不会因为自己说的话或做的事而担心被他人批评呢？",
    },
    {
      "role": "user",
      "text": "还是有点担心，但是我会快速调整自己，然后吸取对自己有利的内容"
    },
    {
      "role": "assistant",
      "text": "听到你说会快速调整自己并吸取有利的内容，说明你在面对批评时有自己的应对方式，这很值得肯定。人际关系中的批评有时难免会让我们感到不安。最近一段时间，当有人对你做的事情提出批评时，你会不会觉得心情变得很糟糕呢？",
    },
    {
      "role": "user",
      "text": "不会，他们可以批评我，但是我不糟糕，我是最优秀的！"
    },
    {
      "role": "assistant",
      "text": "听到你说自己是最优秀的，我感受到你对自己的肯定和自信，这非常重要，尤其是在面对批评时。人际关系中，我们常常会思考自己在他人眼中的样子。最近一段时间，你有没有担心过如果别人了解你真实的样子，他们可能会怎么看待你呢？",
    },
    {
      "role": "user",
      "text": "可能会不容易接受我把，毕竟我也有很多不好的一面"
    },
    {
      "role": "assistant",
      "text": "我理解你内心的担忧，尤其是当你意识到自己并非完美的时候。不过，每个人都有各自的优缺点，这是非常正常的。人际关系中，我们的内心难免会产生一些不安，尤其是害怕让别人看到自己真实的一面。在最近的日子里，有没有出现过这样的时刻，让你觉得如果别人深入了解你的内心，他们可能就不会喜欢你呢？",
    },
    {
      "role": "user",
      "text": "也有可能吧"
    },
    {
      "role": "assistant",
      "text": "听到你说可能会不容易被接受，我感受到你对自己某些方面的顾虑，这种担忧在我们与他人交往时是很自然的。每个人都有不愿意被别人看到的部分，这可能让我们在关系中感到不安。最近一段时间，你有没有觉得不太愿意让别人了解你真实的样子呢？",
    },
    {
      "role": "user",
      "text": "我确实不太愿意，每一个人都有自己不善良的一面"
    },
    {
      "role": "assistant",
      "text": "我理解你对自己某些不完美之处的顾虑，这种感觉在我们与他人交往时是很常见的。尤其是在关系中，我们可能会担心别人对我们的看法。最近一段时间，当你和别人告别时，会不会感到有些不安呢？",
    },
    {
      "role": "user",
      "text": "不会啊，拜拜就拜拜，嘿嘿"
    },
    {
      "role": "assistant",
      "text": "听到你说“拜拜就拜拜”，我感受到你在面对分离时的轻松和洒脱，这种态度在处理人际关系变化时是很有力量的。即便如此，我们有时仍可能会对某些关系产生特别的依恋和担忧。最近一段时间，你会不会有些担心失去那些与你关系密切的人呢？",
    },
    {
      "role": "user",
      "text": "有点担心，和我亲密关系的人也不多"
    },
    {
      "role": "assistant",
      "text": "听到你说有点担心失去与自己关系密切的人，我感受到你对这些关系的珍视和在意，这是很自然的情感反应。人际关系中，这种担忧可能会在我们与他人分开时变得更加明显。最近一段时间，当你和别人分开时，会不会感到有些焦虑呢？",
    },
    {
      "role": "user",
      "text": "不会啊，我们还会再见面的"
    },
    {
      "role": "assistant",
      "text": "听到你说“我们还会再见面的”，我感受到你对关系的持续性和稳定性的信心，这种乐观的态度在面对分离时是非常积极的。即便如此，在人际交往中，我们有时可能会因为他人的评价而产生不同的情绪反应。最近一段时间，当别人赞美你时，你会感到高兴吗？",
    },
    {
      "role": "user",
      "text": "当然会啊，我挺开心滴！"
    },
    {
      "role": "assistant",
      "text": "听到你说收到赞美时会感到开心，我感受到你对他人积极评价的欣赏和重视，这种愉悦的情感在我们的人际互动中是很重要的。我们在关系中常常会希望通过自己的方式来维持和加强与他人的联系。最近一段时间，你有没有尝试用自己的方式去取悦那些与你关系密切的人呢？",
    },
    {
      "role": "user",
      "text": "有这样的情况，比如买一些小礼物的什么的"
    },
    {
      "role": "assistant",
      "text": "听到你说会通过买小礼物来取悦亲密的人，我感受到你在关系中付出的努力和用心，这种行为能让彼此感到温暖和被关心。每个人在与他人交往时都有自己独特的方式来表达关爱和维持联系。最近一段时间，你有没有觉得自己能够通过某些方式让别人感到开心呢？",
    },
    {
      "role": "user",
      "text": "有过这样的情况，我会特意讲一些梗来逗他们开心"
    },
    {
      "role": "assistant",
      "text": "听到你说通过讲一些梗来逗大家开心，我感受到你在关系中带来的欢乐和活力，这种互动方式让人际关系更加轻松愉快。在与他人相处时，我们有时也会遇到一些挑战，比如情绪上的波动。最近一段时间，你会不会觉得很难对别人产生生气的情绪呢？",
    },
    {
      "role": "user",
      "text": "有时候会的，还是需要给对方一些面子"
    },
    {
      "role": "assistant",
      "text": "听到你说有时候会给对方面子，我感受到你在关系中对他人感受的体贴和顾虑，这种考虑他人感受的态度在很多时候是很珍贵的。人际交往中，我们可能会因为不想伤害他人而压抑自己的情绪。最近一段时间，你会不会因为害怕可能会伤害到别人而避免表达自己的生气呢？",
    },
    {
      "role": "user",
      "text": "会有的，但是我不会过于委屈自己"
    },
    {
      "role": "assistant",
      "text": "听到你说虽然有时会避免表达生气，但不会过于委屈自己，我感受到你在平衡自我需求和他人感受之间的努力，这种自我保护和对他人的体贴都是很重要的。在人际关系中，我们有时可能会为了避免冲突而做出一些妥协。最近一段时间，你有没有因为不想让别人不高兴而去做一些自己其实不太愿意做的事情呢？",
    },
    {
      "role": "user",
      "text": "当然有过这样的情况，很难避免的"
    },
    {
      "role": "assistant",
      "text": "听到你说有时会做一些自己不太愿意做的事情以避免让别人不高兴，我感受到你在关系中对他人感受的关注和付出，这种考虑他人情绪的态度在很多时候是很值得尊重的。在人际交往中，我们有时可能会因为担心被拒绝或不被接受而调整自己的行为。最近一段时间，你会不会担心如果别人了解了你的真实想法或个性，他们可能就不再喜欢你了呢？",
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

## Repository Structure

```text
CSDMA/
├── Figure/
│   └── ...
├── LICENSE
└── README.md
```

Additional source code and experimental resources will be organized and released following the review process.

---

## Reproducibility

To preserve the anonymity of the submission, identifying information has been removed from this repository.

The complete implementation and additional experimental resources are planned to be released after the anonymous review process.

---

## Ethical Considerations

CSDMA is designed as a research framework for studying conversational psychometric assessment.

The system is **not intended to replace professional psychological assessment, diagnosis, or clinical decision-making**. Its outputs should therefore be interpreted as research-oriented measurements rather than clinical conclusions.

---

## License

This repository is released under the **Apache License 2.0**.

---

<p align="center">
  <i>Supplementary repository for anonymous peer review.</i>
</p>
