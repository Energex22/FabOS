import tempfile,unittest
from pathlib import Path
from fabos_core.services.cura_integration import CuraIntegrationService
from fabos_core.services.octoprint_print import OctoPrintPrintService

class FakeManufacturing:
 def __init__(self):
  self.calls=[];self.started=False;self.temp_time=__import__("time").time()
 def octo(self,base,key,path,method='GET',body=None):
  self.calls.append((path,method,body))
  if path=="/api/server":
   return {"version":"1.10.0","safemode":False}
  if path=="/api/connection":
   return {"current":{"state":"Operational","port":"/dev/ttyUSB0","baudrate":115200}}
  if path.startswith("/api/printer?history"):
   self.temp_time+=1
   return {"state":{"flags":{"operational":True,"printing":self.started,"paused":False}},
           "temperature":{"tool0":{"actual":25,"target":230 if self.started else 0},
                          "bed":{"actual":24,"target":80 if self.started else 0},
                          "history":[{"time":self.temp_time,"tool0":{"actual":25},"bed":{"actual":24}}]}}
  if path=="/api/printer/command":
   return {}
  if path=="/api/printer":
   return {"state":{"flags":{"operational":True,"printing":self.started,"paused":False}},
           "temperature":{"tool0":{"actual":25,"target":230 if self.started else 0},
                          "bed":{"actual":24,"target":80 if self.started else 0}}}
  if path=="/api/job":
   if method=="POST" and body=={"command":"start"}:
    self.started=True;return {}
   return {"state":"Printing" if self.started else "Operational",
           "job":{"file":{"path":"FabOS_Test.gcode","name":"FabOS_Test.gcode"}}}
  if path.startswith("/api/files/local/"):
   return {}
  return {}

class FakeProductPrint:
 def upload_gcode(self,printer,path,start=False):
  return {"effectiveSelect":True,"effectivePrint":False,
          "files":{"local":{"name":"FabOS_Test.gcode","path":"FabOS_Test.gcode"}}}

class VerifiedPhysicalPrintTests(unittest.TestCase):
 def test_gcode_validator_requires_heat_motion_extrusion(self):
  with tempfile.TemporaryDirectory() as td:
   g=Path(td)/"ok.gcode"
   g.write_text("M140 S80\nM104 S230\nG28\nG1 X10 Y10 E1.2 F1200\n",encoding="utf-8")
   result=CuraIntegrationService.validate_print_gcode(g)
   self.assertTrue(result["valid"])
   bad=Path(td)/"bad.gcode";bad.write_text("G1 X10 Y10\n",encoding="utf-8")
   result=CuraIntegrationService.validate_print_gcode(bad)
   self.assertFalse(result["valid"])
   self.assertTrue(any("nozzle" in x for x in result["problems"]))

 def test_start_uses_job_api_and_waits_for_printing(self):
  m=FakeManufacturing()
  svc=OctoPrintPrintService(m,FakeProductPrint())
  printer={"octoprint_url":"http://octopi","api_key_ref":"key"}
  pre=svc.preflight(printer)
  self.assertEqual(pre["state"],"Operational")
  up=svc.upload_and_select(printer,Path("FabOS_Test.gcode"))
  self.assertEqual(up["path"],"FabOS_Test.gcode")
  started=svc.start_selected(printer,up["path"],timeout=2,verify_heaters=False)
  self.assertEqual(started["state"],"Printing")
  self.assertIn(("/api/job","POST",{"command":"start"}),m.calls)


class OfflineDetectionTests(unittest.TestCase):
 def test_closed_connection_is_offline(self):
  class Closed(FakeManufacturing):
   def octo(self,base,key,path,method='GET',body=None):
    if path=="/api/server":return {"version":"1.10"}
    if path=="/api/connection":return {"current":{"state":"Closed","port":None,"baudrate":None}}
    return super().octo(base,key,path,method,body)
  svc=OctoPrintPrintService(Closed(),FakeProductPrint())
  with self.assertRaises(RuntimeError) as cm:
   svc.preflight({"octoprint_url":"http://octopi","api_key_ref":"key"})
  self.assertIn("OFFLINE",str(cm.exception))

if __name__=="__main__":unittest.main()
