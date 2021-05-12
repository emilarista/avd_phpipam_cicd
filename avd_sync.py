#!/usr/bin/python3
from jinja2 import Template
import sys
import yaml
import json
import ipaddress
import os
# import getpass
import urllib3
from class_phpipam import phpipamapi

urllib3.disable_warnings()

# Some variables from py_vars.py
from py_vars import *

# Helper function for pretty printing
def to_json(input):
    return json.dumps(input, indent = 2, sort_keys=True)

# Get credentials
credsdir = "/foo/bar/"
try:
    with open(credsdir+"credentials.json","r") as f1:
        credentials = json.load(f1)
        ipamapikey = credentials["ipamapikey"]
        ipamhost   = credentials["ipamhost"]
        ipamuser   = credentials["ipamuser"]
        ipampasswd = credentials["ipampasswd"]
except FileNotFoundError as e:
    print(e)

# Instantiate ipam class
ipam = phpipamapi(ipamhost, ipamapikey, ipamuser, ipampasswd)

# We have to build a VLAN map to map some values for later use.
response = ipam.getvlans()
vlans = response["data"]
vlanmap = {}
for vlan in vlans:
    if vlan["custom_Location"] == dc_name:
        vlanid = vlan["vlanId"]                 # This is the internal ID that PHPIPAM uses, not a vid.
        vlannumber = vlan["number"]             # This is the network vlan id.
        name = vlan["name"].replace(" ", "_")
        customer = vlan["customer_id"]          # Needed for later use when generating L2 vlans vars. Again, this is internal PHPIPAM customer ID.
        tags = vlan["custom_tags"].split(",")
        contents = {
            "number": vlannumber,
            "name": name,
            "customer": customer,
            "tags": tags,
        }
        if vlan["custom_VNI-Override"] is not None:
            contents["vni_override"] = int(vlan["custom_VNI-Override"])

        vlanmap[vlanid] = contents

# Getting vrfs from ipam, this is the base we're gonna use to build the tenants and networks dict for avd
response = ipam.getvrfs()
vrfs = response["data"]

# PHPIpam in my version doesn't have a way to get customer data from API :( that's why this is necessary.
customeridmap = {
    "1": {
        "name": "TENANT_A",
        "basevni": 10000,
    }
}

# This is used for rendering the SERVERS file for avd group_vars.
# Basically the type is reflected in a phpIPAM internally relevant ID which we need to map.
devicetypemap = {
    "11": "Server",
    "10": "ESXi",
}

# Same with racks...
rackmap = {
    "1": "RackA1",
}

# Getting devices from ipam.
response = ipam.getdevices()
devices = response["data"]

# Skip some vrfs
skipvrfs = []
# We go through the vrfs and check if they are eligible for deployment with avd.
for vrf in vrfs:
    # Basically, if customer_id and location is not set, we skip it.
    if vrf["customer_id"] and vrf["custom_Location"]:
        # Also if location is not our DC Name, we skip it.
        if vrf["custom_Location"] == dc_name:
            customerid = vrf["customer_id"]
            vrf["customer"] = customeridmap[customerid]
            vrfid = vrf["vrfId"]
            response = ipam.getonevrf(vrfid, getsubnets = True)
            if "data" in response:
                subnets = response["data"]
            else:
                subnets = []
            vrf["vlans"] = []
            if subnets:
                for net in subnets:
                    response = ipam.getsubnetaddresses(net["id"])
                    if "data" in response:
                        addresses = response["data"]
                    else:
                        addresses = []
                    net["addresses"] = addresses
                    vlanid = net["vlanId"]
                    net["vlanname"] = vlanmap[vlanid]["name"]
                    net["vlannumber"] = vlanmap[vlanid]["number"]
                    net["tags"] = vlanmap[vlanid]["tags"]
                    if "vni_override" in vlanmap[vlanid]:
                        net["vni_override"] = vlanmap[vlanid]["vni_override"]
                    vrf["vlans"].append(net)
                    del vlanmap[vlanid]
        else:
            skipvrfs.append(vrf)
    else:
        skipvrfs.append(vrf)

# Here we start to build the avd data structure for TENANTS_NETWORKS file.
overlay = {}
overlay["tenants"] = {}

for custid, contents in customeridmap.items():
    name = contents["name"]
    basevni = contents["basevni"]
    overlay["tenants"][name] = {"vrfs": {}}
    overlay["tenants"][name]["l2vlans"] = {}
    overlay["tenants"][name]["mac_vrf_vni_base"] = basevni

