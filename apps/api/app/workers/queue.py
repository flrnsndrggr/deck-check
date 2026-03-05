from redis import Redis
from rq import Queue

from app.core.config import settings

redis_conn = Redis.from_url(
    settings.redis_url,
    socket_connect_timeout=1,
    socket_timeout=1,
    health_check_interval=30,
)
sim_queue = Queue("sim", connection=redis_conn, default_timeout=3600)
