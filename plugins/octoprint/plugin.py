import json
from urllib.request import Request,urlopen
from fabos_core.plugins.base import FabOSPlugin,PluginMetadata
class Plugin(FabOSPlugin):
    metadata=PluginMetadata('octoprint','OctoPrint Connect','0.1.0')
    def start(self,context): self.context=context
    def stop(self): self.context=None
    def get_job(self,url,key):
        r=Request(url.rstrip('/')+'/api/job',headers={'X-Api-Key':key,'Accept':'application/json'})
        with urlopen(r,timeout=10) as x:return json.loads(x.read().decode())
    def command(self,url,key,command,action=None):
        b={'command':command}; b.update({'action':action} if action else {}); r=Request(url.rstrip('/')+'/api/job',data=json.dumps(b).encode(),method='POST',headers={'X-Api-Key':key,'Content-Type':'application/json'}); urlopen(r,timeout=10).close()
def create_plugin():return Plugin()
