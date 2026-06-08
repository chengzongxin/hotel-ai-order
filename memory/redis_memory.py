import json
from typing import Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from redis.asyncio import Redis

from config.settings import settings

Role = Literal["human", "ai"]


class StoredMessage(TypedDict):
    role: Role
    content: str


class RedisChatMemory:
    """把多轮对话历史存进 Redis。

    Redis 很适合做短期记忆：速度快，并且可以设置过期时间。
    """

    def __init__(self, redis_url: str | None = None, ttl_seconds: int | None = None) -> None:
        self.redis = Redis.from_url(redis_url or settings.redis_url, decode_responses=True)
        self.ttl_seconds = ttl_seconds or settings.redis_ttl_seconds

    async def get_messages(self, session_id: str) -> list[StoredMessage]:
        values = await self.redis.lrange(self._key(session_id), 0, -1)
        return [json.loads(value) for value in values]

    async def get_langchain_messages(self, session_id: str) -> list[BaseMessage]:
        stored_messages = await self.get_messages(session_id)
        messages: list[BaseMessage] = []

        for item in stored_messages:
            if item["role"] == "human":
                messages.append(HumanMessage(content=item["content"]))
            else:
                messages.append(AIMessage(content=item["content"]))

        return messages

    async def append_message(self, session_id: str, role: Role, content: str) -> None:
        payload = json.dumps({"role": role, "content": content}, ensure_ascii=False)
        key = self._key(session_id)

        await self.redis.rpush(key, payload)
        await self.redis.expire(key, self.ttl_seconds)

    async def clear(self, session_id: str) -> None:
        await self.redis.delete(self._key(session_id))

    def _key(self, session_id: str) -> str:
        return f"chat:{session_id}:messages"
