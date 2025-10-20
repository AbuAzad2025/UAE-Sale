"""
Redis Configuration Helper
تهيئة Redis للنظام
"""
import redis
from flask import Flask


def init_redis(app: Flask):
    """Initialize Redis connection"""
    redis_url = app.config.get('REDIS_URL', 'redis://localhost:6379/0')
    
    try:
        # Create Redis client
        redis_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True
        )
        
        # Test connection
        redis_client.ping()
        
        app.logger.info(f"Redis connected: {redis_url}")
        app.redis = redis_client
        
        return redis_client
        
    except redis.ConnectionError as e:
        app.logger.warning(f"⚠️  Redis connection failed: {e}")
        app.logger.warning("   System will work without Redis, but caching will use memory")
        app.redis = None
        
        return None
    except Exception as e:
        app.logger.error(f"❌ Redis initialization error: {e}")
        app.redis = None
        
        return None


def get_redis_client(app: Flask = None):
    """Get Redis client instance"""
    from flask import current_app
    
    if app is None:
        app = current_app
    
    return getattr(app, 'redis', None)


def test_redis_connection():
    """Test Redis connection"""
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    
    try:
        client = redis.from_url(redis_url, decode_responses=True)
        client.ping()
        
        print(f"✅ Redis is accessible at: {redis_url}")
        
        # Test set/get
        client.set('test_key', 'test_value', ex=60)
        value = client.get('test_key')
        
        if value == 'test_value':
            print("✅ Redis read/write working correctly")
        else:
            print("⚠️  Redis read/write issue")
        
        # Show info
        info = client.info('server')
        print(f"📊 Redis version: {info.get('redis_version', 'unknown')}")
        
        return True
        
    except redis.ConnectionError:
        print(f"❌ Cannot connect to Redis at: {redis_url}")
        print("   Make sure Redis is running:")
        print("   - Windows: Download from https://github.com/microsoftarchive/redis/releases")
        print("   - Linux: sudo systemctl start redis")
        print("   - Docker: docker run -d -p 6379:6379 redis:7-alpine")
        
        return False
    except Exception as e:
        print(f"❌ Redis error: {e}")
        return False


if __name__ == '__main__':
    print("🔍 Testing Redis connection...")
    print("=" * 50)
    test_redis_connection()

