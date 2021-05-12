#!/usr/bin/python3.7

import ipaddress
import yaml
import urllib3
from cvprac.cvp_client import CvpClient
from cvprac.cvp_client_errors import CvpApiError
import sys

urllib3.disable_warnings()

# Import some variables from py_vars.py file
from py_vars import *

# Start by validating Overlay config in DC1_TENANTS_NETWORKS.yml
with open("{}/{}_TENANTS_NETWORKS.yml".format(gvars_dir, dc_name), "r") as f:
    overlay = yaml.load(f.read())

for tenant, tenantinfo in overlay["tenants"].items():
    # Fist we need to test that all mac_vrf_vni_bases for tenants are int type.
    if isinstance(tenantinfo["mac_vrf_vni_base"], int):
        pass
    else:
        raise Exception("mac_vrf_vni_base in tenant {} was not type: int, it was type: {}.".format(tenant, type(tenantinfo["mac_vrf_vni_base"])))

    # print(sys.getsizeof("65535"))
    # first we check l2vlans for some stuff we know will break execution
    for vlan, vlaninfo in tenantinfo["l2vlans"].items():
        if "vni_override" in vlaninfo and vlaninfo["vni_override"] > 65535:
            raise Exception("vni_override value of tenant {} l2vlan {} is over 32 bytes long, this might trip you up due to rt/rd length constraints.".format(tenant, vlan))

    l3_vni_dict = {}
    # Then we loop through vrfs
    for vrf, vrfinfo in tenantinfo["vrfs"].items():
        # We need to check that vrf_vni is int type.
        # Fist we need to test that all mac_vrf_vni_bases for tenants are int type.
        if isinstance(vrfinfo["vrf_vni"], int):
            pass
        else:
            raise Exception("vrf_vni in tenant {} vrf {} was not type: int, it was type: {}.".format(tenant, vrf, type(vrfinfo["vrf_vni"])))

        # Check for duplicate l3 vnis
        if vrfinfo["vrf_vni"] not in l3_vni_dict:

            l3_vni_dict[vrfinfo["vrf_vni"]] = vrf
        else:
            duplicate_vrf = l3_vni_dict[vrfinfo["vrf_vni"]]
            raise Exception("VRF vni {} in vrf {} overlaps with vrf {} Please correct it.".format(vrfinfo["vrf_vni"], vrf, duplicate_vrf))

        for svi, sviinfo in vrfinfo["svis"].items():
            # Svis also need to be int type for everything to work correctly.
            if isinstance(svi, int):
                pass
            else:
                raise Exception("svi {} in tenant {}, vrf {} was not int type, it was type: {}".format(svi, tenant, vrf, type(svi)))

            if " " in sviinfo["name"]:
                raise Exception("Whitespace found in svi {} name, this is not allowed.")
            else:
                pass

# Validate DC1_SPINES.yml
with open("{}/{}_SPINES.yml".format(gvars_dir, dc_name), "r") as f:
    spine = yaml.load(f.read())

    if spine["type"] != "spine":
        raise Exception("spine type in {}_SPINES.yml is not spine, the file should contain a single variable like this: 'type: spine'".format(dc_name))
    else:
        pass


# Validate DC1_L3LEAFS.yml
with open("{}/{}_L3LEAFS.yml".format(gvars_dir, dc_name), "r") as f:
    leaf = yaml.load(f.read())

    if leaf["type"] != "l3leaf":
        raise Exception("spine type in DC1_L3LEAFS.yml is not l3leaf, the file should contain a single variable like this: 'type: l3leaf'")
    else:
        pass

# Validate DC1.yml
with open("{}/{}.yml".format(gvars_dir, dc_name), "r") as f:
    dc = yaml.load(f.read())
    # Test if cvp_instance_ip is a valid IP address
    iptest = ipaddress.ip_address(dc["cvp_instance_ip"])
    # Test if mgmt_gw is a valid IP address
    iptest = ipaddress.ip_address(dc["mgmt_gateway"])

    cvp_ip = dc["cvp_instance_ip"]

# Validate inventory
with open("{}/inventory.yml".format(project_folder), "r") as f:
    # Test cvp client access.
    inventory = yaml.load(f.read())
    inv_cvp_ip = inventory["all"]["children"]["CVP"]["hosts"]["cv_server"]["ansible_httpapi_host"]
    iptest = ipaddress.ip_address(inv_cvp_ip)
    if inv_cvp_ip == cvp_ip:
        pass
    else:
        raise Exception("cvp_ip in {}.yml {} is not the same as inventory cvp ip {}.".format(dc_name, cvp_ip, inv_cvp_ip))

    cvp_user = inventory["all"]["children"]["CVP"]["hosts"]["cv_server"]["ansible_user"]
    cvp_pass = inventory["all"]["children"]["CVP"]["hosts"]["cv_server"]["ansible_password"]

    # Testing cvp ip/user/password
    clnt = CvpClient()
    clnt.connect([inv_cvp_ip], cvp_user, cvp_pass)


