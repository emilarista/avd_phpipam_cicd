# AVD Pipeline

This documentation is a work in progress. Not complete by any stretch, but avd.sh and the github repos for arista avd and cvp have a lot of documentation related to ansible/avd. I've tried to document the rest in this README.

## Requirements

* PHPIpam
* Gitlab
* An ansible box (linux distro of your choice)
    - ansible
    - gitlab runner
    - Python3.x along with some modules:
        - ipaddress (avd uses netaddr, which I could probably have reused in retrospect)
        - netaddr
        - ansible
        - treelib
        - cvprac
        - urllib3
        - yaml
        - virtualenv
        - probably more...
* CVP (if you intend to deploy via CVP)
* Some network fabric

## Components

All of the external components used like phpIPAM, ansible, avd, gitlab, python, are 100% open source and free to use and abuse.

### PHPIpam

PHPIpam is used to store the information for the overlay configuration as well as for server access ports.

API documentation:
https://phpipam.net/
https://phpipam.net/api/api_reference/

There are some custom fields at play in PHPIpam, but the good news is that it's very easy to implement them, just navigate to the Administration menu -> Custom Fields and have at it:

The custom fields are settable in API requests to phpIPAM, as well as included when getting info from the API.

Required/Recommended:

* 'Location' field for VLAN and VRF. 'set' type, Size/Length: 'Option1','Option2','Option3'. Default: Option1
    - Used along with Customer field (not custom) to make the VLAN/VRF "eligible" for deployment in the fabric.
* 'Tags' field for VLAN. 'varchar' type. Size/Length: 128.
    - Used as comma-separated list of tags, used for filtering deployment of VLANs/SVIs depending on leaf tags.
* 'VNI' field for VRF. 'varchar' type. Size/Length: 50.
    - Used to set the L3VNI for the VRF.
    - Could probably have reused the built in RD field for this, but oh well...

Optional to implement:

* 'VNI-Override' field for VLAN. 'int' type.
    - Used to override the automatic VLAN-to-VNI mapping that AVD uses.
* 'SVI_style' field for Subnet. 'set' type, Size/Length: 'access','peering'. Default: access.
    - Used for setting ip address virtual vs ip virtual-router address + unique per-leaf addresses for the SVI (the latter requires some Device logic).
* 'deviceType' field for IP addresses. 'varchar' type. Size/Length: 100.
    - Only used if you want to implement SVI_style: peering with unique addresses per leaf. Device field of IP address is used to select which leaf. Only IP addresses with deviceType = 'switch' are considered.

#### More on SVI_style

SVI_style custom field is used to select whether to build an SVI with 'ip address virtual' or 'ip virtual-router address' + unique per-leaf IP addressing.

peering/access:

In the subnet in PHPIpam, you may reserve an address and tick the "Is gateway" flag. This idicates the address will be used as the virtual IP in either case. If this is not defined, the lowest address in the subnet becomes the virtual IP.

peering:

More logic is required if you use the 'peering' type. Because then you need to set IP-addresses per leaf. This could possibly be substituted for something that depends on avd device IDs instead. Start by defining your leafs as devices in PHPIpam. Not much is needed except the name, which needs to match your ansible inventory name exactly.

When a device is defined, you may reserve an address per leaf in the subnet by setting the deviceType field to 'switch', the appropriate Location, as well as selecting the device that should be assigned the IP (for example 'leaf3a').

The sync script will look for addresses that are reserved and compare to its ansible inventory and feed the info into the overlay configuration yaml file like so:

    ---
    tenants:
      TENANT_A:
        ...
        vrfs:
          APP:
            svis:
              ...
              1001:
                enabled: true
                ip_virtual_router_address: 172.31.1.1
                name: APP_FW_Peering
                nodes:
                  leaf3a: {ip_address: 172.31.1.2/28}
                  leaf3b: {ip_address: 172.31.1.3/28}
                tags: [border]
            ...

#### Caveat

PHPIpam has a customers section that we will use to build the 'tenants' part of the overlay config. At present there is no way to query the API for customer information, so we need to map them manually in avd_sync.py. The key is the ID (PHPIpam internal logic) for the customer, which we do get when we query for VLANs/Subnets/VRFs, however in order to get more customer info, we need to do this mapping manually.

    customeridmap = {
        "1": {
            "name": "TENANT_A",
            "basevni": 10000,
        }
    }

This sucks a little bit, but luckily this info doesn't change that often. Hoping this will be rectified in a future release of PHPIpam. Otherwise, netbox is probably a better bet anyway.

### Python

Python scripts are used to talk to the Ipam API, retrieve the devices, subnets, VLANs, and VRFs, and convert them into yaml to be consumed by ansible/avd.

* avd_sync.py - Talks to Ipam and syncs overlay config. For now this runs on a cronjob every x minutes. It is also possible to run on demand or maybe to webhook it somehow,
* class_phpipam.py - Python class that is used by avd_sync.py to talk to Ipam API. Wrote it myself, pretty simple.
* vars-validator.py - Validation script that checks sanity of group variables in the context of avd. Again, wrote it myself, the script is only as smart as the person who wrote it... It runs as part of the CI-CD pipeline.
* py_vars.py - Just a few basic variable definitions used by the sync and validator scripts.

Credentials:

Some of the credentials for the python scripts are stored in a credentials.json file (not included in the repo) formatted like so:

    {
        "ipamapikey":   "<api-key>",
        "ipamhost":     "ipam.example.com",
        "ipamuser":     "<ipam-user>",
        "ipampasswd":   "<ipam-password>"
    }

Some credentials, mainly for interacting with CVP are stored in the group_vars/DC1.yml file and some are stored in the ansible inventory file. This could probably be consolidated in some smart way...

### Ansible AVD/CVP Collections

Ansible AVD and CVP collections are used to generate actual EOS configs and interact with CVP.
https://github.com/aristanetworks/ansible-avd
https://github.com/aristanetworks/ansible-cvp
https://avd.sh

TOI information and labs on avd and cvp collections is located here:
https://github.com/arista-netdevops-community/ansible-cvp-avd-toi

The group vars and host vars folders are included in the repo along with the ansible inventory to provide a simple avd deployment example.

### Gitlab

Gitlab has some neat CI-CD pipeline capabilities as well as version control. We also run the gitlab-runner agent on the ansible control box.

#### Gitlab Runner

This is a tiny agent that runs on the ansible box and gets notified of any changes in the repo. When a change is detected the runner agent clones the repo to a temp directory and executes the pipeline.

#### Gitlab CI-CD Pipeline

For the pipeline to work, rename the "example.gitlab-ci.yml" to ".gitlab-ci.yml".

This is a yaml file (yes... ANOTHER yaml file) that tells the gitlab-runner agent what to do. It's got a few stages:

* lint
    - Checks the group_vars yaml files and the ansible playbook for syntax.
* validate
    - Runs vars-validator.py to do a sanity-check on the group_vars in the context of avd. Not very sophisticated as of now, but could easily be extended/improved.
* prepare
    - Makes sure the environment is ready to run the ansible playbook, ie: it installs the arista.avd and arista.cvp collections if they're not already present.
* test (which is actually deployment into the test environment)
    - Runs the playbook PLAY_evpn_deploy.yml which generates EOS config and pushes it to CVP + creates change control to execute tasks.
* state_check
    - Runs the playbook PLAY_evpn_validate_state.yml which uses the eos_validate_state role to validate the network state, only a subset of the role tasks is used to save time for demo purposes.

The tags assigned to each step are used to tell the gitlab-runner which tasks it should perform. My gitlab-runner is assigned all the tags present in the pipeline.
