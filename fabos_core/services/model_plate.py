from pathlib import Path
import struct,math

class ModelPlateService:
    def __init__(self,vault,data_dir):
        self.vault=vault
        self.data_dir=Path(data_dir)

    @staticmethod
    def _read_stl(path):
        path=Path(path);raw=path.read_bytes()
        triangles=[]
        is_binary=False
        if len(raw)>=84:
            try:
                count=struct.unpack("<I",raw[80:84])[0]
                is_binary=(84+count*50)==len(raw)
            except Exception:
                pass
        if is_binary:
            count=struct.unpack("<I",raw[80:84])[0]
            off=84
            for _ in range(count):
                vals=struct.unpack("<12fH",raw[off:off+50]);off+=50
                normal=tuple(vals[0:3])
                verts=[tuple(vals[3:6]),tuple(vals[6:9]),tuple(vals[9:12])]
                triangles.append((normal,verts))
        else:
            verts=[]
            for line in raw.decode("utf-8","ignore").splitlines():
                s=line.strip().lower()
                if s.startswith("vertex "):
                    bits=s.split()
                    try:verts.append((float(bits[1]),float(bits[2]),float(bits[3])))
                    except Exception:pass
                    if len(verts)==3:
                        triangles.append(((0.0,0.0,0.0),verts));verts=[]
        if not triangles:
            raise ValueError("Could not read STL geometry: %s"%path.name)
        return triangles

    @staticmethod
    def _bounds(triangles):
        xs=[];ys=[];zs=[]
        for _,verts in triangles:
            for x,y,z in verts:xs.append(x);ys.append(y);zs.append(z)
        return min(xs),max(xs),min(ys),max(ys),min(zs),max(zs)

    @staticmethod
    def _normal(v1,v2,v3):
        ax=v2[0]-v1[0];ay=v2[1]-v1[1];az=v2[2]-v1[2]
        bx=v3[0]-v1[0];by=v3[1]-v1[1];bz=v3[2]-v1[2]
        nx=ay*bz-az*by;ny=az*bx-ax*bz;nz=ax*by-ay*bx
        mag=math.sqrt(nx*nx+ny*ny+nz*nz)
        if mag<=1e-12:return (0.0,0.0,0.0)
        return (nx/mag,ny/mag,nz/mag)

    @staticmethod
    def _write_binary_stl(path,triangles,name="FabOS Complete Set"):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        header=name.encode("ascii","ignore")[:80].ljust(80,b" ")
        with path.open("wb") as f:
            f.write(header);f.write(struct.pack("<I",len(triangles)))
            for verts in triangles:
                n=ModelPlateService._normal(verts[0],verts[1],verts[2])
                f.write(struct.pack("<3f",*n))
                for v in verts:f.write(struct.pack("<3f",*v))
                f.write(struct.pack("<H",0))
        return path

    @staticmethod
    def _shelf_pack(pieces,bed_w,bed_d,edge,spacing):
        # Try a few deterministic orderings. Each shelf also tests 90-degree rotation.
        orderings=[
            sorted(pieces,key=lambda p:max(p["w"],p["d"]),reverse=True),
            sorted(pieces,key=lambda p:p["w"]*p["d"],reverse=True),
            sorted(pieces,key=lambda p:p["d"],reverse=True),
        ]
        usable_w=bed_w-2*edge;usable_d=bed_d-2*edge
        for ordered in orderings:
            placed=[];x=edge;y=edge;row_h=0.0;failed=False
            for piece in ordered:
                choices=[(piece["w"],piece["d"],False),(piece["d"],piece["w"],True)]
                # prefer orientation that fits current shelf and leaves less wasted horizontal space
                valid=[c for c in choices if c[0]<=usable_w and c[1]<=usable_d]
                if not valid:failed=True;break
                valid.sort(key=lambda c:(0 if x+c[0]<=bed_w-edge else 1,
                                         abs((bed_w-edge)-(x+c[0])),c[1]))
                w,d,rot=valid[0]
                if x+w>bed_w-edge:
                    x=edge;y+=row_h+spacing;row_h=0.0
                    valid=[c for c in choices if c[0]<=usable_w and y+c[1]<=bed_d-edge]
                    if not valid:failed=True;break
                    valid.sort(key=lambda c:(c[1],c[0]))
                    w,d,rot=valid[0]
                if y+d>bed_d-edge:
                    failed=True;break
                item=dict(piece);item.update({"x":x,"y":y,"placed_w":w,"placed_d":d,"rot90":rot})
                placed.append(item)
                x+=w+spacing;row_h=max(row_h,d)
            if not failed:
                return placed
        return None

    def build_complete_set(self,product_id,bed_w=245.0,bed_d=245.0,edge=5.0,spacing=4.0):
        did=self.vault.ensure_product(product_id)
        summary=self.vault.model_set_summary(did)
        if summary["mode"]!="part_set":
            raise ValueError("This product is not configured as a Part Set.")
        parts=[p for p in summary["parts"] if p["include_in_complete_set"] and int(p["quantity"] or 0)>0]
        if not parts:raise ValueError("No included parts are configured for the complete set.")

        pieces=[];geometry={}
        for part in parts:
            path=Path(part["stored_path"])
            if not path.exists():raise FileNotFoundError("Missing local part file: "+part["original_name"])
            tris=self._read_stl(path);geometry[part["id"]]=tris
            minx,maxx,miny,maxy,minz,maxz=self._bounds(tris)
            w=maxx-minx;d=maxy-miny
            if w<=0 or d<=0:raise ValueError("Invalid STL footprint: "+part["original_name"])
            for copy_index in range(int(part["quantity"] or 1)):
                pieces.append({
                    "part_id":part["id"],"part_name":part["part_name"],
                    "source":str(path),"copy":copy_index+1,
                    "w":w,"d":d,"minx":minx,"miny":miny,"minz":minz
                })

        placements=self._shelf_pack(pieces,float(bed_w),float(bed_d),float(edge),float(spacing))
        if placements is None:
            total_area=sum(p["w"]*p["d"] for p in pieces)
            raise ValueError(
                "The complete part set could not be auto-arranged inside %.0f × %.0f mm. "
                "Pieces: %d, combined footprint area: %.0f mm². Try printing parts separately or reduce quantities."
                %(bed_w,bed_d,len(pieces),total_area)
            )

        # Center the complete packed group on the Vyper bed.
        group_min_x=min(p["x"] for p in placements)
        group_min_y=min(p["y"] for p in placements)
        group_max_x=max(p["x"]+p["placed_w"] for p in placements)
        group_max_y=max(p["y"]+p["placed_d"] for p in placements)
        group_w=group_max_x-group_min_x
        group_d=group_max_y-group_min_y
        shift_x=((float(bed_w)-group_w)/2.0)-group_min_x
        shift_y=((float(bed_d)-group_d)/2.0)-group_min_y
        for p in placements:
            p["x"]+=shift_x
            p["y"]+=shift_y

        combined=[]
        for p in placements:
            tris=geometry[p["part_id"]]
            minx,miny,minz=p["minx"],p["miny"],p["minz"]
            original_w=p["w"]
            for _,verts in tris:
                out=[]
                for vx,vy,vz in verts:
                    nx=vx-minx;ny=vy-miny;nz=vz-minz
                    if p["rot90"]:
                        rx=ny;ry=original_w-nx
                    else:
                        rx=nx;ry=ny
                    out.append((rx+p["x"],ry+p["y"],nz))
                combined.append(out)

        folder=self.data_dir/"Generated Plates"/str(product_id)
        output=folder/"Complete_Set.stl"
        self._write_binary_stl(output,combined)
        min_x=min(p["x"] for p in placements)
        min_y=min(p["y"] for p in placements)
        max_x=max(p["x"]+p["placed_w"] for p in placements)
        max_y=max(p["y"]+p["placed_d"] for p in placements)
        return {
            "path":output,"placements":placements,"pieces":len(placements),
            "part_count":len(parts),"bed_w":float(bed_w),"bed_d":float(bed_d),
            "used_w":max_x-min_x,"used_d":max_y-min_y,
            "min_x":min_x,"min_y":min_y,"max_x":max_x,"max_y":max_y,
            "center_x":(min_x+max_x)/2.0,"center_y":(min_y+max_y)/2.0
        }
