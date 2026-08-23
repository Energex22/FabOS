from pathlib import Path
import time
import threading
import zipfile,configparser,io,os,shutil,subprocess,re,math

class CuraIntegrationService:
    VYPER_GLOBAL = {
        "machine_width": "245",
        "machine_depth": "245",
        "machine_height": "260",
        "machine_center_is_zero": "false",
        "machine_heated_bed": "true",
        "machine_heated_build_volume": "false",
        "machine_extruder_count": "1",
        "machine_gcode_flavor": "RepRap (Marlin/Sprinter)",
        # Safety fallback only. A machine_start_gcode / machine_end_gcode
        # contained in the selected Cura profile overrides these values.
        # FabOS does not inject an edge purge line.
        "machine_start_gcode": (
            "G21 ; millimeters\n"
            "G90 ; absolute XYZ\n"
            "M82 ; absolute extrusion\n"
            "G28 ; home all axes\n"
            "G92 E0 ; reset extruder"
        ),
        "machine_end_gcode": (
            "M104 S0\n"
            "M140 S0\n"
            "M107\n"
            "G91\n"
            "G1 E-2 F2700\n"
            "G1 Z10 F2400\n"
            "G90\n"
            "G1 X10 Y220 F3000\n"
            "M84"
        ),
    }
    VYPER_EXTRUDER = {
        "machine_nozzle_size": "0.4",
        "machine_nozzle_tip_outer_diameter": "1.0",
        "machine_nozzle_head_distance": "3",
        "machine_nozzle_expansion_angle": "45",
        "machine_nozzle_id": "unknown",
        "machine_nozzle_offset_x": "0",
        "machine_nozzle_offset_y": "0",
        "material_diameter": "1.75",
        "machine_extruder_start_code": "",
        "machine_extruder_end_code": "",
    }

    def __init__(self, data_dir):
        self.data_dir=Path(data_dir)

    def install_profile(self, source_path):
        source=Path(source_path)
        if not source.exists():raise FileNotFoundError(source)
        folder=self.data_dir/"Cura Profiles"
        folder.mkdir(parents=True,exist_ok=True)
        target=folder/source.name
        if not target.exists() or target.read_bytes()!=source.read_bytes():
            shutil.copy2(str(source),str(target))
        return target

    @staticmethod
    def _is_engine(path):
        path=Path(path)
        return path.is_file() and path.name.lower() in ("curaengine.exe","curaengine")

    @staticmethod
    def _valid_resources(path):
        path=Path(path)
        fdm=path/"definitions"/"fdmprinter.def.json"
        ext=path/"extruders"/"fdmextruder.def.json"
        return (fdm.exists() and ext.exists(),fdm,ext)

    def _engine_candidates_from(self,path):
        p=Path(path)
        candidates=[]
        if self._is_engine(p):
            candidates.append(p)
            base=p.parent
        elif p.is_dir():
            base=p
            candidates += [base/"CuraEngine.exe",base/"CuraEngine"]
        else:
            base=p.parent
        # Cura Windows distributions have used several layouts.
        for rel in (
            Path("bin")/"CuraEngine.exe",
            Path("bin")/"CuraEngine",
            Path("lib")/"cura"/"CuraEngine.exe",
            Path("lib")/"cura"/"CuraEngine",
        ):
            candidates.append(base/rel)
        # Bounded recursive fallback, intentionally limited to CuraEngine only.
        if base.exists() and base.is_dir():
            try:
                for candidate in base.rglob("CuraEngine.exe"):
                    try:
                        depth=len(candidate.relative_to(base).parts)
                    except Exception:
                        depth=99
                    if depth<=4:
                        candidates.append(candidate)
            except Exception:
                pass
        unique=[]
        seen=set()
        for c in candidates:
            key=str(c).lower()
            if key not in seen:
                seen.add(key);unique.append(c)
        return unique

    def find_cura(self, configured=""):
        candidates=[]
        if configured:
            candidates.extend(self._engine_candidates_from(configured))
        env=os.environ.get("CURAENGINE_PATH")
        if env:
            candidates.extend(self._engine_candidates_from(env))
        install_env=os.environ.get("CURA_INSTALL_DIR")
        if install_env:
            candidates.extend(self._engine_candidates_from(install_env))
        standard=[
            Path(r"C:\Program Files\Ultimaker Cura 4.13.1"),
            Path(r"C:\Program Files\Ultimaker Cura 4.13"),
            Path(r"C:\Program Files (x86)\Ultimaker Cura 4.13.1"),
            Path(r"D:\Programs\Ultimaker Cura 4.13.1"),
        ]
        for folder in standard:
            candidates.extend(self._engine_candidates_from(folder))
        for c in candidates:
            if self._is_engine(c):
                return c
        found=shutil.which("CuraEngine.exe") or shutil.which("CuraEngine")
        return Path(found) if found else None

    def find_cura_gui(self, configured_engine=""):
        """Find the Cura desktop GUI associated with a CuraEngine/install."""
        candidates=[]
        engine=self.find_cura(configured_engine)
        anchors=[]
        if engine:
            current=engine.parent
            for _ in range(4):
                if current not in anchors:anchors.append(current)
                if current.parent==current:break
                current=current.parent
        if configured_engine:
            p=Path(configured_engine)
            anchors.insert(0,p if p.is_dir() else p.parent)

        names=("cura.exe","Cura.exe","Ultimaker Cura.exe")
        for anchor in anchors:
            for name in names:
                candidates.append(anchor/name)
            for rel in (Path("bin")/"cura.exe",Path("bin")/"Cura.exe"):
                candidates.append(anchor/rel)

        for folder in (
            Path(r"C:\Program Files\Ultimaker Cura 4.13.1"),
            Path(r"C:\Program Files\Ultimaker Cura 4.13"),
            Path(r"C:\Program Files (x86)\Ultimaker Cura 4.13.1"),
            Path(r"D:\Programs\Ultimaker Cura 4.13.1"),
        ):
            for name in names:candidates.append(folder/name)

        seen=set()
        for candidate in candidates:
            key=str(candidate).lower()
            if key in seen:continue
            seen.add(key)
            if candidate.exists() and candidate.is_file():
                return candidate

        # Last bounded search around likely Cura roots.
        for anchor in anchors:
            if not anchor.exists() or not anchor.is_dir():continue
            try:
                for candidate in anchor.rglob("Cura.exe"):
                    try:depth=len(candidate.relative_to(anchor).parts)
                    except Exception:depth=99
                    if depth<=4:return candidate
            except Exception:
                pass
        return None

    def launch_cura_gui(self, model_paths, configured_engine=""):
        paths=[Path(p) for p in model_paths]
        missing=[str(p) for p in paths if not p.exists()]
        if missing:
            raise FileNotFoundError("Missing model file(s): "+", ".join(missing))
        if not paths:
            raise ValueError("No model files were supplied to Cura.")
        gui=self.find_cura_gui(configured_engine)
        if not gui:
            raise FileNotFoundError(
                "FabOS could not find Cura.exe. Open Cura manually and drag the listed STL files into it, "
                "or browse to your Cura installation in System → Settings."
            )
        # Cura accepts model file paths as command-line arguments and opens them in the GUI.
        proc=subprocess.Popen([str(gui)]+[str(p) for p in paths],cwd=str(gui.parent))
        return {"cura":gui,"models":paths,"pid":proc.pid}

    def resources_for_engine(self, engine, configured_resources="", configured_fdmprinter="", configured_fdmextruder=""):
        engine=Path(engine)
        install=engine.parent
        roots=[]

        # Explicit definition files win. This supports Cura installs where the GUI works
        # but its resource tree is stored outside the CuraEngine folder.
        if configured_fdmprinter and configured_fdmextruder:
            fdm=Path(configured_fdmprinter);ext=Path(configured_fdmextruder)
            if fdm.exists() and ext.exists():
                common=fdm.parent.parent if fdm.parent.name.lower()=="definitions" else fdm.parent
                return common,fdm,ext

        # Explicit resource folder, if configured later or supplied by environment.
        if configured_resources:
            roots.append(Path(configured_resources))
        env_resources=os.environ.get("CURA_RESOURCES_PATH")
        if env_resources:
            roots.append(Path(env_resources))

        # Search the engine folder and a few ancestors because packaged Cura layouts differ.
        anchors=[]
        current=install
        for _ in range(4):
            if current not in anchors:
                anchors.append(current)
            if current.parent==current:break
            current=current.parent

        common_relatives=(
            Path("resources"),
            Path("share")/"cura"/"resources",
            Path("share")/"cura",
            Path("lib")/"cura"/"resources",
            Path("lib")/"cura",
            Path("cura")/"resources",
        )
        for anchor in anchors:
            for rel in common_relatives:
                roots.append(anchor/rel)

        # Cura's official Windows user-settings locations. Custom definitions and
        # extruders can live here even when the install tree is nonstandard.
        appdata=os.environ.get("APPDATA")
        localapp=os.environ.get("LOCALAPPDATA")
        for base in [appdata,localapp]:
            if not base:continue
            base=Path(base)/"cura"
            for version in ("4.13","4.13.1"):
                roots.append(base/version)
                roots.append(base/version/"resources")
            if base.exists():
                try:
                    for child in base.iterdir():
                        if child.is_dir() and child.name.startswith("4.13"):
                            roots.append(child);roots.append(child/"resources")
                except Exception:
                    pass

        # Bounded discovery for nonstandard Windows installs. Search only directories
        # named resources and only within the likely Cura install anchor.
        likely_root=install
        for anchor in anchors:
            name=anchor.name.lower()
            if "cura" in name:
                likely_root=anchor
                break
        if likely_root.exists() and likely_root.is_dir():
            try:
                for definitions in likely_root.rglob("fdmprinter.def.json"):
                    try:
                        depth=len(definitions.relative_to(likely_root).parts)
                    except Exception:
                        depth=99
                    if depth<=7 and definitions.parent.name.lower()=="definitions":
                        roots.append(definitions.parent.parent)
            except Exception:
                pass

        checked=[]
        seen=set()
        for r in roots:
            try:r=r.resolve()
            except Exception:r=Path(r)
            key=str(r).lower()
            if key in seen:continue
            seen.add(key);checked.append(str(r))
            valid,fdm,ext=self._valid_resources(r)
            if valid:
                return r,fdm,ext
            # User settings folders may themselves contain definitions/ and extruders/.
            fdm2=r/"definitions"/"fdmprinter.def.json"
            ext2=r/"extruders"/"fdmextruder.def.json"
            if fdm2.exists() and ext2.exists():
                return r,fdm2,ext2

        raise FileNotFoundError(
            "Cura resources could not be found for:\n%s\n\n"
            "FabOS looked for Cura's definitions/fdmprinter.def.json and "
            "extruders/fdmextruder.def.json in these locations:\n%s\n\n"
            "You may select either CuraEngine.exe or the Ultimaker Cura 4.13.1 install folder. "
            "For your current setup, the install folder is likely:\n%s"
            %(engine,"\n".join(" • "+x for x in checked[:24]),engine.parent)
        )

    def installation_diagnostic(self, configured="", configured_resources="", configured_fdmprinter="", configured_fdmextruder=""):
        engine=self.find_cura(configured)
        if not engine:
            return {"ok":False,"engine":None,"resources":None,
                    "message":"CuraEngine.exe was not found."}
        try:
            resources,fdm,extruder=self.resources_for_engine(
                engine,configured_resources,configured_fdmprinter,configured_fdmextruder)
            return {"ok":True,"engine":str(engine),"resources":str(resources),
                    "fdmprinter":str(fdm),"fdmextruder":str(extruder),
                    "message":"CuraEngine and resources are ready."}
        except Exception as exc:
            return {"ok":False,"engine":str(engine),"resources":None,"message":str(exc)}

    @staticmethod
    def read_curaprofile(path):
        path=Path(path)
        if not path.exists():raise FileNotFoundError("Cura profile not found: "+str(path))
        global_values={}
        extruder_values={}
        with zipfile.ZipFile(path) as z:
            names=z.namelist()
            if not names:raise ValueError("The .curaprofile archive is empty.")
            for index,name in enumerate(names):
                text=z.read(name).decode("utf-8","replace")
                cfg=configparser.ConfigParser(interpolation=None)
                cfg.optionxform=str
                cfg.read_file(io.StringIO(text))
                values=dict(cfg.items("values")) if cfg.has_section("values") else {}
                meta=dict(cfg.items("metadata")) if cfg.has_section("metadata") else {}
                pos=str(meta.get("position","")).strip()
                if pos=="0" or "extruder" in name.lower():
                    extruder_values.update(values)
                else:
                    global_values.update(values)
        return global_values,extruder_values

    @staticmethod
    def _clean_value(value):
        s=str(value)
        if s=="True":return "true"
        if s=="False":return "false"
        return s

    @staticmethod
    def _cura_progress(line):
        """Return (stage,current,total) for CuraEngine Progress: lines."""
        m=re.search(r"Progress:\s*([^:]+):\s*([0-9.]+)\s*:\s*([0-9.]+)",line,re.I)
        if not m:return None
        try:
            return m.group(1).strip(),float(m.group(2)),float(m.group(3))
        except Exception:
            return None

    def slice(self, model_path, output_path, profile_path, engine_path="", extra_global=None, extra_extruder=None,
              fdmprinter_path="", fdmextruder_path="", progress_callback=None):
        engine=self.find_cura(engine_path)
        if not engine:
            raise ValueError(
                "CuraEngine.exe was not found. Select CuraEngine.exe from your Ultimaker Cura 4.13.1 folder."
            )
        resources,fdm,extruder=self.resources_for_engine(
            engine,configured_fdmprinter=fdmprinter_path,configured_fdmextruder=fdmextruder_path)
        global_profile,extruder_profile=self.read_curaprofile(profile_path)
        global_settings=dict(self.VYPER_GLOBAL)
        extruder_settings=dict(self.VYPER_EXTRUDER)
        global_settings.update(global_profile)
        extruder_settings.update(extruder_profile)
        if extra_global:global_settings.update(extra_global)
        if extra_extruder:extruder_settings.update(extra_extruder)

        output=Path(output_path);output.parent.mkdir(parents=True,exist_ok=True)
        model=Path(model_path)
        if model.suffix.lower()!=".stl":
            raise ValueError(
                "Automatic CuraEngine slicing currently requires an STL. "
                "Import/select an STL version of this design for one-click printing."
            )

        cmd=[str(engine),"slice","-v","-j",str(fdm)]
        for key,value in global_settings.items():
            cmd += ["-s", "%s=%s"%(key,self._clean_value(value))]
        cmd += ["-e0","-j",str(extruder)]
        for key,value in extruder_settings.items():
            cmd += ["-s", "%s=%s"%(key,self._clean_value(value))]
        cmd += ["-l",str(model),"-o",str(output)]

        env=os.environ.copy()
        search=[str(resources/"definitions"),str(resources/"extruders"),str(resources)]
        env["CURA_ENGINE_SEARCH_PATH"]=os.pathsep.join(search)

        started=time.monotonic()
        proc=subprocess.Popen(
            cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
            bufsize=1,universal_newlines=True,env=env,cwd=str(engine.parent)
        )
        stdout_lines=[];stderr_lines=[]
        q=[]
        lock=threading.Lock()

        def reader(stream,target):
            try:
                for line in iter(stream.readline,''):
                    target.append(line)
                    parsed=self._cura_progress(line)
                    if parsed and progress_callback:
                        stage,current,total=parsed
                        fraction=(current/total) if total>0 else 0.0
                        elapsed=time.monotonic()-started
                        # Cura reports progress per stage. Convert the known CuraEngine stages
                        # to a monotonic overall estimate without pretending it is exact.
                        stage_key=stage.lower()
                        stage_ranges={
                            'start':(0.00,0.03),'slice':(0.03,0.35),'layerparts':(0.35,0.48),
                            'inset':(0.48,0.62),'skin':(0.62,0.72),'support':(0.72,0.80),
                            'export':(0.80,0.98),'process':(0.03,0.90)
                        }
                        lo,hi=stage_ranges.get(stage_key,(0.03,0.95))
                        overall=max(0.01,min(0.99,lo+(hi-lo)*fraction))
                        eta=(elapsed*(1.0-overall)/overall) if overall>0.02 else None
                        try:progress_callback(overall,stage,elapsed,eta)
                        except Exception:pass
            finally:
                try:stream.close()
                except Exception:pass

        threads=[
            threading.Thread(target=reader,args=(proc.stdout,stdout_lines),daemon=True),
            threading.Thread(target=reader,args=(proc.stderr,stderr_lines),daemon=True)
        ]
        for th in threads:th.start()
        try:
            returncode=proc.wait(timeout=900)
        except subprocess.TimeoutExpired:
            proc.kill();proc.wait()
            raise TimeoutError("CuraEngine slicing exceeded FabOS's 15-minute safety timeout.")
        for th in threads:th.join(timeout=2)
        stdout=''.join(stdout_lines);stderr=''.join(stderr_lines)
        elapsed=time.monotonic()-started
        if progress_callback:
            try:progress_callback(1.0,'Finished',elapsed,0.0)
            except Exception:pass
        if returncode!=0 or not output.exists() or output.stat().st_size<100:
            detail=(stderr or stdout or "").strip()
            raise RuntimeError(
                "CuraEngine could not create G-code."
                + ("\\n\\n"+detail[-2500:] if detail else "")
            )
        return output,stdout,stderr

    @staticmethod
    def gcode_heater_targets(path):
        hotend=None;bed=None
        for raw in Path(path).read_text(encoding="utf-8",errors="ignore").splitlines():
            line=raw.split(";",1)[0].strip().upper()
            if not line:continue
            if hotend is None and re.match(r"^M10(?:4|9)\b",line):
                m=re.search(r"(?:^|\s)S([0-9.]+)",line)
                if m and float(m.group(1))>0:hotend=float(m.group(1))
            if bed is None and re.match(r"^M1(?:40|90)\b",line):
                m=re.search(r"(?:^|\s)S([0-9.]+)",line)
                if m and float(m.group(1))>0:bed=float(m.group(1))
            if hotend is not None and bed is not None:break
        return {"hotend":hotend,"bed":bed}

    @staticmethod
    def gcode_xy_bounds(path, bed_w=245.0, bed_d=245.0, hard_tolerance=0.50):
        """
        Track G90/G91 and validate G0/G1 XY travel.

        Cura can emit coordinates a few hundredths of a millimeter outside the nominal
        machine extent due to floating point math. FabOS records those as edge warnings
        but only blocks travel beyond the hard tolerance.
        """
        x=y=0.0
        absolute=True
        min_x=min_y=float("inf")
        max_x=max_y=float("-inf")
        violations=[]
        warnings=[]
        token_re=re.compile(r"[A-Z][-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")

        nominal_min_x=0.0
        nominal_min_y=0.0
        nominal_max_x=float(bed_w)
        nominal_max_y=float(bed_d)

        hard_min_x=nominal_min_x-float(hard_tolerance)
        hard_min_y=nominal_min_y-float(hard_tolerance)
        hard_max_x=nominal_max_x+float(hard_tolerance)
        hard_max_y=nominal_max_y+float(hard_tolerance)

        for line_number,raw in enumerate(
            Path(path).read_text(encoding="utf-8",errors="ignore").splitlines(),1
        ):
            clean=raw.split(";",1)[0].strip().upper()
            if not clean:
                continue
            tokens=token_re.findall(clean)
            if not tokens:
                continue
            cmd=tokens[0]

            if cmd=="G90":
                absolute=True
                continue
            if cmd=="G91":
                absolute=False
                continue
            if cmd not in ("G0","G00","G1","G01"):
                continue

            nx=x
            ny=y
            for token in tokens[1:]:
                axis=token[0]
                try:
                    value=float(token[1:])
                except ValueError:
                    continue
                if axis=="X":
                    nx=value if absolute else x+value
                elif axis=="Y":
                    ny=value if absolute else y+value

            x,y=nx,ny
            min_x=min(min_x,x)
            max_x=max(max_x,x)
            min_y=min(min_y,y)
            max_y=max(max_y,y)

            outside_nominal=(
                x < nominal_min_x or x > nominal_max_x or
                y < nominal_min_y or y > nominal_max_y
            )
            outside_hard=(
                x < hard_min_x or x > hard_max_x or
                y < hard_min_y or y > hard_max_y
            )

            record={"line":line_number,"x":x,"y":y,"gcode":raw.strip()}

            if outside_hard:
                violations.append(record)
                if len(violations)>=10:
                    break
            elif outside_nominal:
                warnings.append(record)

        if min_x==float("inf"):
            min_x=max_x=min_y=max_y=0.0

        return {
            "valid":not violations,
            "violations":violations,
            "warnings":warnings,
            "min_x":min_x,"max_x":max_x,
            "min_y":min_y,"max_y":max_y,
            "bed_w":float(bed_w),"bed_d":float(bed_d),
            "hard_tolerance":float(hard_tolerance)
        }

    @staticmethod
    def validate_print_gcode(path):
        text=Path(path).read_text(encoding="utf-8",errors="ignore")
        noncomment=[]
        for raw in text.splitlines():
            line=raw.strip()
            if not line or line.startswith(";"):continue
            line=line.split(";",1)[0].strip()
            if line:noncomment.append(line.upper())
        joined="\n".join(noncomment)
        hotend=bool(re.search(r"(?m)^M10(?:4|9)\b.*\bS\d+",joined))
        bed=bool(re.search(r"(?m)^M1(?:40|90)\b.*\bS\d+",joined))
        motion=bool(re.search(r"(?m)^G0?1\b",joined))
        extrusion=bool(re.search(r"(?m)^G0?1\b.*\bE-?[\d.]+",joined))
        homing=bool(re.search(r"(?m)^G28\b",joined))
        problems=[]
        if not hotend:problems.append("no nozzle temperature command (M104/M109)")
        if not bed:problems.append("no bed temperature command (M140/M190)")
        if not motion:problems.append("no print movement commands")
        if not extrusion:problems.append("no extrusion moves")
        bounds=CuraIntegrationService.gcode_xy_bounds(path,245.0,245.0)
        if not bounds["valid"]:
            v=bounds["violations"][0]
            problems.append(
                "unsafe XY move outside Vyper bed at G-code line %d: X%.2f Y%.2f"
                %(v["line"],v["x"],v["y"])
            )
        return {
            "valid":not problems,
            "problems":problems,
            "hotend":hotend,"bed":bed,
            "motion":motion,"extrusion":extrusion,
            "homing":homing,"bounds":bounds
        }

    @staticmethod
    def gcode_profile_hints(path):
        """Extract human-readable printer/material/profile hints from Cura-style G-code."""
        text=Path(path).read_text(encoding="utf-8",errors="ignore")
        def first(pattern):
            m=re.search(pattern,text,re.I|re.M)
            return m.group(1).strip() if m else None

        machine=(
            first(r"^;\s*MACHINE(?:_NAME)?\s*[:=]\s*(.+)$") or
            first(r"^;\s*TARGET_MACHINE\.NAME\s*[:=]\s*(.+)$") or
            first(r"^;\s*PRINTER(?:_MODEL)?\s*[:=]\s*(.+)$")
        )
        material=(
            first(r"^;\s*MATERIAL(?:_TYPE)?\s*[:=]\s*([A-Za-z0-9 _+\-]+)$") or
            first(r"^;\s*FILAMENT_TYPE\s*[:=]\s*([A-Za-z0-9 _+\-]+)$")
        )
        generator=first(r"^;\s*Generated with\s+(.+)$")
        layer_raw=(
            first(r"^;\s*Layer height\s*[:=]\s*([\d.]+)") or
            first(r"^;\s*LAYER_HEIGHT\s*[:=]\s*([\d.]+)")
        )
        nozzle_raw=(
            first(r"^;\s*NOZZLE_DIAMETER\s*[:=]\s*([\d.]+)") or
            first(r"^;\s*NOZZLE_SIZE\s*[:=]\s*([\d.]+)")
        )

        # Cura 4.x often stores setting keys in comments near the file header.
        if not material:
            m=re.search(r"material_type\s*=\s*([^\\n;]+)",text,re.I)
            if m:material=m.group(1).strip()
        if not machine:
            m=re.search(r"machine_name\s*=\s*([^\\n;]+)",text,re.I)
            if m:machine=m.group(1).strip()
        if not layer_raw:
            m=re.search(r"layer_height\s*=\s*([\d.]+)",text,re.I)
            if m:layer_raw=m.group(1)
        if not nozzle_raw:
            m=re.search(r"machine_nozzle_size\s*=\s*([\d.]+)",text,re.I)
            if m:nozzle_raw=m.group(1)

        targets=CuraIntegrationService.gcode_heater_targets(path)
        meta=CuraIntegrationService.gcode_metadata(path,material or "PLA")
        return {
            "machine":machine,
            "material":material.upper() if material else None,
            "generator":generator,
            "layer_height":float(layer_raw) if layer_raw else None,
            "nozzle_mm":float(nozzle_raw) if nozzle_raw else None,
            "hotend":targets.get("hotend"),
            "bed":targets.get("bed"),
            "estimated_minutes":meta.get("estimated_minutes"),
            "filament_length_m":meta.get("filament_length_m"),
        }

    @staticmethod
    def gcode_metadata(path, material="PLA", diameter=1.75):
        text=Path(path).read_text(encoding="utf-8",errors="ignore")
        seconds=None;length_m=None
        m=re.search(r"^;\s*TIME\s*:\s*([\d.]+)",text,re.I|re.M)
        if m:seconds=float(m.group(1))
        f=re.search(r"^;\s*Filament used\s*:\s*([\d.]+)\s*m",text,re.I|re.M)
        if f:length_m=float(f.group(1))
        grams=None
        if length_m is not None:
            density={
                "PLA":1.24,"PETG":1.27,"ABS":1.04,"ASA":1.07,
                "TPU":1.21,"NYLON":1.14,"PA":1.14
            }.get(str(material or "").upper(),1.24)
            radius_cm=(float(diameter)/10.0)/2.0
            volume_cm3=math.pi*radius_cm*radius_cm*(length_m*100.0)
            grams=volume_cm3*density
        return {
            "estimated_minutes": int(round(seconds/60.0)) if seconds is not None else None,
            "filament_length_m": length_m,
            "filament_g": grams,
        }
