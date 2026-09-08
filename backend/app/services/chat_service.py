class ChatService:
    """Persistence boundary shared by REST and a future realtime transport."""
    def __init__(self, db):
        self.db = db

    def list(self, trip_id, page):
        return self.db.select("group_messages", {"trip_id": trip_id}, **page)

    def send(self, trip_id, sender_id, content):
        return self.db.insert("group_messages", {"trip_id": trip_id, "sender_id": sender_id, "content": content})
