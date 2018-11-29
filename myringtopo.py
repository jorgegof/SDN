"""
Custom ring topology

sudo mn --custom ./myringtopo.py --topo myringtopo --mac --switch ovsk --controller remote
"""

from mininet.topo import Topo

class MyRingTopo (Topo) :
    "Simple Ring Topology with one host for each switch"
    def __init__(self,n=4):
        super(MyRingTopo,self).__init__();
        hosts = [ self.addHost( 'h%s' % (h+1) ) for h in range(n) ]
        switches = [ self.addSwitch( 's%s' % (s+1) ) for s in range(n) ]
        for i in range(n):
            self.addLink(hosts[i], switches[i])
        for i in range(n):
            j = (i + 1) % n
            self.addLink(switches[i], switches[j])

"The following line allows users to pass --topo myringtopo from command line"
topos = { "myringtopo" : (lambda n: MyRingTopo(n))}
