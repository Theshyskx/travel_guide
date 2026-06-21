import json
import os
from datetime import datetime
from typing import List, Dict, Optional

class SessionManager:
    def __init__(self, sessions_dir: str = 'sessions'):
        self.sessions_dir = sessions_dir
        if not os.path.exists(self.sessions_dir):
            os.makedirs(self.sessions_dir)
    
    def save_session(self, session_id: str, messages: List[Dict], title: str = None, preview: str = None):
        """保存会话历史"""
        session_data = {
            'session_id': session_id,
            'title': title or '新对话',
            'preview': preview or '对话预览',
            'messages': messages,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        session_file = os.path.join(self.sessions_dir, f'{session_id}.json')
        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)
    
    def load_session(self, session_id: str) -> Optional[Dict]:
        """加载会话历史"""
        session_file = os.path.join(self.sessions_dir, f'{session_id}.json')
        if os.path.exists(session_file):
            with open(session_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None
    
    def get_all_sessions(self) -> List[Dict]:
        """获取所有会话列表"""
        sessions = []
        for filename in os.listdir(self.sessions_dir):
            if filename.endswith('.json'):
                session_file = os.path.join(self.sessions_dir, filename)
                try:
                    with open(session_file, 'r', encoding='utf-8') as f:
                        session_data = json.load(f)
                        sessions.append({
                            'id': session_data['session_id'],
                            'title': session_data['title'],
                            'preview': session_data['preview'],
                            'updated_at': session_data['updated_at']
                        })
                except Exception as e:
                    print(f"加载会话文件 {filename} 失败: {e}")
        
        # 按更新时间排序，最新的在前
        sessions.sort(key=lambda x: x['updated_at'], reverse=True)
        return sessions
    
    def delete_session(self, session_id: str):
        """删除会话"""
        session_file = os.path.join(self.sessions_dir, f'{session_id}.json')
        if os.path.exists(session_file):
            os.remove(session_file)
    
    def update_session_title(self, session_id: str, title: str):
        """更新会话标题"""
        session_data = self.load_session(session_id)
        if session_data:
            session_data['title'] = title
            session_data['updated_at'] = datetime.now().isoformat()
            session_file = os.path.join(self.sessions_dir, f'{session_id}.json')
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)
    
    def update_session_preview(self, session_id: str, preview: str):
        """更新会话预览"""
        session_data = self.load_session(session_id)
        if session_data:
            session_data['preview'] = preview
            session_data['updated_at'] = datetime.now().isoformat()
            session_file = os.path.join(self.sessions_dir, f'{session_id}.json')
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)

# 全局会话管理器实例
session_manager = SessionManager()