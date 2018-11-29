# ext/graphapp.py
"""
Uma aplicacao simples para demonstrar o uso do NetworkX como estrutura
de dados para mapear a topologia da rede em um grafo dirigido

Depende de openflow.discovery

Running:
    python pox.py --verbose openflow.discovery graphapp py  log --no-default  --file=/tmp/mylog.log
"""

# Importar as bibliotecas
from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.lib.revent import *
import networkx as nx

log = core.getLogger()     # logging

class graphapp (EventMixin):
    switches = None

    def __init__(self):
        self.listenTo(core.openflow)
        self.listenTo(core.openflow_discovery)
        self.net = nx.DiGraph()
        graphapp.switches = self.net

    def _handle_ConnectionUp (self, event):
        log.debug("Connection UP from %s", event.dpid)
        self.net.add_node(event.dpid, 
                conn=event.connection,
                ports=event.ofp.ports)

    def _handle_ConnectionDown(self, event):
        log.debug("Connection Down from %s", event.dpid)
        self.net.remove_node(event.dpid)

    def _handle_PacketIn (self, event):
        log.debug("Packet in from %s - does nothing..", event.dpid)

    def _handle_LinkEvent (self, event):
        l = event.link
        if event.added:
            log.debug("Link Added: %s -> %s", l.dpid1, l.dpid2)
            self.net.add_edge(l.dpid1, l.dpid2, sport=l.port1, dport=l.port2)
        else: # or you can use: if event.removed:
            log.debug("Link Removed: %s -> %s", l.dpid1, l.dpid2)
            self.net.remove_edge(l.dpid1, l.dpid2)

def launch ():
    core.openflow.miss_send_len = 1024
    core.registerNew(graphapp)
