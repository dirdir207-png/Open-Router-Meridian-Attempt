def post_worker_init(worker):
    from app import init_db

    init_db()