# Validate DC1_FABRIC.yml
with open("{}/{}_FABRIC.yml".format(gvars_dir, dc_name), "r") as f:
    fabric = yaml.load(f.read())

    # Check fabric naming sanity
    fab_name = fabric["fabric_name"]
    if dc_name not in fab_name:
        raise Exception("dc_name variable: {} specified in py_vars.py isn't included in fabric name {} in {}_FABRIC.yml".format(dc_name, fab_name, dc_name))
    else:
        pass

    # Check that peer groups have passwords defined
    for peergroup, pginfo in fabric["bgp_peer_groups"].items():
        if not pginfo["password"]:
            raise Exception("No bgp password was defined for peer group {} in {}_FABRIC.yml".format(peergroup, dc_name))

    spine_as = fabric["spine"]["bgp_as"]
    accepted_leaf_as_range = fabric["spine"]["leaf_as_range"]
    # Turning accepted_leaf_as_range into a list of asn
    xranges = [(lambda l: range(l[0], l[-1]+1))(list(map(int, r.split('-')))) for r in accepted_leaf_as_range.split(',')]
    accepted_leaf_as_range = [y for x in xranges for y in x]

    spineids = []
    spines = []
    fabric_platforms = []
    try:
        fabric_platforms.append(fabric["spine"]["platform"])
    except KeyError:
        raise Exception("Spines platform is not defined in {}_FABRIC.yml".format(dc_name))

    for spine, spineinfo in fabric["spine"]["nodes"].items():
        spines.append(spine)
        if spineinfo["id"] not in spineids:
            spineids.append(spineinfo["id"])
        else:
            raise Exception("Duplicate spine ids found in {}_FABRIC.yml spines definition".format(dc_name))

        if not spineinfo["mgmt_ip"]:
            raise Exception("Spine device {} missing mgmt_ip assignment in {}_FABRIC.yml".format(spine, dc_name))

    for item in fabric["l3leaf"]["defaults"]["spines"]:
        if item not in spines:
            raise Exception("Spine device {} in l3leaf defaults settings is not defined under spines in {}_FABRIC.yml".format(item, dc_name))

    fabric_platforms.append(fabric["l3leaf"]["defaults"]["platform"])

    for nodegroup, nginfo in fabric["l3leaf"]["node_groups"].items():
        if nginfo["bgp_as"] not in accepted_leaf_as_range:
            raise Exception("Leaf/leaf group {} bgp asn {} is outside accepted range {} defined for spines in {}_FABRIC.yml".format(
                nodegroup,
                nginfo["bgp_as"],
                fabric["spine"]["leaf_as_range"],
                dc_name))

        for node, nodeinfo in nginfo["nodes"].items():
            if not nodeinfo["id"]:
                raise Exception("Node {} in node group {} in {}_FABRIC.yml does not have a defined id, should be for example 'id: 1' for first leaf node.".format(
                    node, nodegroup, dc_name))

            if not nodeinfo["mgmt_ip"]:
                raise Exception("Node {} in node group {} in {}_FABRIC.yml does not have a mgmt_ip defined".format(node, nodegroup, dc_name))

            try:
                if len(nodeinfo["spine_interfaces"])<1:
                    raise Exception("Node {} in node group {} in {}_FABRIC.yml does not have any spine_interfaces defined.".format(node, nodegroup, dc_name))
            except KeyError:
                raise Exception("Node {} in node group {} in {}_FABRIC.yml does not have any spine_interfaces defined.".format(node, nodegroup, dc_name))

    if "veos-lab" in (x.lower() for x in fabric_platforms):
        if ("update wait-for-convergence" in (x for x in fabric["spine_bgp_defaults"])) or ("update wait-install" in (x for x in fabric["spine_bgp_defaults"])):
            raise Exception("Found update wait-install or update wait-for-convergence in spine_bgp_defaults in {}_FABRIC.yml in combination with platform vEOS-LAB, this will cause routes not to be installed properly.".format(dc_name))

        if ("update wait-for-convergence" in (x for x in fabric["leaf_bgp_defaults"])) or ("update wait-install" in (x for x in fabric["leaf_bgp_defaults"])):
            raise Exception("Found update wait-install or update wait-for-convergence in leaf_bgp_defaults in {}_FABRIC.yml in combination with platform vEOS-LAB, this will cause routes not to be installed properly.".format(dc_name))


# Validate SERVERS file
with open("{}/{}_SERVERS.yml".format(gvars_dir, dc_name), "r") as f:
    servers = yaml.load(f.read())
    for server, serverinfo in servers["servers"].items():
        for adapter in serverinfo["adapters"]:
            if len(adapter["server_ports"]) == len(adapter["switch_ports"]) == len(adapter["switches"]):
                pass
            else:
                raise Exception("Found a mismatch between number of server ports, switch ports and switches in file {}/{}_SERVERS.yml, server: {}".format(gvars_dir, dc_name, server))






# Validate CVP.yml could check that the parent containers for each device exist.