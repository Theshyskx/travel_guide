import os
import torch
import chromadb
from sentence_transformers import SentenceTransformer
from llama_index.core import SimpleDirectoryReader, VectorStoreIndex, Settings, StorageContext
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.node_parser import SentenceSplitter
from src.utils.logger import logger, log_rag_query
from src.config.settings import config

class CustomEmbedding(BaseEmbedding):
    def __init__(self, model):
        super().__init__()
        self._model = model
    
    def _get_text_embedding(self, text: str) -> list[float]:
        return self._model.encode(
            text,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_tensor=False
        ).tolist()
    
    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return [self._get_text_embedding(text) for text in texts]
    
    def _get_query_embedding(self, query: str) -> list[float]:
        return self._get_text_embedding(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

class RAGService:
    def __init__(self):
        self.chroma_client = None
        self.collection = None
        self.vector_store = None
        self.model = None
        self.index = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        # 从配置中获取模型路径
        self.model_path = config.EMBEDDING_MODEL_PATH
        
    def initialize(self):
        """初始化模型和向量数据库"""
        logger.info(f"正在使用设备: {self.device}")
        
        # 1. 初始化 Chroma 持久化客户端
        persistence_path = config.VECTOR_STORE_PATH
        logger.info(f"正在初始化 Chroma 持久化客户端，路径: {persistence_path}")
        self.chroma_client = chromadb.PersistentClient(path=persistence_path)
        self.collection = self.chroma_client.get_or_create_collection("travel_knowledge")
        self.vector_store = ChromaVectorStore(chroma_collection=self.collection)
        
        # 2. 加载模型
        logger.info(f"正在加载本地模型: {self.model_path}")
        self.model = SentenceTransformer(
            self.model_path,
            device=self.device,
            trust_remote_code=True
        )
        if self.device == "cuda":
            self.model.half()
            
        # 3. 配置 LlamaIndex
        Settings.embed_model = CustomEmbedding(self.model)
        Settings.llm = None  # 仅用于检索
        
        # 4. 如果集合中已有数据，直接加载索引
        try:
            collection_count = self.collection.count()
            logger.info(f"当前集合 '{self.collection.name}' 中的向量数量: {collection_count}")
            if collection_count > 0:
                logger.info("检测到已有向量数据，正在从向量数据库加载索引...")
                self.index = VectorStoreIndex.from_vector_store(
                    self.vector_store,
                    embed_model=Settings.embed_model
                )
                logger.info(f"索引加载完成，共加载 {collection_count} 个向量")
            else:
                logger.info("集合为空，等待后续向量化")
        except Exception as e:
            logger.error(f"加载已有索引失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        logger.info("RAG 服务初始化完成")

    def vectorize_file(self, file_path: str, chunk_size: int = 256, chunk_overlap: int = 25):
        """对文件进行向量化并创建索引"""
        if not os.path.exists(file_path):
            logger.error(f"文件不存在: {file_path}")
            return False
            
        # 检查是否已经有索引数据
        try:
            current_count = self.collection.count()
            logger.info(f"正在检查向量数据库状态... 当前向量数量: {current_count}")
            
            if current_count > 0:
                if self.index:
                    logger.info(f"【跳过向量化】检测到集合中已有 {current_count} 个向量，且索引已加载。")
                    return True
                else:
                    logger.info(f"检测到集合中已有 {current_count} 个向量，但索引未加载，尝试重新加载索引...")
                    try:
                        self.index = VectorStoreIndex.from_vector_store(
                            self.vector_store,
                            embed_model=Settings.embed_model
                        )
                        logger.info("【跳过向量化】索引重新加载成功。")
                        return True
                    except Exception as e:
                        logger.error(f"重新加载索引失败: {e}，将尝试重新向量化")
            else:
                logger.info("集合为空，准备开始向量化...")
        except Exception as e:
            logger.error(f"检查集合数量失败: {e}")
            
        logger.info(f"正在对文件进行向量化: {file_path}")
        reader = SimpleDirectoryReader(input_files=[file_path])
        documents = reader.load_data()
        
        splitter = SentenceSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
        
        nodes = splitter.get_nodes_from_documents(documents)
        
        # 使用 StorageContext 明确指定 vector_store，确保 LlamaIndex 正确写入
        storage_context = StorageContext.from_defaults(vector_store=self.vector_store)
        
        self.index = VectorStoreIndex(
            nodes,
            storage_context=storage_context,
            embed_model=Settings.embed_model
        )
        
        # 强制检查一次持久化状态
        final_count = self.collection.count()
        logger.info(f"向量化完成，文档数量: {len(documents)}, 节点数量: {len(nodes)}")
        logger.info(f"【持久化校验】当前集合向量总数: {final_count}")
        
        return True

    def query(self, query_text: str, top_k: int = 5):
        """执行检索"""
        if not self.index:
            logger.warning("索引未初始化，请先进行向量化")
            return "未找到匹配答案"
            
        query_engine = self.index.as_query_engine(llm=None, similarity_top_k=top_k)
        response = query_engine.query(query_text)
        
        answer = ""
        if response.source_nodes:
            # 获取最相关的节点内容
            top_node = response.source_nodes[0]
            answer = top_node.text
            if len(answer) > 800:
                answer = answer[:800] + "..."
                
        # 记录日志
        log_rag_query(query_text, answer if answer else "未找到匹配答案")
        
        return answer if answer else "未找到匹配答案"

# 单例模式
rag_service = RAGService()
