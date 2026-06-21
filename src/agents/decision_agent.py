from src.config.settings import config
from src.utils.logger import logger, log_performance
import json

class DecisionAgent:
    def __init__(self, name: str = "DecisionMaker", travel_agent=None):
        """
        初始化决策智能体
        
        Args:
            name: 智能体名称
            travel_agent: 绑定的 TravelAgent 实例
        """
        self.name = name
        self.travel_agent = travel_agent
        self.model = travel_agent.model if travel_agent else None
        self.sys_prompt = """你是一个智能决策中心。你的任务是协调多智能体协作流：
1. 用户的输入会先由 TravelAgent（专业的旅游数据库查询专家）处理。
2. 你需要评估 TravelAgent 返回的内容是否有效：
   - 如果 TravelAgent 明确表示"未找到相关信息"、"数据库中没有"或回复内容过于简短且无实质性帮助，则判定为【无效】。
   - 否则判定为【有效】。
3. 如果判定为【无效】，你需要亲自出马，利用你作为通用大模型的知识经验，直接为用户提供专业且详细的旅游建议。
4. 如果判定为【有效】，你只需直接透传 TravelAgent 的结果，或在必要时做极简的格式修饰。

请以专业的语气回答，确保用户得到满意的答案。"""

    @log_performance
    async def reply(self, msg_history=None) -> dict:
        user_message = ""
        
        # 统一输入格式处理
        if isinstance(msg_history, list) and msg_history:
            last_msg = msg_history[-1]
            # 支持字典格式和对象格式
            if isinstance(last_msg, dict):
                user_message = last_msg.get('content', str(last_msg))
            else:
                user_message = last_msg.content if hasattr(last_msg, 'content') else str(last_msg)
        elif msg_history:
            if isinstance(msg_history, dict):
                user_message = msg_history.get('content', str(msg_history))
            else:
                user_message = msg_history.content if hasattr(msg_history, 'content') else str(msg_history)
        
        logger.info(f"DecisionAgent 接收到任务: {user_message[:50]}...")

        # 先让 TravelAgent 尝试查询（基于数据库和 RAG）
        travel_response = await self.travel_agent.reply(msg_history)
        travel_content = travel_response.get('content', '') if isinstance(travel_response, dict) else str(travel_response)

        # 打印 TravelAgent 响应（详细日志）
        logger.info(f"====== DecisionAgent 决策过程开始 ======")
        logger.info(f"【用户输入】: {user_message}")
        logger.info(f"【TravelAgent 响应长度】: {len(travel_content)} 字符")
        logger.info(f"【TravelAgent 响应摘要】: {travel_content[:100]}..." if len(travel_content) > 100 else f"【TravelAgent 响应】: {travel_content}")

        # 决策判断：TravelAgent 的回复是否足够好？
        failure_keywords = [
            "未找到", "没有找到", "数据库中没有", "抱歉，我无法在数据库中", 
            "资料还不太丰富", "掌握的资料还不太丰富", "目前还没有详细的资料",
            "没有详细的资料", "不能真正踏上", "想象一下", "确切的资料", "资料库中没有",
            "暂时没有收录", "暂时没有关于", "抱歉，我现在无法提供"
        ]
        
        # 检测失败关键词
        detected_failure_kws = [kw for kw in failure_keywords if kw in travel_content]
        has_failure_keyword = len(detected_failure_kws) > 0
        
        success_indicators = ["推荐", "可以去", "建议", "特色", "必吃", "景点", "位于"]
        # 检测成功关键词
        detected_success_indicators = [si for si in success_indicators if si in travel_content]
        has_success_indicator = len(detected_success_indicators) > 0

        # 打印检测结果
        logger.info(f"【失败关键词检测】: {'检测到: ' + ', '.join(detected_failure_kws) if has_failure_keyword else '未检测到'}")
        logger.info(f"【成功关键词检测】: {'检测到: ' + ', '.join(detected_success_indicators) if has_success_indicator else '未检测到'}")
        logger.info(f"【响应长度检查】: {len(travel_content.strip())} 字符 (阈值: 100)")

        # 判定逻辑
        is_invalid = False
        reason = ""
        
        if has_failure_keyword and not has_success_indicator:
            is_invalid = True
            reason = "检测到失败关键词且无成功关键词"
        elif len(travel_content.strip()) < 100 and not has_success_indicator:
            is_invalid = True
            reason = "响应内容过短且无成功关键词"
        elif "未找到匹配答案" in travel_content and not has_success_indicator:
            is_invalid = True
            reason = "包含'未找到匹配答案'且无成功关键词"

        # 打印判定结果
        logger.info(f"【判定结果】: {'无效' if is_invalid else '有效'}")
        if is_invalid:
            logger.info(f"【判定原因】: {reason}")

        if not is_invalid:
            logger.info("【决策】: TravelAgent 提供的信息有效，直接返回")
            logger.info(f"====== DecisionAgent 决策过程结束 ======")
            return {"content": travel_content, "role": "assistant", "name": self.name}
        
        # 如果 TravelAgent 失效，调用大模型自身的通用知识库
        logger.warning("【决策】: TravelAgent 信息缺失，启动大模型经验补全")
        
        # 识别用户核心意图
        intent = "旅游建议"
        if any(kw in user_message for kw in ["美食", "吃", "餐厅", "特产"]):
            intent = "美食建议"
        elif any(kw in user_message for kw in ["景点", "玩", "地方", "去哪"]):
            intent = "景点游玩建议"
        elif any(kw in user_message for kw in ["交通", "车", "怎么去"]):
            intent = "交通出行建议"
        elif any(kw in user_message for kw in ["住宿", "酒店", "住"]):
            intent = "住宿建议"
        
        logger.info(f"【识别意图】: {intent}")

        # 构建一个更聚焦用户问题的 Prompt
        prompt = f"""
用户的问题是："{user_message}"
TravelAgent（基于数据库）的反馈是："{travel_content}"

由于数据库中缺乏相关精准信息，请你利用你的通用旅游知识经验，为用户提供一个详尽、专业的回复。

要求：
1. **高度聚焦**：如果用户问的是美食，请重点回答美食；如果问的是景点，请重点回答景点。不要给出一个大而全的通用模板。
2. **专业性**：提供具体的名称（如餐厅名、景点名）和推荐理由。
3. **结构化**：使用清晰的标题或列表，但要保持亲切的导游语气。
4. **简洁明了**：不要提及"数据库查不到"这类技术细节。

请直接给出针对用户问题的【{intent}】：
"""
        
        # 使用当前的模型直接生成回复
        model_msg = {"role": "user", "content": prompt}
        response = self.model.invoke([model_msg])
    
        # 提取响应内容
        final_content = response.content if hasattr(response, 'content') else str(response)
        
        logger.info(f"【补充回答长度】: {len(final_content)} 字符")
        logger.info(f"====== DecisionAgent 决策过程结束 ======")

        return {"content": final_content, "role": "assistant", "name": self.name}