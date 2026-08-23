import json
class SqliteEventStore:
    def __init__(self,db): self.db=db
    def append(self,e):
        with self.db.connect() as c:
            c.execute('INSERT INTO domain_events(id,event_type,aggregate_type,aggregate_id,payload_json,occurred_at) VALUES(?,?,?,?,?,?)',(e.id,e.type,e.aggregate_type,e.aggregate_id,json.dumps(e.payload,sort_keys=True),e.occurred_at)); c.commit()
