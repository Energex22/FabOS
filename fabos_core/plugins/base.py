from abc import ABC,abstractmethod
from dataclasses import dataclass
@dataclass(frozen=True)
class PluginMetadata: id:str; name:str; version:str; minimum_core_version:str='0.1.0'
class FabOSPlugin(ABC):
    metadata:PluginMetadata
    @abstractmethod
    def start(self,context): raise NotImplementedError
    @abstractmethod
    def stop(self): raise NotImplementedError
    def health(self): return {'status':'ok'}
