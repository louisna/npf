import os
import random
import sys
import re
import socket
import time

from npf.executor.localexecutor import LocalExecutor
from npf.executor.sshexecutor import SSHExecutor
from npf.variable import Variable,get_bool
from npf.nic import NIC
from npf.executor.executor import Executor
from npf import npf


class Node:
    _nodes = {}

    def __init__(self, name, executor : Executor, tags):
        self.executor = executor
        self.name = name
        self._nics = []
        self.tags = []
        self.nfs = True
        self.addr = 'localhost'
        self.port = 22
        self.arch = ''
        self.active_nics = range(32)
        self.multi = None
        self.mode = "bash"

        # Always fill 32 random nics address that will be overwriten by config eventually
        self._gen_random_nics()

        clusterFileName = 'cluster/' + name + ('.node' if not name.endswith(".node") else "")
        try:
            clusterFilePath = npf.find_local(clusterFileName, critical=False)

            f = open(clusterFilePath, 'r')
            for i, line in enumerate(f):
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("//"):
                    continue
                match = re.match(r'((?P<tag>[a-zA-Z]+[a-zA-Z0-9]*):)?(?P<nic_idx>[0-9]+):(?P<type>' + NIC.TYPES + ')=(?P<val>[a-z0-9:_.]*)', line,
                                 re.IGNORECASE)
                if match:
                    if match.group('tag') and not match.group('tag') in tags:
                        continue
                    self._nics[int(match.group('nic_idx'))][match.group('type')] = match.group('val')
                    continue
                match = re.match(r'(?P<var>' + Variable.ALLOWED_NODE_VARS + ')=(?P<val>.*)', line,
                                 re.IGNORECASE)
                if match:
                    if match.group('var') == 'nfs':
                        self.nfs = get_bool(match.group('val'))
                    setattr(executor, match.group('var'), match.group('val'))
                    continue
                raise Exception("%s:%d : Unknown node config line %s" % (clusterFilePath, i, line))
            self.parsed = True
        except FileNotFoundError as e:
            print("%s could not be found, we will connect to %s with SSH using default parameters" % (clusterFilePath,name))
            self.parsed = False


    def get_nic(self, nic_idx):
        if nic_idx >= len(self.active_nics):
            raise Exception("ERROR: node %s has no nic number %d" % (self.name, nic_idx))

        return self._nics[self.active_nics[nic_idx]]

    def get_name(self):
        return self.name

    def experiment_path(self):
        return (self.executor.path) if self.executor.path else npf.experiment_path()

    @staticmethod
    def _addr_gen():
        mac = [0xAE, 0xAA, 0xAA,
               random.randint(0x01, 0x7f),
               random.randint(0x01, 0xff),
               random.randint(0x01, 0xfe)]
        macaddr = ':'.join(map(lambda x: "%02x" % x, mac))
        ip = [10, mac[3], mac[4], mac[5]]
        ipaddr = '.'.join(map(lambda x: "%d" % x, ip))
        return macaddr, ipaddr

    def _gen_random_nics(self):
        for i in range(32):
            mac, ip = self._addr_gen()
            nic = NIC(i, mac, ip, "eth%d" % i)
            self._nics.append(nic)

    def _find_nics(self):
        if self.parsed:
            return
        print("Looking for NICs on %s, to avoid this message write down the configuration in cluster/%s.node" % (self.name,self.name))
        pid, out, err, ret = self.executor.exec(cmd="sudo lshw -class network -businfo -quiet", title="Listing network devices")
        if ret != 0:
            print("WARNING: %s has no configuration file and the NICs could not be found automatically. Please refer to the cluster documentation in NPF to define NIC order and addresses." % self.name)
            print(out)
            return

        header=out[:out.find('====')].splitlines()[-1]
        descpos = header.find('Description') - 1
        lines=out[out.find('===='):].splitlines()[1:]
        speeds = {}
        for line in lines:
            line = line[:descpos].strip()
            if not line:
                continue
            words = re.findall(r'\S+', line)
            if len(words) < 3:
                continue

            pid, out, err, ret = self.executor.exec(cmd="( sudo ethtool %s | grep Speed | grep -oE '[0-9]+' ) || echo '0'\ncat /sys/class/net/%s/address\n( /sbin/ifconfig %s | grep 'inet addr:' | cut -d: -f2| cut -d' ' -f1 ) || echo ''" % (words[1], words[1], words[1]), title="Getting device %s info" % words[1])

            res = out.split("\n")
            try:
                ip = res[-1].strip()
                mac = res[-2].strip()
                speed = int(res[-3].strip())
            except IndexError:
                print("Cannot find speed of %s" % words[1])
                print(out)
                speed=0
            except ValueError:
                print("Cannot parse speed of %s : %s" % (words[1], res[-3]))
                speed=0

            speeds.setdefault(speed, [])
            nic = NIC(words[0][4:], mac, ip, words[1])
            nic.speed = speed
            speeds[speed].append(nic)
        i = 0
        for speed in reversed(sorted(speeds.keys())):
            for n in speeds[speed]:
                self._nics[i] = n
                print("%d:pci=%s" % (i, n.pci))
                print("%d:ifname=%s" % (i, n.ifname))
                #print("%d:speed=%s" % (i, n.speed))
                print("%d:mac=%s" % (i, n.mac))
                print("%d:ip=%s" % (i, n.ip))
                i = i + 1


    @classmethod
    def makeLocal(cls, options, test_access = True):
        node = cls._nodes.get('localhost', None)
        if node is None:
            node = Node('localhost', LocalExecutor(), options.tags)
            cls._nodes['localhost'] = node
        node.ip = '127.0.0.1'
        if test_access:
            pid, out, err, ret = node.executor.exec(cmd="pwd && test -e "+node.experiment_path() + ".access_test")
            if ret != 0:
                raise Exception("The local executor could not find the file created at %s. Check your --experiment-path argument! Current folder : %s" % ( node.experiment_path() + ".access_test", out+err) )
        return node

    @classmethod
    def makeSSH(cls, user, addr, path, options, port=22, nfs=None):
        if path is None:
            path = os.path.abspath(npf.experiment_path())
        node = cls._nodes.get(addr, None)
        if node is not None:
            return node
        sshex = SSHExecutor(user, addr, path, port)
        node = Node(addr, sshex, options.tags)
        if nfs is not None:
            node.nfs = nfs
        cls._nodes[addr] = node

        if options.do_test and options.do_conntest:
            try:
                node.ip = socket.gethostbyname(node.executor.addr)
            except Exception as e:
                print("Could not resolve hostname '%s'" % node.executor.addr)
                raise(e)
            print("Testing connection to %s..." % node.executor.addr)
            time.sleep(0.01)
            if not node.nfs:
                print("Remote is not shared through nfs... Sending .access_test")
                assert(isinstance(node.executor, SSHExecutor))
                node.executor.sendFolder(".access_test")
            pid, out, err, ret = sshex.exec(cmd="pwd;ls -al;test -e " + ".access_test" + " && echo 'access_ok' && if ! type 'unbuffer' ; then ( ( sudo apt-get update && sudo apt-get install -y expect ) || sudo yum install -y expect ) && sudo echo 'test' ; else sudo echo 'test' ; fi", raw=True, title="SSH dependencies installation")
            out = out.strip()

            if not node.nfs:
                node.executor.deleteFolder(".access_test")
            if ret != 0:
                #Something was wrong, try first with a more basic test to help the user pinpoint the problem
                pidT, outT, errT, retT = sshex.exec(cmd="echo -n 'test'", raw=True, title="SSH echo test")
                if retT != 0 or outT.split("\n")[-1] != "test":
                    raise Exception("Could not communicate with%s node %s, got return code %d : %s" %  (" user "+ sshex.user if sshex.user else "", sshex.addr, retT, outT + errT))
                if not "access_ok" in out:
                    raise Exception("Could not find the access test file at %s. Verify the path= paramater in the cluster file and that this directory alread exists. It must match --root-path on the remote equivalent when nfs is active. If the path is not shared accross clusters, ensure you set nfs=0 in the cluster file." % sshex.path)
                if out.split("\n")[-1] != "test":
                    raise Exception("Could not communicate with user %s on node %s, unbuffer (expect package) could not be installed, or passwordless sudo is not working, got return code %d : %s" %  (sshex.user, sshex.addr, ret, out + err))
        if options.do_test:
            node._find_nics()
        return node
