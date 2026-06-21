import os
import sys
import torch
import chromadb
from typing import List, Dict, Any, Tuple
from sentence_transformers import SentenceTransformer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.utils.logger import logger

class HierarchicalRetrieval:
    """分层检索系统：细粒度子chunk用于检索，粗粒度父chunk用于LLM阅读"""
    
    def __init__(self):
        self.chroma_client = None
        self.child_collection = None  # 子chunk集合，用于向量检索
        self.parent_collection = None  # 父chunk集合，存储完整上下文
        self.model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.CHILD_TOKEN_SIZE = 150  # 子chunk大小
        self.PARENT_TOKEN_SIZE = 500  # 父chunk大小
        self.OVERLAP_SIZE = 25  # 重叠大小
        
    def initialize(self, embedding_model_path: str, vector_store_path: str):
        """初始化分层检索系统"""
        logger.info(f"正在使用设备: {self.device}")
        
        # 初始化Chroma客户端
        self.chroma_client = chromadb.PersistentClient(path=vector_store_path)
        
        # 创建子chunk集合（用于向量检索）
        self.child_collection = self.chroma_client.get_or_create_collection(
            name="child_chunks",
            metadata={"description": "细粒度子chunk，用于向量检索"}
        )
        
        # 创建父chunk集合（用于存储完整上下文）
        self.parent_collection = self.chroma_client.get_or_create_collection(
            name="parent_chunks",
            metadata={"description": "粗粒度父chunk，用于LLM阅读"}
        )
        
        # 加载嵌入模型
        self.model = SentenceTransformer(
            embedding_model_path,
            device=self.device,
            trust_remote_code=True
        )
        if self.device == "cuda":
            self.model.half()
            
        logger.info("分层检索服务初始化完成")
    
    def _tokenize_chinese(self, text: str) -> List[str]:
        """简单的中文分词，按字符数近似token数"""
        return list(text)
    
    def _count_tokens(self, text: str) -> int:
        """估算token数量（中文按字符数计算）"""
        return len(self._tokenize_chinese(text))
    
    def _split_text(self, text: str, chunk_size: int, overlap_size: int) -> List[str]:
        """按指定大小切分文本"""
        tokens = self._tokenize_chinese(text)
        chunks = []
        
        start = 0
        while start < len(tokens):
            end = start + chunk_size
            chunk_tokens = tokens[start:end]
            chunks.append(''.join(chunk_tokens))
            
            if end >= len(tokens):
                break
            start = end - overlap_size
        
        return chunks
    
    def add_document(self, document: str, doc_id: str = None):
        """添加文档并创建分层chunk结构"""
        if doc_id is None:
            doc_id = f"doc_{hash(document) % 1000000}"
        
        # 1. 创建粗粒度父chunk（500 token）
        parent_chunks = self._split_text(document, self.PARENT_TOKEN_SIZE, self.OVERLAP_SIZE)
        logger.info(f"文档 {doc_id} 切分为 {len(parent_chunks)} 个父chunk")
        
        # 2. 为每个父chunk创建细粒度子chunk（150 token）
        all_child_chunks = []
        all_parent_ids = []
        all_metadatas = []
        
        for parent_idx, parent_chunk in enumerate(parent_chunks):
            parent_chunk_id = f"{doc_id}_parent_{parent_idx}"
            
            # 添加父chunk到父集合
            self.parent_collection.add(
                documents=[parent_chunk],
                ids=[parent_chunk_id],
                metadatas=[{"doc_id": doc_id, "parent_idx": parent_idx}]
            )
            
            # 将父chunk切分为子chunk
            child_chunks = self._split_text(parent_chunk, self.CHILD_TOKEN_SIZE, self.OVERLAP_SIZE)
            
            for child_idx, child_chunk in enumerate(child_chunks):
                child_chunk_id = f"{doc_id}_child_{parent_idx}_{child_idx}"
                all_child_chunks.append(child_chunk)
                all_parent_ids.append(parent_chunk_id)
                all_metadatas.append({
                    "doc_id": doc_id,
                    "parent_id": parent_chunk_id,
                    "parent_idx": parent_idx,
                    "child_idx": child_idx
                })
        
        # 3. 为子chunk创建向量索引
        if all_child_chunks:
            embeddings = self.model.encode(all_child_chunks, normalize_embeddings=True).tolist()
            self.child_collection.add(
                documents=all_child_chunks,
                embeddings=embeddings,
                metadatas=all_metadatas,
                ids=[f"{doc_id}_child_{i}" for i in range(len(all_child_chunks))]
            )
        
        logger.info(f"文档 {doc_id} 处理完成：{len(parent_chunks)} 父chunk，{len(all_child_chunks)} 子chunk")
    
    def retrieve(self, query: str, top_k: int = 3) -> List[Tuple[str, float, Dict]]:
        """检索：先用子chunk匹配，再获取对应的父chunk"""
        # 1. 使用子chunk进行向量检索
        query_embedding = self.model.encode(query, normalize_embeddings=True).tolist()
        child_results = self.child_collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k * 2  # 查询更多结果用于去重
        )
        
        # 2. 提取父chunk ID并去重
        parent_ids = set()
        for meta in child_results.get("metadatas", [[]])[0]:
            if meta and meta.get("parent_id"):
                parent_ids.add(meta["parent_id"])
        
        # 3. 根据parent_id获取父chunk
        parent_results = []
        if parent_ids:
            parents = self.parent_collection.get(ids=list(parent_ids))
            for doc, meta in zip(parents.get("documents", []), parents.get("metadatas", [])):
                # 计算分数（基于子chunk的匹配分数）
                score = 1.0 / (len(parent_results) + 1)  # 简化的分数计算
                parent_results.append((doc, score, meta if meta else {}))
        
        # 4. 排序并返回
        parent_results.sort(key=lambda x: -x[1])
        return parent_results[:top_k]
    
    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return {
            "child_chunks": self.child_collection.count(),
            "parent_chunks": self.parent_collection.count()
        }


