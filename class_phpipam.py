import requests
import json


class phpipamapi():

    def __init__(self, host, apikey, username, password, **kwargs):

        self.apiapp = "apiadmin"
        self.baseurl="http://{}/api/{}".format(host, self.apiapp)
        self.authurl = self.baseurl+"/user"

        payload = {
            "Auhtorization": "Basic "+apikey
        }

        self.auth = (username, password)
        result = requests.post(self.authurl, auth=self.auth, json=payload).json()
        self.token = result["data"]["token"]
        self.authheader = {'token': self.token }
        return

    def getsubnets(self):
        url = self.baseurl+"/subnets"
        result = requests.get(url, headers=self.authheader).json()
        return result

    def getonesubnet(self, subnetid):
        url = self.baseurl+"/subnets/{}".format(subnetid)
        result = requests.get(url, headers=self.authheader).json()
        return result

    def getsubnetaddresses(self, subnetid):
        url = self.baseurl+"/subnets/{}/addresses/".format(subnetid)
        result = requests.get(url, headers=self.authheader).json()
        return result

    def getvrfs(self):
        url = self.baseurl+"/vrf"
        result = requests.get(url, headers=self.authheader).json()
        return result

    def getonevrf(self, vrfid, **kwargs):
        url = self.baseurl+"/vrf/{}".format(vrfid)
        if "getsubnets" in kwargs and kwargs["getsubnets"] == True:
            url += "/subnets"
        result = requests.get(url, headers=self.authheader).json()
        return result

    def getvlans(self):
        url = self.baseurl+"/vlan/"
        result = requests.get(url, headers=self.authheader).json()
        return result

    def getsections(self):
        url = self.baseurl+"/sections"
        result = requests.get(url, headers=self.authheader).json()
        return result

    def getdevices(self):
        url = self.baseurl+"/devices/"
        result = requests.get(url, headers=self.authheader).json()
        return result

    def requestaddress(self, subnetid, hostname, **kwargs):
        if "method" in kwargs:
            if kwargs["method"].upper() == "POST":
                method = kwargs["method"].upper()
            elif kwargs["method"].upper() == "GET":
                method = kwargs["method"].upper()
            else:
                raise Exception("This method may only use http GET and POST methods")
        else:
            method = "GET"

        if "devicetype" in kwargs:
            self.devicetype = kwargs["devicetype"]
        else:
            self.devicetype = "unspecified"

        url = self.baseurl+"/addresses/first_free/{}/".format(subnetid)
        payload = {
            "hostname": hostname,
            "custom_deviceType": self.devicetype,
        }

        if method == "POST":
            result = requests.post(url, data=payload, headers=self.authheader).json()
        else:
            result = requests.get(url, headers=self.authheader).json()
        return result