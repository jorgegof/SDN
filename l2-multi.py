from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller import dpset
from ryu.controller.handler import MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_0
import networkx as nx
from ryu.topology import event
from ryu.topology.api import get_switch, get_link

class SingleHub(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_0.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(SingleHub, self).__init__(*args, **kwargs)
        self.net = nx.DiGraph()
     

    def add_flow(self, datapath, in_port, actions, buffer_id=None):
        ofproto = datapath.ofproto

        match = datapath.ofproto_parser.OFPMatch(
            in_port=in_port)

        mod = datapath.ofproto_parser.OFPFlowMod(
            datapath=datapath, match=match, cookie=0,
            buffer_id=buffer_id, 
            command=ofproto.OFPFC_ADD, idle_timeout=0, hard_timeout=0,
            priority=ofproto.OFP_DEFAULT_PRIORITY,
            flags=ofproto.OFPFF_SEND_FLOW_REM, actions=actions)
        datapath.send_msg(mod)


    @set_ev_cls(dpset.EventDP, dpset.DPSET_EV_DISPATCHER)
    def datapath_handler(self, ev):
        if ev.enter:
            print "==> Add switch: sw=%d ports=%s" % (ev.dp.id, ev.ports)
            datapath_id = ev.dp.id
            self.net.add_node(datapath_id, ports=ev.ports, conn=ev.dp)
        else:
            print "==> Del switch: sw=%d" % (ev.dp.id)
            datapath_id = ev.dp.id
            self.net.remove_node(datapath_id)

        print "switch=%d entrou/saiu: %s" % (ev.dp.id, ev.enter)
        print "--> Nos no grafo atualmente:"
        for node in self.net.nodes():
            print "Node=%d" % (node)



    @set_ev_cls(event.EventSwitchEnter)
    def get_topology_data(self, ev):
        switch_list = get_switch(self, None)
        links_list = get_link(self, None)
        for link in links_list:
             self.net.add_edge(link.src.dpid, link.dst.dpid,sport=link.src.port_no, dport=link.dst.port_no)


        print "--> Arestas no grafo atualmente:"
        for n1,n2,attrs in self.net.edges(data=True):
            print "No_ori=%s No_dst=%s attrs=%s" % (n1, n2, attrs)



    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        ofp_parser = dp.ofproto_parser

        actions = [ofp_parser.OFPActionOutput(ofp.OFPP_FLOOD)]
        self.add_flow(dp, msg.in_port, actions,  msg.buffer_id)
