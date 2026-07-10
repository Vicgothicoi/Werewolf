import json
import os
import glob
import ssl
import threading
import time
import urllib.error
import urllib.request

import numpy as np
import chromadb
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from metagpt.actions import Action
from metagpt.config import Config
from metagpt.const import WORKSPACE_ROOT
from metagpt.logs import logger
from werewolf_game.schema import RoleExperience

# 与本地 bge-m3 向量不兼容，切换在线 embedding 后需重建 ChromaDB collection
DEFAULT_COLLECTION_NAME = "hard_facts_v4"

_EMBED_BATCH_SIZE = 10  # text-embedding-v4 单次请求最多 10 条
_EMBED_BATCH_DELAY = 0.3  # 连续请求间隔（秒），避免触发连接限流
_embed_lock = threading.Lock()
_ssl_context = ssl.create_default_context()


def _get_embedding_config() -> tuple[str, str, str, int]:
    config = Config()
    api_base = config.embedding_api_base.rstrip("/")
    api_key = config.embedding_api_key
    model = config.embedding_model
    dimensions = int(config.embedding_dimensions)
    return api_base, api_key, model, dimensions


@retry(
    retry=retry_if_exception_type((urllib.error.URLError, RuntimeError, OSError)),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def _call_embedding_api(batch: list[str]) -> list[list[float]]:
    api_base, api_key, model, dimensions = _get_embedding_config()
    url = f"{api_base}/embeddings"
    body = json.dumps(
        {
            "model": model,
            "input": batch,
            "dimensions": dimensions,
            "encoding_format": "float",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Connection": "close",
        },
        method="POST",
    )
    try:
        with _embed_lock:
            with urllib.request.urlopen(
                req, timeout=60, context=_ssl_context
            ) as resp:
                data = json.loads(resp.read().decode())
            time.sleep(_EMBED_BATCH_DELAY)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Embedding API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Embedding API unreachable: {exc.reason}") from exc

    items = sorted(data["data"], key=lambda item: item["index"])
    return [item["embedding"] for item in items]


def _normalize_vectors(vectors: list[list[float]]) -> list[list[float]]:
    normalized = []
    for vec in vectors:
        arr = np.array(vec, dtype=float)
        norm = np.linalg.norm(arr)
        normalized.append((arr / norm).tolist() if norm > 0 else vec)
    return normalized


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """调用百炼 text-embedding-v4 对文本列表编码，返回 L2 归一化向量列表。"""
    if not texts:
        return []

    all_vectors: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[i : i + _EMBED_BATCH_SIZE]
        all_vectors.extend(_call_embedding_api(batch))
    return _normalize_vectors(all_vectors)


# ChromaDB 自定义 embedding function 接口
class _ApiEmbeddingFunction:
    def __call__(self, input: list[str]) -> list[list[float]]:
        return _embed_texts(input)


EMB_FN = _ApiEmbeddingFunction()


def _hard_facts_to_texts(hard_facts_str: str) -> list[str]:
    try:
        entries = json.loads(hard_facts_str)
    except Exception:
        entries = None

    if not isinstance(entries, list) or not entries:
        return [hard_facts_str]

    return [
        json.dumps({k: v for k, v in entry.items() if k != "TARGET"})
        for entry in entries
    ]


def _average_vectors(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    if len(vectors) == 1:
        return vectors[0]
    return np.mean(vectors, axis=0).tolist()


def embed_hard_facts_batch(hard_facts_list: list[str]) -> list[list[float]]:
    """批量编码多条 hard_facts，合并 API 请求以减少连接次数。"""
    if not hard_facts_list:
        return []

    grouped_texts: list[list[str]] = [_hard_facts_to_texts(item) for item in hard_facts_list]
    flat_texts = [text for group in grouped_texts for text in group]
    flat_vectors = _embed_texts(flat_texts)

    embeddings: list[list[float]] = []
    cursor = 0
    for texts in grouped_texts:
        group_vectors = flat_vectors[cursor : cursor + len(texts)]
        cursor += len(texts)
        embeddings.append(_average_vectors(group_vectors))
    return embeddings


def embed_hard_facts(hard_facts_str: str) -> list[float]:
    """对每个玩家的hard_facts条目独立编码，平均池化后返回与顺序无关的向量。

    Args:
        hard_facts_str (str): hard_facts的JSON字符串，格式为list of dicts

    Returns:
        list[float]: 平均池化后的embedding向量
    """
    return embed_hard_facts_batch([hard_facts_str])[0]


class AddNewExperiences(Action):
    def __init__(
        self,
        name="AddNewExperience",
        context=None,
        llm=None,
        collection_name=DEFAULT_COLLECTION_NAME,
        delete_existing=False,
    ):
        super().__init__(name, context, llm)
        chroma_client = chromadb.PersistentClient(
            path=f"{WORKSPACE_ROOT}/werewolf_game/chroma"
        )
        if delete_existing:
            try:
                chroma_client.get_collection(name=collection_name)
                chroma_client.delete_collection(name=collection_name)
                logger.info(f"existing collection {collection_name} deleted")
            except:
                pass

        self.collection = chroma_client.get_or_create_collection(
            name=collection_name,
            # HNSW 是 Hierarchical Navigable Small World 的缩写，使用余弦相似度度量
            metadata={"hnsw:space": "cosine"},
            embedding_function=EMB_FN,
        )

    def run(self, experiences: list[RoleExperience]):
        if not experiences:
            return
        for i, exp in enumerate(experiences):
            exp.id = f"{exp.profile}-{exp.name}-step{i}-round_{exp.round_id}"
        ids = [exp.id for exp in experiences]

        # 对每条经验的hard_facts独立编码后平均池化，消除玩家顺序影响
        AddNewExperiences._record_experiences_local(experiences)

        try:
            embeddings = embed_hard_facts_batch([exp.hard_facts for exp in experiences])
            documents = [exp.hard_facts for exp in experiences]  # 保留原文供调试
            metadatas = [exp.dict() for exp in experiences]

            # embeddings：手动传入向量，跳过ChromaDB自动embedding；documents仅作备份存储
            self.collection.add(
                embeddings=embeddings, documents=documents, metadatas=metadatas, ids=ids
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist experiences to ChromaDB (local JSON backup kept): %s",
                exc,
            )

    def add_from_file(self, file_path):
        with open(file_path, "r") as fl:
            lines = fl.readlines()
        experiences = [RoleExperience(**json.loads(line)) for line in lines]
        experiences = [exp for exp in experiences if len(exp.reflection) > 2]

        ids = [exp.id for exp in experiences]
        documents = [exp.reflection for exp in experiences]
        metadatas = [exp.dict() for exp in experiences]

        self.collection.add(documents=documents, metadatas=metadatas, ids=ids)

    @staticmethod
    def _record_experiences_local(experiences: list[RoleExperience]):
        round_id = experiences[0].round_id
        version = experiences[0].version
        version = "test" if not version else version
        experiences = [exp.json() for exp in experiences]
        experience_folder = WORKSPACE_ROOT / f"werewolf_game/experiences/{version}"
        if not os.path.exists(experience_folder):
            os.makedirs(experience_folder)
        save_path = f"{experience_folder}/{round_id}.json"
        with open(save_path, "a") as fl:
            fl.write("\n".join(experiences))
            fl.write("\n")
        logger.info(f"experiences saved to {save_path}")


class RetrieveExperiences(Action):

    def __init__(
        self,
        name="RetrieveExperiences",
        context=None,
        llm=None,
        collection_name=DEFAULT_COLLECTION_NAME,
    ):
        super().__init__(name, context, llm)
        chroma_client = chromadb.PersistentClient(
            path=f"{WORKSPACE_ROOT}/werewolf_game/chroma"
        )
        try:
            # 新增时是get_or_create_collection()；检索时当然不能创建数据库
            self.collection = chroma_client.get_collection(
                name=collection_name,
                embedding_function=EMB_FN,
            )
            self.has_experiences = True
        except:
            logger.warning(f"No experience pool {collection_name}")
            self.has_experiences = False

    def run(
        self,
        query: str,
        profile: str,
        topk: int = 5,
        excluded_version: str = "",
        verbose: bool = False,
    ) -> str:
        """
        Args:
            query (str): 用当前的hard_facts作为query去检索过去相似局面的经验
            profile (str): 角色身份，只检索同角色的经验
            topk (int, optional): 最终返回的经验条数上限. Defaults to 5.
            excluded_version (str): 消融实验用，排除指定版本的经验
            verbose (bool): 是否打印距离信息

        Returns:
            str: 格式化后的历史经验JSON字符串，无有效经验时返回空字符串
        """
        if not self.has_experiences or len(query) <= 2:  # not "" or not '""'
            return ""

        # 过滤器，只使用相同角色的经验
        filters = {"profile": profile}
        ### 消融实验逻辑 ###
        if profile == "Werewolf":  # 狼人作为基线，不用经验
            logger.warning("Disable werewolves' experiences")
            return ""
        if excluded_version:
            # 运算符 $and：同时满足；$ne：不等于
            filters = {
                "$and": [{"profile": profile}, {"version": {"$ne": excluded_version}}]
            }

        # 对query的hard_facts独立编码后平均池化，与存储时保持一致
        try:
            query_embedding = embed_hard_facts(query)
        except Exception as exc:
            logger.warning("Failed to embed query for experience retrieval: %s", exc)
            return ""

        # 多取候选，留给后续两层过滤筛选
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=topk * 3,
            where=filters,
        )

        logger.info(f"retrieve {profile}'s experiences")
        # 因为只传送了1个query，所以results["metadatas"][0]返回所有查询结果
        candidates = [RoleExperience(**res) for res in results["metadatas"][0]]
        distances = results["distances"][0]

        if verbose:
            print(*candidates, sep="\n\n")
            print(distances)

        # 过滤1：相似度阈值，cosine距离越小越相似，距离过大说明局面差异太大，丢弃以避免负迁移
        DISTANCE_THRESHOLD = 0.3
        candidates = [
            exp for exp, dist in zip(candidates, distances) if dist < DISTANCE_THRESHOLD
        ]
        logger.info(f"after distance filtering: {len(candidates)} candidates remain")

        # 过滤2：outcome-aware reranking，赢的经验优先，保留少量输的经验作为反面教材
        won = [exp for exp in candidates if exp.outcome == "won"]
        lost = [exp for exp in candidates if exp.outcome == "lost"]
        # 赢的经验占大头，输的经验最多保留1条作为反面参考
        past_experiences = (won + lost[:1])[:topk]

        if not past_experiences:
            logger.info("no sufficiently similar experiences found, skipping")
            return ""

        template = """
        {
            "Situation __i__": "__situation__"
            ,"Moderator's instruction": "__instruction__"
            ,"Your action or speech during that time": "__response__"
            ,"Reality": "In fact, it turned out the true roles are __game_step__",
            ,"Outcome": "You __outcome__ in the end"
        }
        """
        past_experiences = [
            (
                template.replace("__i__", str(i))
                .replace("__situation__", exp.reflection)
                .replace("__instruction__", exp.instruction)
                .replace("__response__", exp.response)
                .replace(
                    "__game_step__",
                    exp.game_setup.replace("0 | Game setup:\n", "").replace("\n", " "),
                )
                .replace("__outcome__", exp.outcome)
            )
            for i, exp in enumerate(past_experiences)
        ]
        print(*past_experiences, sep="\n")
        logger.info("retrieval done")

        return json.dumps(past_experiences)


# FIXME: below are some utility functions, should be moved to appropriate places
# 删数据库
def delete_collection(name):
    chroma_client = chromadb.PersistentClient(
        path=f"{WORKSPACE_ROOT}/werewolf_game/chroma"
    )
    chroma_client.delete_collection(name=name)


# 从文件写入数据
def add_file_batch(folder, **kwargs):
    action = AddNewExperiences(**kwargs)
    file_paths = glob.glob(str(folder) + "/*")
    for fp in file_paths:
        print(fp)
        action.add_from_file(fp)


# 改数据库名
def modify_collection():
    chroma_client = chromadb.PersistentClient(
        path=f"{WORKSPACE_ROOT}/werewolf_game/chroma"
    )
    collection = chroma_client.get_collection(name=DEFAULT_COLLECTION_NAME)
    updated_name = DEFAULT_COLLECTION_NAME + "_backup"
    collection.modify(name=updated_name)
    try:
        chroma_client.get_collection(name=DEFAULT_COLLECTION_NAME)
    except:
        logger.info(f"collection {DEFAULT_COLLECTION_NAME} not found")
    updated_collection = chroma_client.get_collection(name=updated_name)
    print(updated_collection.get()["documents"][-5:])


# if __name__ == "__main__":
# delete_collection(name="test")
# add_file_batch(WORKSPACE_ROOT / 'werewolf_game/experiences', collection_name=DEFAULT_COLLECTION_NAME, delete_existing=True)
# modify_collection()
