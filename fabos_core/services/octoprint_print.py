import time,socket
from urllib.error import HTTPError,URLError
from urllib.parse import quote
from pathlib import Path

class OctoPrintPrintService:
    def __init__(self,manufacturing,product_print):
        self.manufacturing=manufacturing
        self.product_print=product_print

    @staticmethod
    def _job_state(payload):
        return str((payload or {}).get("state") or "")

    @staticmethod
    def _connection_state(payload):
        current=(payload or {}).get("current") or {}
        return str(current.get("state") or ""),current

    @staticmethod
    def _temp_snapshot(printer_payload):
        temps=(printer_payload or {}).get("temperature") or {}
        tool=temps.get("tool0") or {}
        bed=temps.get("bed") or {}
        return {
            "tool_actual":tool.get("actual"),"tool_target":tool.get("target"),
            "bed_actual":bed.get("actual"),"bed_target":bed.get("target"),
            "history":temps.get("history") or []
        }

    def _call(self,base,key,path,method="GET",body=None,stage="OctoPrint request"):
        try:
            return self.manufacturing.octo(base,key,path,method,body)
        except HTTPError as exc:
            detail=""
            try:detail=exc.read().decode("utf-8","replace")
            except Exception:pass
            raise RuntimeError("%s failed: HTTP %s%s"%(stage,exc.code,(" — "+detail) if detail else ""))
        except (socket.timeout,TimeoutError) as exc:
            raise RuntimeError("%s timed out. OctoPrint is reachable, but the printer/server did not respond in time."%stage)
        except URLError as exc:
            reason=getattr(exc,"reason",exc)
            if isinstance(reason,(socket.timeout,TimeoutError)) or "timed out" in str(reason).lower():
                raise RuntimeError("%s timed out. Check that the OctoPrint computer and printer are both powered and responsive."%stage)
            raise RuntimeError("%s could not reach OctoPrint: %s"%(stage,reason))
        except Exception as exc:
            if "timed out" in str(exc).lower():
                raise RuntimeError("%s timed out. Check OctoPrint and printer power/USB connection."%stage)
            raise

    def _fresh_temperature_history(self,base,key,max_age=20):
        payload=self._call(base,key,"/api/printer?history=true&limit=3",stage="Printer response check")
        snap=self._temp_snapshot(payload)
        now=time.time()
        fresh=False
        newest=None
        for point in snap["history"]:
            try:
                stamp=float(point.get("time"))
                newest=max(newest or stamp,stamp)
            except Exception:
                pass
        if newest is not None:
            fresh=(now-newest)<=float(max_age)
        return payload,snap,fresh,newest

    def probe_printer_response(self,printer,wait_seconds=8):
        base=str(printer["octoprint_url"] or "").rstrip("/")
        key=str(printer["api_key_ref"] or "")
        connection=self._call(base,key,"/api/connection",stage="Printer connection check")
        conn_state,current=self._connection_state(connection)
        lower=conn_state.lower()
        if not conn_state or any(x in lower for x in ("closed","offline","error")):
            raise RuntimeError("Printer OFFLINE/DISCONNECTED in OctoPrint. Connection state: %s"%(conn_state or "Unknown"))
        if any(x in lower for x in ("connecting","detect","opening")):
            raise RuntimeError("OctoPrint is still connecting to the printer: %s"%conn_state)

        # A harmless M105 asks firmware for temperatures. OctoPrint's REST API only queues the
        # command, so we verify that fresh temperature history appears afterward.
        try:
            before_payload,before,before_fresh,before_time=self._fresh_temperature_history(base,key,max_age=20)
        except RuntimeError:
            before_payload={};before={};before_fresh=False;before_time=None

        self._call(base,key,"/api/printer/command","POST",{"command":"M105"},stage="Printer firmware probe")
        deadline=time.time()+float(wait_seconds)
        last=None
        while time.time()<deadline:
            time.sleep(1.0)
            try:
                payload,snap,fresh,newest=self._fresh_temperature_history(base,key,max_age=12)
                last=(payload,snap,newest)
                has_temps=(snap["tool_actual"] is not None or snap["bed_actual"] is not None)
                newer=(before_time is None or (newest is not None and newest>before_time))
                if has_temps and fresh and newer:
                    return {"connection":connection,"state":conn_state,"printer":payload,"temperatures":snap,"responding":True}
            except RuntimeError:
                pass
        # If history never advanced, don't trust Operational.
        details=""
        if last:
            snap=last[1]
            details=" Last temperatures: nozzle %s°C, bed %s°C."%(snap["tool_actual"],snap["bed_actual"])
        raise RuntimeError(
            "PRINTER NOT RESPONDING. OctoPrint reports %s, but FabOS could not confirm a fresh firmware/temperature response.%s "
            "Make sure the Vyper is powered on, its USB cable is connected, and OctoPrint can communicate with it."
            %(conn_state,details)
        )

    def preflight(self,printer):
        base=str(printer["octoprint_url"] or "").rstrip("/")
        key=str(printer["api_key_ref"] or "")
        if not base:raise ValueError("OctoPrint URL is missing.")
        if not key:raise ValueError("OctoPrint API key is missing.")

        server=self._call(base,key,"/api/server",stage="OctoPrint server check")
        try:
            user=self._call(base,key,"/api/currentuser",stage="OctoPrint API-key authorization check")
        except RuntimeError as exc:
            if "403" in str(exc):
                raise RuntimeError("OCTOPRINT API KEY FORBIDDEN: the saved API key is invalid or no longer authorized. Generate a fresh user API key in OctoPrint and update FabOS.")
            raise
        # Authentication is verified here. Effective file permissions may be inherited
        # through OctoPrint groups, so the actual upload/select endpoints remain the
        # authoritative permission check.
        probe=self.probe_printer_response(printer)
        printer_info=probe["printer"]
        job=self._call(base,key,"/api/job",stage="OctoPrint job check")
        state=self._job_state(job)
        flags=(printer_info or {}).get("state",{}).get("flags",{}) or {}
        if flags.get("printing") or flags.get("paused") or state.lower() in ("printing","paused","pausing"):
            raise RuntimeError("OctoPrint says the printer is already busy: %s"%(state or "Printing"))
        if flags and not flags.get("operational",False):
            raise RuntimeError("The printer responded, but OctoPrint does not consider it operational.")
        return {
            "server":server,"connection":probe["connection"],"printer":printer_info,
            "temperatures":probe["temperatures"],"job":job,"state":state or probe["state"] or "Operational",
            "responding":True
        }

    def upload_and_select(self,printer,gcode_path):
        try:
            response=self.product_print.upload_gcode(printer,gcode_path,start=False) or {}
        except (socket.timeout,TimeoutError) as exc:
            raise RuntimeError("G-code upload to OctoPrint timed out.")
        except URLError as exc:
            if "timed out" in str(getattr(exc,"reason",exc)).lower():
                raise RuntimeError("G-code upload to OctoPrint timed out.")
            raise RuntimeError("G-code upload failed: %s"%getattr(exc,"reason",exc))
        files=response.get("files") or {}
        local=files.get("local") or {}
        uploaded_path=(local.get("path") or local.get("name") or Path(gcode_path).name)
        base=str(printer["octoprint_url"]).rstrip("/")
        key=str(printer["api_key_ref"])
        job=self._call(base,key,"/api/job",stage="Uploaded-file verification")
        current=((job.get("job") or {}).get("file") or {}).get("path") or ((job.get("job") or {}).get("file") or {}).get("name")
        if not current or str(current).replace("\\","/") != str(uploaded_path).replace("\\","/"):
            encoded="/".join(quote(part,safe="") for part in str(uploaded_path).replace("\\","/").split("/"))
            self._call(base,key,"/api/files/local/"+encoded,"POST",
                       {"command":"select","print":False},stage="G-code file selection")
            job=self._call(base,key,"/api/job",stage="G-code selection verification")
            current=((job.get("job") or {}).get("file") or {}).get("path") or ((job.get("job") or {}).get("file") or {}).get("name")
        if not current:
            raise RuntimeError("OctoPrint received the G-code but did not select a printable file.")
        return {"upload":response,"path":str(current),"job":job}

    def _verify_heater_response(self,printer,initial_temps=None,timeout=28):
        base=str(printer["octoprint_url"]).rstrip("/")
        key=str(printer["api_key_ref"])
        initial=initial_temps or {}
        start_tool=initial.get("tool_actual")
        start_bed=initial.get("bed_actual")
        deadline=time.time()+float(timeout)
        saw_target=False
        last={}
        while time.time()<deadline:
            time.sleep(2.0)
            payload=self._call(base,key,"/api/printer",stage="Heating verification")
            snap=self._temp_snapshot(payload);last=snap
            tool_target=float(snap["tool_target"] or 0);bed_target=float(snap["bed_target"] or 0)
            tool_actual=snap["tool_actual"];bed_actual=snap["bed_actual"]
            if tool_target>0 or bed_target>0:saw_target=True
            increases=[]
            if start_tool is not None and tool_actual is not None and tool_target>float(start_tool)+5:
                increases.append(float(tool_actual)-float(start_tool))
            if start_bed is not None and bed_actual is not None and bed_target>float(start_bed)+5:
                increases.append(float(bed_actual)-float(start_bed))
            # Even a 1C rise is enough to prove heater power is doing something.
            if saw_target and any(v>=1.0 for v in increases):
                return {"confirmed":True,"temperatures":snap}
            # If already hot enough, target itself plus fresh readings is sufficient.
            if saw_target and (
                (tool_target>0 and tool_actual is not None and float(tool_actual)>=tool_target-3) or
                (bed_target>0 and bed_actual is not None and float(bed_actual)>=bed_target-3)
            ):
                return {"confirmed":True,"temperatures":snap}
        if not saw_target:
            raise RuntimeError(
                "PRINT STARTED IN OCTOPRINT, BUT NO HEATER TARGETS APPEARED. "
                "The selected G-code may not be streaming correctly to the printer."
            )
        raise RuntimeError(
            "PRINTER POWER/HEATER RESPONSE NOT CONFIRMED. OctoPrint set heater targets, but temperatures did not begin rising. "
            "Check that the Vyper's main power is ON and that the printer is actually receiving heater power. "
            "Last readings: nozzle %s/%s°C, bed %s/%s°C."
            %(last.get("tool_actual"),last.get("tool_target"),last.get("bed_actual"),last.get("bed_target"))
        )

    def preheat_together(self,printer,hotend=None,bed=None):
        hotend=float(hotend) if hotend not in (None,"") else None
        bed=float(bed) if bed not in (None,"") else None
        commands=[]
        if bed is not None and bed>0:commands.append("M140 S%s"%("%g"%bed))
        if hotend is not None and hotend>0:commands.append("M104 S%s"%("%g"%hotend))
        if not commands:return {"hotend":hotend,"bed":bed,"commands":[]}
        base=str(printer["octoprint_url"]).rstrip("/");key=str(printer["api_key_ref"])
        self._call(base,key,"/api/printer/command","POST",{"commands":commands},
                   stage="Simultaneous bed/hotend preheat")
        return {"hotend":hotend,"bed":bed,"commands":commands}

    def start_selected(self,printer,expected_path="",timeout=20,verify_heaters=True,initial_temps=None):
        base=str(printer["octoprint_url"]).rstrip("/")
        key=str(printer["api_key_ref"])
        try:
            self._call(base,key,"/api/job","POST",{"command":"start"},stage="Physical print start")
        except RuntimeError as exc:
            if "409" in str(exc):
                raise RuntimeError("OctoPrint refused to start. The printer may be disconnected, busy, or have no printable file selected.")
            raise

        deadline=time.time()+float(timeout)
        last={}
        while time.time()<deadline:
            time.sleep(0.75)
            last=self._call(base,key,"/api/job",stage="Print-start verification")
            state=str(last.get("state") or "")
            current=((last.get("job") or {}).get("file") or {}).get("path") or ((last.get("job") or {}).get("file") or {}).get("name")
            if state.lower() in ("printing","pausing","paused"):
                if expected_path and current and str(current).replace("\\","/") != str(expected_path).replace("\\","/"):
                    raise RuntimeError("OctoPrint started a different file than FabOS expected: %s"%current)
                printer_state=self._call(base,key,"/api/printer",stage="Live printer-state verification")
                temps=self._temp_snapshot(printer_state)
                heater={"confirmed":None,"temperatures":temps}
                if verify_heaters:
                    heater=self._verify_heater_response(printer,initial_temps or temps)
                return {
                    "job":last,"printer":printer_state,"state":state,"path":current,
                    "temperatures":heater.get("temperatures") or temps,
                    "heater_confirmed":heater.get("confirmed")
                }
        state=str((last or {}).get("state") or "Unknown")
        raise RuntimeError("FabOS sent START, but OctoPrint never reported Printing. Last state: %s"%state)

    def pause(self,printer):
        base=str(printer["octoprint_url"]).rstrip("/");key=str(printer["api_key_ref"])
        return self._call(base,key,"/api/job","POST",{"command":"pause","action":"pause"},stage="Pause print")

    def resume(self,printer):
        base=str(printer["octoprint_url"]).rstrip("/");key=str(printer["api_key_ref"])
        return self._call(base,key,"/api/job","POST",{"command":"pause","action":"resume"},stage="Resume print")

    def cancel(self,printer):
        base=str(printer["octoprint_url"]).rstrip("/");key=str(printer["api_key_ref"])
        return self._call(base,key,"/api/job","POST",{"command":"cancel"},stage="Cancel print")

    def prepare_and_start(self,printer,gcode_path):
        preflight=self.preflight(printer)
        uploaded=self.upload_and_select(printer,gcode_path)
        started=self.start_selected(printer,uploaded["path"],initial_temps=preflight.get("temperatures"))
        return {"preflight":preflight,"uploaded":uploaded,"started":started}