for vrf in vrfs:
    if vrf not in skipvrfs:
        tenant = vrf["customer"]["name"]
        vrfname = vrf["name"]
        svis = {}
        for vlan in vrf["vlans"]:
            number = int(vlan["vlannumber"])
            network = vlan["subnet"]
            mask = vlan["mask"]
            ip_subnet = "{}/{}".format(network, mask)
            vlanname = vlan["vlanname"]
            tags = vlan["tags"]
            svis[number] = {
                "enabled": True,
                "name": vlanname,
                "tags": tags
            }
            # Search the access type VLANs/SVIs for a candidate ip_address_virtual to use based on "is_gateway" attribute.
            # If none found, use lowest address in subnet.
            if vlan["custom_SVI_style"] == "access":
                if len(vlan["addresses"]) > 0:
                    for address in vlan["addresses"]:
                        if address["is_gateway"] == "1":
                            ip_address_virtual = address["ip"]
                            break
                        else:
                            ip_address_virtual = str(ipaddress.ip_network(ip_subnet)[1])
                else:
                    ip_address_virtual = str(ipaddress.ip_network(ip_subnet)[1])
                ip_address_virtual = "{}/{}".format(ip_address_virtual, mask)
                svis[number]["ip_address_virtual"] = ip_address_virtual

            # Search the peering type VLANs/SVIs for a candidate ip_virtual_router_address to use based on the "is_gateway" attribute.
            # Also search for nodes IPs to use in overlay configuration.
            elif vlan["custom_SVI_style"] == "peering":
                nodes = {}
                found_gw = False
                if len(vlan["addresses"]) > 0:
                    for address in vlan["addresses"]:
                        if address["is_gateway"] == "1":
                            ip_virtual_router_address = address["ip"]
                            found_gw = True
                        elif address["custom_deviceType"] == "switch" and address["deviceId"]:
                            deviceid = address["deviceId"]

                            for device in devices:
                                if deviceid == device["id"]:
                                    node = {device["hostname"]: {"ip_address": "{}/{}".format(address["ip"], mask)}}
                                    nodes.update(node)
                if found_gw == False:
                    ip_virtual_router_address = str(ipaddress.ip_network(ip_subnet)[1])
                    ip_virtual_router_address = "{}/{}".format(ip_virtual_router_address, mask)
                else:
                    pass
                svis[number]["ip_virtual_router_address"] = ip_virtual_router_address
                if len(nodes) > 0:
                    svis[number]["nodes"] = nodes

            if "vni_override" in vlan:
                svis[number]["vni_override"] = vlan["vni_override"]
        overlay["tenants"][tenant]["vrfs"][vrfname] = {"svis": svis}
        vrf_vni = int(vrf["custom_VNI"])
        overlay["tenants"][tenant]["vrfs"][vrfname]["vrf_vni"] = vrf_vni


# Build l2vlans data using all entries left in vlanmap (l3 vlans are deleted from the map when svis data is created above).
# VLANs with subnets, located in DC1, but without a VRF defined will become an l2vlan in the EVPN fabric.
for vlan in vlanmap:
    vlaninfo = {
        "name": vlanmap[vlan]["name"],
        "tags": vlanmap[vlan]["tags"]
        }
    if "vni_override" in vlanmap[vlan]:
        vlaninfo["vni_override"] = vlanmap[vlan]["vni_override"]
    vlanid = int(vlanmap[vlan]["number"])
    customerid = vlanmap[vlan]["customer"]
    tenant = customeridmap[customerid]["name"]
    overlay["tenants"][tenant]["l2vlans"][vlanid] = vlaninfo


with open("{}/{}_TENANTS_NETWORKS.yml".format(gvars_dir, dc_name), "r") as f:
    old_overlay = yaml.load(f.read())


repo_changed = False
changed_files = []

if overlay == old_overlay:
    # There are no changes found
    pass
else:
    with open("{}/{}_TENANTS_NETWORKS.yml".format(gvars_dir, dc_name), "w") as f:
        print("found changes, syncing")
        f.write("---\n")
        f.write("# This file is maintained by avd_sync.py. Do not edit manually as any changes will be overwritten.\n")
        f.write(yaml.dump(overlay))
        repo_changed = True
        changed_files.append("{}_TENANTS_NETWORKS.yml".format(dc_name))


# Now we're gonna build the server interfaces
with open("{}/{}_SERVERS.yml".format(gvars_dir, dc_name), "r") as f:
    old_serversfile = (yaml.load(f.read()))
    port_profiles = old_serversfile["port_profiles"]
    old_servers = old_serversfile["servers"]
    new_servers = {}
    for device in devices:
        # This is an ugly, ugly try-except clause. I Should really do something nicer.
        try:
            if devicetypemap[device["type"]] == "Server" or devicetypemap[device["type"]] == "ESXi":
                access_ports = device["custom_Access Ports"].split(",")
                if "custom_Server Interfaces" not in device:
                    server_port_prefix = "Eth"
                    server_portno = 0
                    server_ports = []
                    for port in access_ports:
                        server_ports.append(server_port_prefix+str(server_portno))
                        server_portno += 1
                switches = device["custom_Connected Swithes"].split(",")
                if device["rack"]:
                    rack = rackmap[device["rack"]]
                else:
                    rack = "Undefined"
                server = {
                    "rack": rack,
                    "adapters": [
                        {
                            "server_ports": server_ports,
                            "switch_ports": access_ports,
                            "switches": switches,
                        }
                    ]
                }
                if device["custom_Untagged VLAN"] or device["custom_Tagged VLAN"]:
                    # Not yet implemented
                    pass

                if device["custom_Port Profile"]:
                    server["adapters"][0]["profile"] = device["custom_Port Profile"]

                if device["custom_Port-Channel"].lower() == "yes":
                    server["adapters"][0]["port-channel"] = {
                        "description": "Something blabla",              # ??? Nice...
                        "mode": "active",
                        "state": "present"
                    }

                new_servers[device["hostname"]] = server

        except:
            pass
            # print("Some exception occurred", e)

if new_servers == old_servers:
    pass
else:
    new_serversfile = {
        "servers": new_servers,
        "port_profiles": port_profiles,
    }

    with open("{}/{}_SERVERS.yml".format(gvars_dir, dc_name), "w") as f:
        f.write("---\n")
        f.write("# This file is maintained by avd_sync.py script.\n# Port profiles may be edited manually, but servers will be overwritten on next run.\n")
        f.write(yaml.dump(new_serversfile))

    repo_changed = True
    changed_files.append("{}_SERVERS.yml".format(dc_name))


if repo_changed:
    print("Commiting...")
    commitmessage = "Automated commit from ansible control node, changes found in: {}".format(", ".join(changed_files))
    os.chdir(top_directory)
    for changed_file in changed_files:
        os.system("git add {}/{}".format(gvars_dir, changed_file))
    os.system("git commit -m \"{}\"".format(commitmessage))
    os.system("git push")


sys.exit()





