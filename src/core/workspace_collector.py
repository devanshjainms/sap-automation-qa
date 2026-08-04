# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only guest fact collector executed through Azure VM Run Command.

The script is sent verbatim to a seed VM, so it must stay small enough for the
Run Command payload and must run on the oldest Python shipped with a supported
SAP guest image (3.6). Keep it dependency-free and side-effect free.
"""

from __future__ import annotations

COMPACT_COLLECTOR = r"""python3 - <<'PY'
import glob,json,os,re,socket,subprocess,urllib.request,xml.etree.ElementTree as ET
def run(*args):
    try:return subprocess.check_output(args,stderr=subprocess.DEVNULL,universal_newlines=True,timeout=15)
    except (OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired):return ""
def imds(path):
    req=urllib.request.Request("http://169.254.169.254/metadata/instance/"+path+"?api-version=2021-02-01",headers={"Metadata":"true"})
    return json.loads(urllib.request.urlopen(req,timeout=3).read().decode())
def profile_value(sid,key):
    for path in glob.glob("/usr/sap/"+sid+"/SYS/profile/*"):
        try:
            with open(path) as handle:
                for line in handle:
                    match=re.match(r"\s*"+re.escape(key)+r"\s*=\s*(\S+)",line)
                    if match:return match.group(1)
        except OSError:pass
    return ""
compute=imds("compute"); network=imds("network/interface")
cib=run("cibadmin","--query") or run("pcs","status","xml")
root=ET.fromstring(cib) if cib else ET.Element("cib")
members=run("crm_node","-l").splitlines()
member_names=[]
for line in members:
    parts=line.split()
    if len(parts)>1 and parts[0].isdigit():member_names.append(parts[1][:255])
member_names=sorted(set(member_names))[:16]
fencing=[];fence_devices=[]
for node in root.findall(".//primitive"):
    if node.attrib.get("class")!="stonith":continue
    kind=node.attrib.get("type","")[:64]
    fencing.append(kind)
    for pair in node.findall(".//nvpair"):
        if pair.attrib.get("name") in ("devices","sbd_device"):
            fence_devices+=[part[:255] for part in re.split(r"[;,\s]+",pair.attrib.get("value","")) if part]
fencing=sorted(set(fencing));fence_devices=sorted(set(fence_devices))
instances=[]
for group in root.findall(".//group"):
    vip=""
    for primitive in group.findall(".//primitive[@type='IPaddr2']"):
        value=primitive.find("./instance_attributes/nvpair[@name='ip']")
        if value is not None:vip=value.attrib.get("value","")
    for primitive in group.findall(".//primitive[@type='SAPInstance']"):
        attrs={node.attrib.get("name"):node.attrib.get("value") for node in primitive.findall(".//nvpair")}
        match=re.match(r"([A-Z0-9]{3})_(ASCS|ERS)(\d\d)_(\S+)",attrs.get("InstanceName",""))
        if match:instances.append({"sid":match.group(1),"role":match.group(2),"instance_number":match.group(3),"virtual_host":match.group(4)[:255],"vip":vip[:255]})
hana={"installed":False}
paths=glob.glob("/usr/sap/*/HDB[0-9][0-9]")
if len(paths)==1:
    parts=paths[0].split("/"); sid=parts[-2]; number=parts[-1][-2:]
    state=run("su","-",sid.lower()+"adm","-c","hdbnsutil -sr_state")
    hosts=sorted({m.group(1) for m in re.finditer(r"(?m)^(\S+) -> \[",state)})
    hana={"installed":True,"sr_online":"online: true" in state.lower(),"sid":sid,"instance_number":number,"virtual_host":profile_value(sid,"SAPGLOBALHOST"),"hosts":hosts}
sources=[];sapmnt=""
try:
    mounts=json.loads(run("findmnt","--json","--types","nfs,nfs4")).get("filesystems",[])
    for item in mounts:
        source=item.get("source","")[:512];target=item.get("target","")
        if not source:continue
        if re.match(r"^/(sapmnt|hana/shared)(/|$)",target or ""):sapmnt=sapmnt or source
    sources=sorted({item.get("source","")[:512] for item in mounts if item.get("source")})[:4]
except (ValueError,TypeError):pass
ips=[item["ipv4"]["ipAddress"][0]["privateIpAddress"] for item in network if item.get("ipv4",{}).get("ipAddress")]
facts={"schema_version":2,"identity":{"resource_id":compute["resourceId"],"hostname":socket.gethostname()[:255],"private_ip":ips[0] if ips else ""},"cluster":{"members":member_names,"fencing_agents":fencing,"fencing_devices":fence_devices,"sap_instances":instances},"hana":hana,"storage":{"nfs_sources":sources,"sapmnt_source":sapmnt}}
encoded=json.dumps(facts,separators=(",",":"))
print(encoded if len(encoded.encode())<=4096 else json.dumps({"schema_version":2,"error":"collector output exceeds limit"}))
PY"""
