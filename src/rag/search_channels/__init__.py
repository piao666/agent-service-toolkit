"""Phase 6A: Search Channels — 多路检索 channel 集合。"""

from rag.search_channels.base import ChannelResult, SearchChannel, SearchHit, hit_from_retrieval_result
from rag.search_channels.official_vector import official_vector_channel
from rag.search_channels.internal_vector import internal_vector_channel
from rag.search_channels.keyword_bm25 import keyword_bm25_channel
from rag.search_channels.metadata_filter import metadata_filter_channel
from rag.search_channels.history_aware import history_aware_channel

__all__ = [
    "ChannelResult",
    "SearchChannel",
    "SearchHit",
    "hit_from_retrieval_result",
    "official_vector_channel",
    "internal_vector_channel",
    "keyword_bm25_channel",
    "metadata_filter_channel",
    "history_aware_channel",
]
