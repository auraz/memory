from app.approvals.queue import ApprovalQueue
from app.storage.db import connect, init_db


def test_approval_queue_lifecycle(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)

    with connect(db_path) as conn:
        queue = ApprovalQueue(conn)
        action_id = queue.create("memory.write", {"text": "hello"})

        pending = queue.list_pending()
        assert len(pending) == 1
        assert pending[0].id == action_id
        assert pending[0].payload == {"text": "hello"}

        queue.mark(action_id, "approved")

        assert queue.list_pending() == []

