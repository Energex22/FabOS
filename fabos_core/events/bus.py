from dataclasses import dataclass,field
from datetime import datetime
import uuid
@dataclass(frozen=True)
class Event:
    type:str; aggregate_type:str=''; aggregate_id:str=''; payload:dict=field(default_factory=dict); id:str=field(default_factory=lambda:str(uuid.uuid4())); occurred_at:str=field(default_factory=lambda:datetime.utcnow().isoformat()+'Z')
class EventBus:
    def __init__(self): self.handlers={}
    def subscribe(self,t,h): self.handlers.setdefault(t,[]).append(h)
    def publish(self,e):
        for h in self.handlers.get(e.type,[])+self.handlers.get('*',[]): h(e)
