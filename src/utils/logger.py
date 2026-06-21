import logging
import sys
import os
import time
import json
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Any, Optional, Dict, List
from contextvars import ContextVar
from rich.logging import RichHandler
from rich.console import Console
from functools import wraps

# 全局上下文变量，用于全链路追踪
request_id_var: ContextVar[str] = ContextVar("request_id", default="system")

# 确保日志目录存在
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# 基础格式配置
LOG_FORMAT = "%(name)s - %(message)s"
# JSON 格式用于分析
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
            "filename": record.filename,
            "lineno": record.lineno,
            "funcName": record.funcName
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "duration"):
            log_record["duration_ms"] = record.duration
        return json.dumps(log_record, ensure_ascii=False)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt="[%X]",
    handlers=[
        # 控制台使用 Rich 美化输出
        RichHandler(
            console=Console(width=120),
            rich_tracebacks=True, 
            markup=True,
            show_path=True
        ),
        # 结构化 JSON 日志文件，用于后续分析
        RotatingFileHandler(
            os.path.join(LOG_DIR, "app.json.log"),
            maxBytes=20*1024*1024,
            backupCount=10,
            encoding="utf-8"
        )
    ]
)

# 设置 JSON 格式化器给文件处理器
for handler in logging.root.handlers:
    if isinstance(handler, RotatingFileHandler):
        handler.setFormatter(JsonFormatter())

# 获取主记录器
logger = logging.getLogger("TravelAssistant")

def set_request_id(request_id: Optional[str] = None):
    """设置当前链路的 Request ID"""
    rid = request_id or str(uuid.uuid4())
    request_id_var.set(rid)
    return rid

def get_request_id():
    """获取当前链路的 Request ID"""
    return request_id_var.get()

def log_performance(func):
    """性能监控装饰器"""
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            return result
        finally:
            duration = (time.perf_counter() - start_time) * 1000
            logger.info(f"函数 {func.__name__} 执行耗时: {duration:.2f}ms", extra={"duration": duration})
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            duration = (time.perf_counter() - start_time) * 1000
            logger.info(f"函数 {func.__name__} 执行耗时: {duration:.2f}ms", extra={"duration": duration})
    
    import inspect
    return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper

def log_rag_query(query: str, result: str):
    """打印 RAG 查询日志"""
    # 截断超长结果
    display_result = result[:1000] + "..." if len(result) > 1000 else result
    
    msg = (
        "\n[bold cyan]" + "="*60 + "[/bold cyan]\n"
        "[bold yellow]RAG 检索[/bold yellow]\n"
        f"[blue]查询内容:[/blue] {query}\n"
        f"[green]检索结果:[/green]\n{display_result}\n"
        "[bold cyan]" + "="*60 + "[/bold cyan]\n"
    )
    logger.info(msg, extra={"markup": True})

def log_sql_query(sql: str, params: Any, results: List[Dict] = None):
    """打印 SQL 查询日志"""
    result_count = len(results) if results else 0
    
    # 准备结果详情展示
    result_detail = ""
    if results:
        # 只展示前 3 条结果
        show_count = min(3, result_count)
        result_detail = f"\n[green]结果详情 (前{show_count}条):[/green]\n"
        for i in range(show_count):
            result_detail += f"  - {results[i]}\n"
        if result_count > 3:
            result_detail += "  ... (更多结果已省略)\n"
    
    msg = (
        "\n[bold magenta]" + "="*60 + "[/bold magenta]\n"
        "[bold yellow]SQL 查询[/bold yellow]\n"
        f"[blue]SQL 语句:[/blue] [italic]{sql}[/italic]\n"
        f"[blue]查询参数:[/blue] {params}\n"
        f"[green]结果条数:[/green] {result_count}\n"
        f"{result_detail}"
        "[bold magenta]" + "="*60 + "[/bold magenta]\n"
    )
    logger.info(msg, extra={"markup": True})

class LogAnalyzer:
    """简易日志分析器"""
    @staticmethod
    def analyze_latency(log_file: str = "logs/app.json.log"):
        """分析函数执行耗时统计"""
        durations = []
        if not os.path.exists(log_file):
            return "日志文件不存在"
            
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if "duration_ms" in data:
                        durations.append(data["duration_ms"])
                except:
                    continue
        
        if not durations:
            return "未找到性能数据"
            
        return {
            "count": len(durations),
            "avg_ms": sum(durations) / len(durations),
            "max_ms": max(durations),
            "min_ms": min(durations)
        }