# 示例文档（约800字）
SAMPLE_DOCUMENT = """
故宫，又称紫禁城，是中国明清两代的皇家宫殿，位于北京市中心的紫禁城内。作为世界上现存规模最大、保存最为完整的木质结构古建筑群，故宫不仅是中国古代宫廷建筑艺术的巅峰之作，更是中华文明五千年历史的重要见证。

故宫始建于明成祖永乐四年（1406年），历时十四年建成，占地面积约72万平方米，建筑面积约15万平方米，拥有殿宇宫室9999间半。整个建筑群严格按照《周礼·考工记》中"前朝后寝"的规制布局，分为外朝和内廷两大部分。外朝以太和殿、中和殿、保和殿三大殿为中心，是皇帝举行重大典礼和处理政务的场所；内廷以乾清宫、交泰殿、坤宁宫为中心，两侧分布着东六宫和西六宫，是皇帝和后妃居住生活的地方。

故宫的建筑设计充分体现了中国古代的哲学思想和皇权至上的观念。黄色的琉璃瓦屋顶、红色的宫墙、白色的汉白玉台基，构成了鲜明的色彩对比，彰显出皇家的威严与尊贵。宫殿的布局讲究对称美，中轴线上的建筑高大雄伟，两侧的配殿则相对低矮，形成了层次分明的空间序列。

作为世界文化遗产，故宫博物院收藏了大量珍贵文物，总数超过180万件（套），涵盖书画、陶瓷、青铜器、玉器、金银器、织绣等多个门类。其中，《清明上河图》、《千里江山图》等稀世珍品更是享誉海内外。这些文物不仅是中华民族的瑰宝，也是人类文明的共同财富。

近年来，故宫博物院积极推进数字化建设，通过虚拟现实、增强现实等技术手段，让更多人能够足不出户地欣赏故宫的壮丽景象和珍贵文物。同时，故宫还推出了一系列文创产品，将传统文化与现代生活相结合，使古老的故宫文化焕发出新的生机与活力。

无论是作为历史遗迹还是文化机构，故宫都承载着传承中华文明的重要使命。它不仅是北京的一张文化名片，更是中华民族精神家园的重要象征。每年吸引着数百万游客前来参观，感受这座古老宫殿的独特魅力。
"""

# 示例用法
if __name__ == "__main__":
    EMBEDDING_MODEL_PATH = "D:/project-gs/new/vector_embeding/models/Qwen3-Embedding-0.6B"
    VECTOR_STORE_PATH = "d:/good-project/myagent1/chroma_db_hierarchical"
    
    # 初始化
    retriever = HierarchicalRetrieval()
    retriever.initialize(EMBEDDING_MODEL_PATH, VECTOR_STORE_PATH)
    
    # 添加示例文档
    retriever.add_document(SAMPLE_DOCUMENT, doc_id="palace_intro")
    print(f"\n文档添加完成！统计信息: {retriever.get_stats()}")
    
    # 测试检索
    queries = [
        "故宫有多少件文物",
        "故宫的建筑特点",
        "故宫的历史"
    ]
    
    for query in queries:
        print(f"\n=== 查询: {query} ===")
        results = retriever.retrieve(query, top_k=2)
        for i, (doc, score, meta) in enumerate(results, 1):
            print(f"{i}. 匹配分数: {score:.4f}")
            print(f"   父chunk内容:\n   {doc[:150]}...")