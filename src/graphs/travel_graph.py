from typing import TypedDict, Optional, Dict, Any, List
from langgraph.graph import StateGraph, END
from src.agents.travel_agent import TravelAgent
from src.agents.decision_agent import DecisionAgent
from src.config.settings import config
from langchain_openai import ChatOpenAI
import json

class TravelState(TypedDict):
    """定义图的状态"""
    messages: List[Dict[str, str]]
    user_input: str
    keywords: Dict[str, Optional[str]]
    sql_result: List[Dict[str, Any]]
    rag_result: str
    travel_response: str  # TravelAgent 的原始响应
    final_response: str
    next_step: str  # 用于条件路由

class TravelGraph:
    def __init__(self):
        self.travel_agent = TravelAgent(name="TravelAssistant")
        self.decision_agent = DecisionAgent(name="DecisionMaker", travel_agent=self.travel_agent)
        
    def decide_intent(self, state: TravelState) -> TravelState:
        """
        使用 DecisionAgent 判断用户意图：
        - 设置 next_step 为 "search_knowledge": 需要进行旅游检索
        - 设置 next_step 为 "direct_response": 闲聊，直接回复
        """
        user_input = state["user_input"]
        
        # 触发关键词：美食、景点、交通、住宿、体验（包含经验、分享、心得等）
        trigger_keywords = ['美食', '景点', '交通', '住宿', '体验', '经验', '分享', '感悟', '心得', '攻略',
                           '推荐', '哪里', '怎么去', '好玩', '好吃', '路线', '行程']
        
        if any(keyword in user_input for keyword in trigger_keywords):
            print(f"检测到旅游相关关键词，进入检索流程: {user_input}")
            next_step = "search_knowledge"
        else:
            print(f"未检测到旅游关键词，直接响应: {user_input}")
            next_step = "direct_response"
        
        return {
            **state,
            "next_step": next_step
        }
    
    def extract_keywords(self, state: TravelState) -> TravelState:
        """提取用户输入中的关键词"""
        user_input = state["user_input"]
        keywords = self.travel_agent.extract_keywords_sync(user_input)
        print(f"提取的关键词: {keywords}")
        return {
            **state,
            "keywords": keywords
        }
    
    def search_knowledge(self, state: TravelState) -> TravelState:
        """执行数据库查询和RAG检索"""
        keywords = state["keywords"]
        user_input = state["user_input"]
        
        # 执行 SQL 查询
        sql, params = self.travel_agent.generate_sql(keywords)
        sql_result = self.travel_agent.execute_sql(sql, params)
        
        # 执行 RAG 检索
        rag_result = self.travel_agent.query_rag(user_input)
        
        return {
            **state,
            "sql_result": sql_result,
            "rag_result": rag_result
        }
    
    def generate_travel_response(self, state: TravelState) -> TravelState:
        """生成旅游检索响应"""
        user_input = state["user_input"]
        keywords = state["keywords"]
        sql_result = state["sql_result"]
        rag_result = state["rag_result"]
        
        # 格式化 SQL 响应
        raw_sql_response = self.travel_agent.format_response(sql_result, keywords)
        
        # 合并 SQL 和 RAG 结果作为上下文
        combined_context = f"【数据库查询结果】:\n{raw_sql_response}\n\n【知识库检索结果】:\n{rag_result}"
        
        # 使用大模型生成回复
        travel_response = self.travel_agent.generate_final_answer_sync(user_input, combined_context)
        
        return {
            **state,
            "travel_response": travel_response
        }
    
    async def evaluate_and_decide(self, state: TravelState) -> TravelState:
        """
        使用 DecisionAgent 评估 TravelAgent 的响应是否有效：
        - 如果有效，直接返回结果
        - 如果无效，使用 DecisionAgent 补充回答
        """
        user_input = state["user_input"]
        travel_response = state["travel_response"]
        
        # 构建消息历史
        messages = state["messages"].copy()
        messages.append({"role": "user", "content": user_input})
        
        # 使用 DecisionAgent 进行评估和决策（异步调用）
        result = await self.decision_agent.reply(messages)
        final_response = result.get('content', travel_response)
        
        # 如果 DecisionAgent 返回了不同的内容，说明进行了补充回答
        if final_response != travel_response:
            print("DecisionAgent 进行了补充回答")
        
        return {
            **state,
            "final_response": final_response
        }
    
    def direct_response(self, state: TravelState) -> TravelState:
        """直接响应（不进行知识检索，用于闲聊）"""
        user_input = state["user_input"]
        messages = [
            {"role": "system", "content": self.travel_agent.sys_prompt}
        ]
        
        # 添加历史消息
        for msg in state["messages"]:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        
        # 添加当前用户消息
        messages.append({"role": "user", "content": user_input})
        
        # 调用模型
        response = self.travel_agent.model.invoke(messages)
        response_content = response.content if hasattr(response, 'content') else str(response)
        
        return {
            **state,
            "final_response": response_content
        }
    
    def build_graph(self) -> StateGraph:
        """构建 LangGraph 图"""
        workflow = StateGraph(TravelState)
        
        # 添加节点
        workflow.add_node("decide_intent", self.decide_intent)
        workflow.add_node("extract_keywords", self.extract_keywords)
        workflow.add_node("search_knowledge", self.search_knowledge)
        workflow.add_node("generate_travel_response", self.generate_travel_response)
        workflow.add_node("evaluate_and_decide", self.evaluate_and_decide)
        workflow.add_node("direct_response", self.direct_response)
        
        # 设置起点
        workflow.set_entry_point("decide_intent")
        
        # 添加条件边：根据意图决定下一步
        workflow.add_conditional_edges(
            "decide_intent",
            lambda state: state["next_step"],  # 从状态中读取下一步
            {
                "search_knowledge": "extract_keywords",
                "direct_response": "direct_response"
            }
        )
        
        # 旅游检索流程
        workflow.add_edge("extract_keywords", "search_knowledge")
        workflow.add_edge("search_knowledge", "generate_travel_response")
        workflow.add_edge("generate_travel_response", "evaluate_and_decide")
        
        # 添加到终点的边
        workflow.add_edge("evaluate_and_decide", END)
        workflow.add_edge("direct_response", END)
        
        return workflow
    
    def run(self, user_input: str, messages: List[Dict[str, str]] = None) -> str:
        """运行图并返回结果（同步包装器，不推荐在已有事件循环中使用）"""
        import asyncio
        try:
            # 检查是否已有运行中的事件循环
            loop = asyncio.get_running_loop()
            # 如果已有事件循环，直接运行协程
            return loop.run_until_complete(self.arun(user_input, messages))
        except RuntimeError:
            # 如果没有事件循环，创建新的
            return asyncio.run(self.arun(user_input, messages))
    
    async def arun(self, user_input: str, messages: List[Dict[str, str]] = None) -> str:
        """运行图并返回结果（异步版本）"""
        graph = self.build_graph()
        app = graph.compile()
        
        # 初始化状态
        initial_state: TravelState = {
            "messages": messages or [],
            "user_input": user_input,
            "keywords": {},
            "sql_result": [],
            "rag_result": "",
            "travel_response": "",
            "final_response": "",
            "next_step": ""
        }
        
        # 执行图（使用异步调用）
        result = await app.ainvoke(initial_state)
        
        return result["final_response"]

# 创建全局实例
travel_graph = TravelGraph()