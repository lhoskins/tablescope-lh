# redash/services/redis_permission_cache.py

"""
Redis-based permission cache service for performance optimization.

This service provides a Redis-backed caching layer for user permissions,
offering faster lookups than database-based caching. It gracefully falls
back to database caching if Redis is unavailable.
"""

import json
import logging
from typing import Optional, List, Set

logger = logging.getLogger(__name__)

# Try to import Redis, but make it optional
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis library not available. Permission caching will use database fallback.")


class RedisPermissionCache:
    """
    Redis-based permission cache service.
    
    Provides high-performance caching of user permissions using Redis.
    Falls back gracefully to database caching if Redis is unavailable.
    """
    
    def __init__(self, redis_url=None, enabled=True):
        """
        Initialize Redis permission cache.
        
        Args:
            redis_url (str, optional): Redis connection URL (e.g., 'redis://localhost:6379/0')
            enabled (bool): Whether caching is enabled (default: True)
        """
        self.enabled = enabled and REDIS_AVAILABLE
        self.redis_client = None
        
        if self.enabled and redis_url:
            try:
                self.redis_client = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2
                )
                # Test connection
                self.redis_client.ping()
                logger.info("Redis permission cache initialized successfully: %s", redis_url)
            except Exception as e:
                logger.warning("Failed to connect to Redis: %s. Falling back to database cache.", e)
                self.redis_client = None
                self.enabled = False
    
    def is_available(self):
        """
        Check if Redis cache is available.
        
        Returns:
            bool: True if Redis is connected and available
        """
        if not self.enabled or not self.redis_client:
            return False
        
        try:
            self.redis_client.ping()
            return True
        except Exception:
            return False
    
    def _make_cache_key(self, user_id, permission=None, resource_type=None, resource_id=None):
        """
        Generate cache key for permission.
        
        Args:
            user_id (int): User ID
            permission (str, optional): Permission string
            resource_type (str, optional): Resource type
            resource_id (int, optional): Resource ID
            
        Returns:
            str: Cache key
        """
        if permission:
            if resource_type and resource_id:
                return "user:{}:perm:{}:{}:{}".format(user_id, permission, resource_type, resource_id)
            return "user:{}:perm:{}".format(user_id, permission)
        return "user:{}:permissions".format(user_id)
    
    def get_cached_permissions(self, user_id, org_id):
        """
        Get all cached permissions for a user.
        
        Args:
            user_id (int): User ID
            org_id (int): Organization ID
            
        Returns:
            set: Set of permission strings, or None if not cached
        """
        if not self.is_available():
            return None
        
        try:
            cache_key = "user:{}:permissions:{}".format(user_id, org_id)
            cached_data = self.redis_client.get(cache_key)
            
            if cached_data:
                permissions = json.loads(cached_data)
                logger.debug("Redis cache hit for user %s permissions", user_id)
                return set(permissions)
            
            return None
        except Exception as e:
            logger.warning("Error getting cached permissions from Redis: %s", e)
            return None
    
    def set_cached_permissions(self, user_id, org_id, permissions, ttl_seconds=300):
        """
        Cache all permissions for a user with TTL.
        
        Args:
            user_id (int): User ID
            org_id (int): Organization ID
            permissions (set or list): Set or list of permission strings
            ttl_seconds (int): Time to live in seconds (default: 300 = 5 minutes)
            
        Returns:
            bool: True if successfully cached
        """
        if not self.is_available():
            return False
        
        try:
            cache_key = "user:{}:permissions:{}".format(user_id, org_id)
            permissions_list = list(permissions) if isinstance(permissions, set) else permissions
            
            # Use SETEX to set value with expiration atomically
            self.redis_client.setex(
                cache_key,
                ttl_seconds,
                json.dumps(permissions_list)
            )
            
            logger.debug("Cached %s permissions for user %s with TTL %ss", len(permissions_list), user_id, ttl_seconds)
            return True
        except Exception as e:
            logger.warning("Error caching permissions in Redis: %s", e)
            return False
    
    def get_cached_permission(self, user_id, permission, resource_type=None, resource_id=None):
        """
        Get a specific cached permission.
        
        Args:
            user_id (int): User ID
            permission (str): Permission string
            resource_type (str, optional): Resource type
            resource_id (int, optional): Resource ID
            
        Returns:
            bool: True if permission is cached, None if not cached
        """
        if not self.is_available():
            return None
        
        try:
            cache_key = self._make_cache_key(user_id, permission, resource_type, resource_id)
            result = self.redis_client.get(cache_key)
            
            if result is not None:
                logger.debug("Redis cache hit for permission %s", permission)
                return result == "1"
            
            return None
        except Exception as e:
            logger.warning("Error getting cached permission from Redis: %s", e)
            return None
    
    def set_cached_permission(self, user_id, permission, org_id, has_permission=True,
                             resource_type=None, resource_id=None, ttl_seconds=300):
        """
        Cache a specific permission with TTL.
        
        Args:
            user_id (int): User ID
            permission (str): Permission string
            org_id (int): Organization ID
            has_permission (bool): Whether user has the permission
            resource_type (str, optional): Resource type
            resource_id (int, optional): Resource ID
            ttl_seconds (int): Time to live in seconds (default: 300 = 5 minutes)
            
        Returns:
            bool: True if successfully cached
        """
        if not self.is_available():
            return False
        
        try:
            cache_key = self._make_cache_key(user_id, permission, resource_type, resource_id)
            
            # Use SETEX to set value with expiration atomically
            self.redis_client.setex(
                cache_key,
                ttl_seconds,
                "1" if has_permission else "0"
            )
            
            logger.debug("Cached permission %s for user %s with TTL %ss", permission, user_id, ttl_seconds)
            return True
        except Exception as e:
            logger.warning("Error caching permission in Redis: %s", e)
            return False
    
    def invalidate_cache(self, user_id=None, org_id=None, pattern=None):
        """
        Invalidate cached permissions using Redis DEL.
        
        Args:
            user_id (int, optional): User ID to invalidate cache for
            org_id (int, optional): Organization ID to invalidate
            pattern (str, optional): Custom pattern to match keys
            
        Returns:
            int: Number of keys deleted
        """
        if not self.is_available():
            return 0
        
        try:
            deleted_count = 0
            
            if pattern:
                # Use custom pattern
                keys = self.redis_client.keys(pattern)
            elif user_id and org_id:
                # Invalidate all permissions for user in org
                keys = self.redis_client.keys("user:{}:*:{}".format(user_id, org_id))
                keys.extend(self.redis_client.keys("user:{}:perm:*".format(user_id)))
            elif user_id:
                # Invalidate all permissions for user
                keys = self.redis_client.keys("user:{}:*".format(user_id))
            elif org_id:
                # Invalidate all permissions for org (expensive operation)
                keys = self.redis_client.keys("user:*:permissions:{}".format(org_id))
            else:
                logger.warning("No invalidation criteria provided")
                return 0
            
            if keys:
                deleted_count = self.redis_client.delete(*keys)
                logger.info("Invalidated %s Redis cache entries", deleted_count)
            
            return deleted_count
        except Exception as e:
            logger.error("Error invalidating Redis cache: %s", e)
            return 0
    
    def invalidate_user_cache(self, user_id):
        """
        Invalidate all cached permissions for a user.
        
        Args:
            user_id (int): User ID
            
        Returns:
            int: Number of keys deleted
        """
        return self.invalidate_cache(user_id=user_id)
    
    def invalidate_org_cache(self, org_id):
        """
        Invalidate all cached permissions for an organization.
        
        Args:
            org_id (int): Organization ID
            
        Returns:
            int: Number of keys deleted
        """
        return self.invalidate_cache(org_id=org_id)
    
    def invalidate_resource_cache(self, resource_type, resource_id):
        """
        Invalidate all cached permissions for a specific resource.
        
        Args:
            resource_type (str): Resource type
            resource_id (int): Resource ID
            
        Returns:
            int: Number of keys deleted
        """
        pattern = "user:*:perm:*:{}:{}".format(resource_type, resource_id)
        return self.invalidate_cache(pattern=pattern)
    
    def clear_all(self):
        """
        Clear all permission cache entries (use with caution).
        
        Returns:
            int: Number of keys deleted
        """
        if not self.is_available():
            return 0
        
        try:
            keys = self.redis_client.keys("user:*:perm*")
            if keys:
                deleted_count = self.redis_client.delete(*keys)
                logger.warning("Cleared all permission cache: %s entries", deleted_count)
                return deleted_count
            return 0
        except Exception as e:
            logger.error("Error clearing Redis cache: %s", e)
            return 0


# Global instance (will be initialized by application)
_redis_cache_instance = None


def get_redis_cache():
    """
    Get the global Redis cache instance.
    
    Returns:
        RedisPermissionCache: Global cache instance
    """
    global _redis_cache_instance
    
    if _redis_cache_instance is None:
        # Initialize with default settings (will be reconfigured by app)
        _redis_cache_instance = RedisPermissionCache(enabled=False)
    
    return _redis_cache_instance


def initialize_redis_cache(redis_url=None, enabled=True):
    """
    Initialize the global Redis cache instance.
    
    This should be called during application startup.
    
    Args:
        redis_url (str, optional): Redis connection URL
        enabled (bool): Whether caching is enabled
        
    Returns:
        RedisPermissionCache: Initialized cache instance
    """
    global _redis_cache_instance
    
    _redis_cache_instance = RedisPermissionCache(redis_url=redis_url, enabled=enabled)
    return _redis_cache_instance
