"""Run separately from the API; same application package and schema."""
import platform
from rq import Worker
from rq.worker import SimpleWorker
from rq.serializers import JSONSerializer
from backend.inference import redis_connection
from backend.jobs import recover_jobs

if __name__ == "__main__":
    recover_jobs()
    # RQ's default worker forks a work horse. On macOS, forking after Objective-C
    # runtime initialization can abort with objc_initializeAfterForkError. Use
    # the synchronous no-fork worker for local macOS development; retain process
    # isolation on Linux deployments.
    worker_type = SimpleWorker if platform.system() == "Darwin" else Worker
    worker_type(["watermelon"], connection=redis_connection(), serializer=JSONSerializer).work(with_scheduler=True)
