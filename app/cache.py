"""轻量级内存缓存模块"""

import time
import asyncio
from functools import wraps
from app.config import CACHE_DEFAULT_TTL, MANUAL_UPDATE_COOLDOWN as MANUAL_COOLDOWN

_cache = {}


def get(key):
    """获取缓存值，过期返回 None"""
    entry = _cache.get(key)
    if entry is None:
        return None
    if time.time() > entry["expires"]:
        del _cache[key]
        return None
    return entry["value"]


def set(key, value, ttl=CACHE_DEFAULT_TTL):
    """设置缓存值"""
    _cache[key] = {
        "value": value,
        "expires": time.time() + ttl,
    }


def delete(key):
    """删除缓存"""
    _cache.pop(key, None)


def clear():
    """清空全部缓存"""
    _cache.clear()


def cached(ttl=60):
    """缓存装饰器（支持同步和异步函数）

    用法：
        @cached(ttl=300)
        def sync_func(arg1, arg2):
            ...

        @cached(ttl=300)
        async def async_func(arg1, arg2):
            ...
    """
    def decorator(func):
        is_coro = asyncio.iscoroutinefunction(func)

        @wraps(func)
        def wrapper(*args, **kwargs):
            key = f"{func.__name__}:{args}:{sorted(kwargs.items())}"
            result = get(key)
            if result is not None:
                return result
            result = func(*args, **kwargs)
            set(key, result, ttl)
            return result

        if is_coro:
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                key = f"{func.__name__}:{args}:{sorted(kwargs.items())}"
                result = get(key)
                if result is not None:
                    return result
                result = await func(*args, **kwargs)
                set(key, result, ttl)
                return result
            return async_wrapper

        return wrapper
    return decorator


def invalidate_by_prefix(prefix):
    """按前缀批量失效缓存（如更新数据后失效相关统计缓存）"""
    keys_to_delete = [k for k in _cache if k.startswith(prefix)]
    for k in keys_to_delete:
        del _cache[k]


def stats():
    """缓存统计信息"""
    return {
        "total_entries": len(_cache),
        "keys": list(_cache.keys()),
    }


# ============================================================
# 全局手动更新冷却（服务器内存级别，重启后重置）
# ============================================================
MANUAL_UPDATE_COOLDOWN = MANUAL_COOLDOWN  # 冷却时间（秒）
_manual_update_timestamp = 0  # 最后一次手动更新时间戳


def get_manual_update_cooldown():
    """获取手动更新冷却剩余秒数（0 表示可更新）"""
    global _manual_update_timestamp
    elapsed = time.time() - _manual_update_timestamp
    remaining = max(0, MANUAL_UPDATE_COOLDOWN - elapsed)
    return int(remaining)


def set_manual_update_timestamp():
    """记录手动更新时间"""
    global _manual_update_timestamp
    _manual_update_timestamp = time.time()


def can_manual_update():
    """检查是否允许手动更新"""
    return get_manual_update_cooldown() == 0