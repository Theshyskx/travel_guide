from langchain_openai import ChatOpenAI
from src.config.settings import config
from src.database.db_manager import db_manager
from src.services.rag_service import rag_service
from src.utils.logger import log_sql_query, log_rag_query
import json
import re

class TravelAgent:
    def __init__(self, name: str = "TravelAssistant"):
        model_config = config.get_model_config()
        self.model = ChatOpenAI(
            model=model_config['model'],
            api_key=model_config['api_key'],
            base_url=model_config['base_url']
        )
        self.name = name
        self.sys_prompt = """你是一个专业的旅游建议助手。你的主要职责是：
1. 为用户提供旅游目的地推荐
2. 提供旅游行程规划建议
3. 回答关于旅游相关的问题
4. 提供实用的旅游建议和注意事项

请用友好、专业的语气与用户交流，尽可能提供详细和有用的信息。"""
        self.keyword_extraction_prompt = """你是一个专业的旅游关键词提取助手。你的任务是从用户的旅游相关问题中提取出：
1. 目的地关键词（如城市、景区名称）
2. 信息类型关键词（如美食、景点、交通、住宿等）
请以JSON格式输出结果，包含destination和info_type两个字段。
示例：
用户输入："阳朔必吃美食"
输出：{"destination": "阳朔", "info_type": "美食"}
用户输入："丽江古城的交通方式"
输出：{"destination": "丽江古城", "info_type": "交通"}
用户输入："宏村的住宿推荐"
输出：{"destination": "宏村", "info_type": "住宿"}
"""
    
    def _extract_content_from_response(self, response) -> str:
        """从模型响应中提取文本内容，支持流式和非流式"""
        if not response:
            return ""
            
        # 1. 基础类型直接处理
        if isinstance(response, (str, list)):
            return self._extract_simple_content(response)

        # 2. 处理 LangChain 的 AIMessage 或其他带 content 属性的对象
        if hasattr(response, 'content'):
            content = response.content
            if content is not None and not isinstance(content, (str, list, dict)):
                return self._extract_content_from_response(content)
            return self._extract_simple_content(content)
        
        # 3. 处理字典格式
        if isinstance(response, dict):
            content = response.get('content')
            if content is not None:
                return self._extract_content_from_response(content)
            return self._extract_simple_content(response)

        # 4. 兜底提取
        return self._extract_simple_content(response)

    def _extract_simple_content(self, content) -> str:
        """提取非流式的简单内容（字符串、列表等）"""
        if isinstance(content, str):
            return content
        
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, str):
                    text_parts.append(part)
                elif isinstance(part, dict):
                    text_parts.append(part.get('text', part.get('content', '')))
                elif hasattr(part, 'text'):
                    text_parts.append(str(part.text))
                elif hasattr(part, 'content'):
                    text_parts.append(str(part.content))
            return "".join(text_parts)
            
        if hasattr(content, 'content'):
            return self._extract_simple_content(content.content)
            
        if hasattr(content, 'text'):
            return str(content.text)

        return str(content) if content is not None else ""

    def extract_keywords_sync(self, user_input: str) -> dict:
        """同步版本：提取用户输入中的关键词"""
        try:
            messages = [
                {"role": "system", "content": self.keyword_extraction_prompt},
                {"role": "user", "content": user_input}
            ]
            
            response = self.model.invoke(messages)
            reply_content = self._extract_content_from_response(response)
            
            print(f"关键词提取结果: {reply_content}")
            
            if not reply_content:
                print("模型未返回关键词内容")
                return self._backup_keyword_extraction(user_input)
            
            json_match = re.search(r'\{.*\}', reply_content, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                try:
                    keywords = json.loads(json_str)
                    return keywords
                except json.JSONDecodeError:
                    print(f"JSON 解析失败: {json_str}")
            
            try:
                keywords = json.loads(reply_content)
                return keywords
            except:
                pass
                
            return self._backup_keyword_extraction(user_input)
        except Exception as e:
            print(f"关键词提取错误: {e}")
            return self._backup_keyword_extraction(user_input)
    
    async def extract_keywords(self, user_input: str) -> dict:
        """异步版本：提取用户输入中的关键词"""
        return self.extract_keywords_sync(user_input)
    
    def _get_all_destinations(self):
        """从数据库获取所有目的地"""
        try:
            query = "SELECT DISTINCT destination FROM tourism_data"
            result = db_manager.execute_query(query)
            return [row['destination'] for row in result if row['destination']]
        except Exception as e:
            print(f"获取目的地列表失败: {e}")
            return ['阳朔', '丽江', '宏村', '凤凰', '朱家尖', '桂林', '黄山', '舟山']
    
    def _backup_keyword_extraction(self, user_input: str) -> dict:
        """备份关键词提取方案"""
        destinations = self._get_all_destinations()
        info_types = {
            '交通': ['交通安排', '交通方式', '怎么去', '路线', '出行', '交通'],
            '住宿': ['住宿推荐', '酒店', '民宿', '住'],
            '美食': ['美食推荐', '必吃', '特色菜', '餐厅', '美食', '吃'],
            '景点': ['必打卡景点', '景点', '玩', '游览', '参观', '风景'],
            '体验': ['旅行感悟', '体验', '感受', '心得', '印象', '经验', '分享', '攻略']
        }
        
        destination = None
        info_type = None
        
        for it, keywords in info_types.items():
            for keyword in keywords:
                if keyword in user_input:
                    info_type = it
                    break
            if info_type:
                break
        
        sorted_destinations = sorted(destinations, key=len, reverse=True)
        for dest in sorted_destinations:
            if dest in user_input:
                destination = dest
                break
        
        if not destination:
            stop_words = [
                '美食', '景点', '交通', '住宿', '体验', '必吃', '推荐', '攻略', '安排',
                '我要去', '有什么', '吗', '呢', '吧', '啊', '的', '了', '在', '去', '想',
                '请问', '告诉', '我', '你', '我们', '大家', '一下', '看看', '说说', '问问'
            ]
            cleaned_input = user_input
            for word in stop_words:
                cleaned_input = cleaned_input.replace(word, '')
            
            potential_destinations = re.findall(r'[\u4e00-\u9fa5]{2,6}', cleaned_input)
            
            for potential in potential_destinations:
                for dest in destinations:
                    if potential in dest or dest in potential:
                        destination = dest
                        break
                if destination:
                    break
            
            if not destination and potential_destinations:
                place_suffixes = ['山', '城', '古城', '古镇', '岛', '湖', '江', '河', '海', '沟', '谷', '峰', '岭', '寨', '村', '镇', '市', '区', '县']
                
                for potential in potential_destinations:
                    for suffix in place_suffixes:
                        potential_with_suffix = potential + suffix
                        for dest in destinations:
                            if potential_with_suffix in dest or dest in potential_with_suffix:
                                destination = dest
                                break
                        if destination:
                            break
                    if destination:
                        break
            
            if not destination and potential_destinations:
                destination = potential_destinations[0]
        
        return {"destination": destination, "info_type": info_type}
    
    def generate_sql(self, keywords: dict) -> tuple:
        """根据关键词生成SQL查询语句和参数"""
        destination = keywords.get('destination')
        info_type = keywords.get('info_type')
        
        field_map = {
            '美食': 'food',
            '景点': 'attractions',
            '交通': 'transportation',
            '住宿': 'accommodation',
            '体验': 'experience'
        }
        
        field = field_map.get(info_type, '*')
        
        if destination:
            flexible_dest = "%" + "%".join(list(destination)) + "%"
                
            if field == '*':
                query = "SELECT * FROM tourism_data WHERE destination LIKE %s"
                params = (flexible_dest,)
            else:
                query = f"SELECT destination, {field} FROM tourism_data WHERE destination LIKE %s"
                params = (flexible_dest,)
        else:
            if field != '*':
                query = f"SELECT destination, {field} FROM tourism_data WHERE {field} IS NOT NULL AND {field} != '' LIMIT 5"
                params = ()
            else:
                query = "SELECT * FROM tourism_data LIMIT 5"
                params = ()
        
        print(f"生成的SQL: {query}")
        print(f"参数: {params}")
        return query, params
    
    def execute_sql(self, query: str, params: tuple = ()) -> list:
        """执行SQL查询"""
        try:
            result = db_manager.execute_query(query, params)
            log_sql_query(query, params, result)
            return result
        except Exception as e:
            print(f"SQL执行错误: {e}")
            return []
    
    def query_rag(self, query_text: str) -> str:
        """执行RAG检索"""
        return rag_service.query(query_text)
    
    def format_response(self, result: list, keywords: dict) -> str:
        """格式化查询结果"""
        if not result:
            return "抱歉，未找到相关信息。"
        
        destination = keywords.get('destination')
        info_type = keywords.get('info_type')
        
        if len(result) == 1:
            row = result[0]
            if destination:
                response = f"关于{destination}的{info_type}信息：\n\n"
            else:
                response = f"关于{info_type}的信息：\n\n"
            
            field_map = {
                '美食': 'food',
                '景点': 'attractions',
                '交通': 'transportation',
                '住宿': 'accommodation',
                '体验': 'experience'
            }
            
            field_name = field_map.get(info_type)
            if field_name and row.get(field_name):
                content = row[field_name]
                cleaned_content = self._clean_duplicate_content(content)
                response += f"{cleaned_content}"
            else:
                if 'food' in row and row['food']:
                    response += f"美食: {row['food']}\n\n"
                if 'attractions' in row and row['attractions']:
                    response += f"景点: {row['attractions']}\n\n"
                if 'transportation' in row and row['transportation']:
                    response += f"交通: {row['transportation']}\n\n"
                if 'accommodation' in row and row['accommodation']:
                    response += f"住宿: {row['accommodation']}\n\n"
                if 'experience' in row and row['experience']:
                    response += f"体验: {row['experience']}\n"
            
            return response
        else:
            if destination:
                response = f"关于{destination}的{info_type}信息：\n\n"
            else:
                response = f"关于{info_type}的信息：\n\n"
            
            for i, row in enumerate(result, 1):
                response += f"{i}. 目的地: {row.get('destination', '未知')}\n"
                if 'food' in row and row['food']:
                    response += f"   美食: {row['food']}\n"
                if 'attractions' in row and row['attractions']:
                    response += f"   景点: {row['attractions']}\n"
                if 'transportation' in row and row['transportation']:
                    response += f"   交通: {row['transportation']}\n"
                if 'accommodation' in row and row['accommodation']:
                    response += f"   住宿: {row['accommodation']}\n"
                if 'experience' in row and row['experience']:
                    response += f"   体验: {row['experience']}\n"
                response += "\n"
            
            return response
    
    def _clean_duplicate_content(self, content: str) -> str:
        """对内容进行简单的去重处理"""
        if not content:
            return ""
        
        sentences = re.split(r'[。！？\n]', content)
        
        unique_sentences = []
        seen = set()
        
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and sentence not in seen:
                unique_sentences.append(sentence)
                seen.add(sentence)
        
        cleaned_content = '。'.join(unique_sentences)
        
        if len(cleaned_content) > 500:
            sentences = cleaned_content.split('。')
            cleaned_content = '。'.join(sentences[:5])
            if not cleaned_content.endswith('。'):
                cleaned_content += '。'
        
        return cleaned_content
    
    def generate_final_answer_sync(self, user_input: str, combined_context: str) -> str:
        """同步版本：使用大模型结合背景知识生成最终回复"""
        try:
            prompt = f"""你是一个专业的旅游向导。请结合提供的背景知识，回答用户的旅游问题。

重要要求：
1. 以亲切、专业且富有吸引力的语气回复。
2. 整合提供的【数据库查询结果】和【知识库检索结果】，给出一个逻辑清晰、层次分明的回答。
3. 如果背景知识中存在重复信息，请合并去重，只保留最准确、最核心的部分。
4. 如果背景知识不足以完全回答用户问题，请基于已知信息回答，并给予适当的旅游建议。
5. 避免死板的罗列，要像真实的向导一样与用户交流。
6. 直接输出你的回复内容。

用户问题：{user_input}

参考背景知识：
{combined_context}

请作为旅游向导给出最终回复："""

            messages = [
                {"role": "system", "content": "你是一个专业的旅游向导，擅长整合信息并提供友好的回复。"},
                {"role": "user", "content": prompt}
            ]
            
            response = self.model.invoke(messages)
            final_content = self._extract_content_from_response(response)
            
            if not final_content:
                print("警告：大模型生成的最终回复内容为空")
                
            return final_content if final_content else "抱歉，我现在无法生成详细建议。请稍后再试。"
        except Exception as e:
            print(f"生成最终回复错误: {e}")
            return "抱歉，整合旅游信息时出现了问题。"
    
    async def generate_final_answer(self, user_input: str, combined_context: str) -> str:
        """异步版本：使用大模型结合背景知识生成最终回复"""
        return self.generate_final_answer_sync(user_input, combined_context)
    
    async def process_user_query(self, user_input: str) -> str:
        """处理用户查询的完整流程"""
        print(f"用户输入: {user_input}")
        
        keywords = await self.extract_keywords(user_input)
        print(f"提取的关键词: {keywords}")
        
        sql, params = self.generate_sql(keywords)
        sql_result = self.execute_sql(sql, params)
        
        rag_answer = self.query_rag(user_input)
        
        raw_sql_response = self.format_response(sql_result, keywords)
        
        combined_context = f"【数据库查询结果】:\n{raw_sql_response}\n\n【知识库检索结果】:\n{rag_answer}"
        
        print("正在整合 SQL 和 RAG 信息，由大模型生成最终回复...")
        final_response = await self.generate_final_answer(user_input, combined_context)
        return final_response
    
    async def reply(self, msg=None) -> dict:
        """兼容旧接口的回复方法"""
        try:
            user_input = ""
            if isinstance(msg, list):
                # 支持字典格式和对象格式
                if isinstance(msg[-1], dict):
                    user_input = msg[-1].get('content', '') if msg else ""
                else:
                    user_input = msg[-1].content if msg else ""
            elif msg:
                if isinstance(msg, dict):
                    user_input = msg.get('content', str(msg))
                else:
                    user_input = msg.content if hasattr(msg, 'content') else str(msg)
            
            trigger_keywords = ['美食', '景点', '交通', '住宿', '体验', '经验', '分享', '感悟', '心得', '攻略']
            if any(keyword in user_input for keyword in trigger_keywords):
                response_content = await self.process_user_query(user_input)
            else:
                messages = [
                    {"role": "system", "content": self.sys_prompt}
                ]
                
                if isinstance(msg, list):
                    for m in msg:
                        # 支持字典格式和对象格式
                        if isinstance(m, dict):
                            role = m.get('role', 'user')
                            content = m.get('content', str(m))
                        else:
                            role = m.role if hasattr(m, 'role') else 'user'
                            content = m.content if hasattr(m, 'content') else str(m)
                        messages.append({
                            "role": role,
                            "content": content
                        })
                elif msg:
                    messages.append({
                        "role": 'user',
                        "content": user_input
                    })
                
                print(f"发送消息到模型: {messages[-1]['content']}")
                
                response = self.model.invoke(messages)
                response_content = self._extract_content_from_response(response)
                
                if not response_content:
                    print(f"未知响应类型或内容为空: {type(response)}")
                    response_content = "抱歉，服务暂时不可用"
            
            print(f"模型回复: {response_content[:100]}...")
            
            return {"content": response_content, "role": "assistant", "name": self.name}
        except Exception as e:
            print(f"模型调用错误: {e}")
            return {"content": f"抱歉，服务暂时不可用: {str(e)}", "role": "assistant", "name": self.name}