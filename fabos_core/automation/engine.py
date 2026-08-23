import json
class AutomationEngine:
    def __init__(self,db): self.db=db; self.actions={}
    def register_action(self,n,h): self.actions[n]=h
    @staticmethod
    def _matches(payload,conditions): return all(payload.get(k)==v for k,v in conditions.items())
    def handle(self,e):
        with self.db.connect() as c: rows=c.execute('SELECT * FROM automation_rules WHERE enabled=1 AND trigger_event=?',(e.type,)).fetchall()
        for r in rows:
            if not self._matches(e.payload,json.loads(r['conditions_json'] or '{}')): continue
            for a in json.loads(r['actions_json'] or '[]'):
                h=self.actions.get(a.get('type'))
                if h: h(e,a)
