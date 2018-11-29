# Copyright (C) Italo Valcy S Brito <italovalcy@ufba.br>
#
# Simple multiswitch L2 application
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from ryu.base import app_manager
from ryu.controller import ofp_event,dpset
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.topology import event, switches
from ryu.topology.api import get_switch, get_link
import networkx as nx


class SimpleSwitch13(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(SimpleSwitch13, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.mac_to_sw = {}
        self.net = nx.DiGraph()
        self.topology_api_app = self

    @set_ev_cls(dpset.EventDP, dpset.DPSET_EV_DISPATCHER)
    def datapath_handler(self, ev):
        if ev.enter:
            ports = []
            for p in ev.ports:
                if p.port_no != ev.dp.ofproto.OFPP_LOCAL:
                    ports.append(p.port_no)
            self.net.add_node(ev.dp.id, {'all_ports': ev.ports, 'ports': ports, 'conn': ev.dp})
            self.logger.debug('OFPStateChange switch entered: datapath_id=0x%016x ports=%s' % (ev.dp.id, ev.ports))
        else:
            self.logger.debug('OFPStateChange switch leaves: datapath_id=0x%016x' % (ev.dp.id))
            self.net.remove_node(ev.dp.id)


    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # install table-miss flow entry
        #
        # We specify NO BUFFER to max_len of the output action due to
        # OVS bug. At this moment, if we specify a lesser number, e.g.,
        # 128, OVS will send Packet-In with invalid buffer_id and
        # truncated packet data. In that case, we cannot output packets
        # correctly.  The bug has been fixed in OVS v2.1.0.
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst)
        datapath.send_msg(mod)

    @set_ev_cls(event.EventSwitchEnter)
    def get_topology_data(self, ev):
        switch_list = get_switch(self.topology_api_app, None)
        switches=[switch.dp.id for switch in switch_list]
        links_list = get_link(self.topology_api_app, None)
        links = []
        backbone_ports = {}
        for link in links_list:
            links.append((link.src.dpid,link.dst.dpid,{
                'sport':link.src.port_no, 'dport':link.dst.port_no}))
            backbone_ports.setdefault(link.src.dpid, [])
            backbone_ports[link.src.dpid].append(link.src.port_no)
        self.logger.debug("add_nodes: %s" % (switches))
        self.net.add_nodes_from(switches)
        self.logger.debug("add_edges: %s" % (links))
        self.net.add_edges_from(links)
        for sw in backbone_ports:
            self.net.node[sw]['backbone_ports'] = backbone_ports[sw]
            self.logger.debug("backbone_ports[%s] = %s " % (sw, backbone_ports[sw]))


    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        # If you hit this you might want to increase
        # the "miss_send_length" of your switch
        if ev.msg.msg_len < ev.msg.total_len:
            self.logger.debug("packet truncated: only %s of %s bytes",
                              ev.msg.msg_len, ev.msg.total_len)
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        dst = eth.dst
        src = eth.src

        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        self.logger.info("packet in %s %s %s %s", dpid, src, dst, in_port)

        # learn a mac address to avoid FLOOD next time, except if received 
        # in backbone port
        if in_port not in self.net.node[dpid]['backbone_ports']:
            self.mac_to_port[dpid][src] = in_port
            self.mac_to_sw[src] = [dpid, in_port]

        if dst in self.mac_to_sw:
            dst_sw = self.mac_to_sw[dst][0]
            out_port = self.mac_to_sw[dst][1]
        else:
            dst_sw = None

        # if destination switch (dst_sw) is known, then we just search for a 
        # path on the graph and install a flow along this path. Otherwise, we 
        # flood the packet into the access ports for all switches
        if dst_sw:
            path = nx.shortest_path(self.net, dpid, dst_sw)
            self.logger.info("==> path(src=%s,dst=%s): %s", dpid, dst_sw, path)
            for i in range(len(path)-1,-1,-1):
                sw = path[i]
                buff_id = None
                if i == 0: # first switch
                    match_in_port = in_port
                    buff_id = msg.buffer_id
                else:
                    prev_sw = path[i-1]
                    match_in_port = self.net.edge[prev_sw][sw]['dport']
                if i == len(path)-1:
                    action_out_port = out_port
                else:
                    next_sw = path[i+1]
                    action_out_port = self.net.edge[sw][next_sw]['sport']
                self.logger.info("==> add_flow sw=%s match_in_port=%s action_out_port=%s", sw, match_in_port, action_out_port)
                match = parser.OFPMatch(in_port=match_in_port, 
                        eth_dst=dst, eth_src=src)
                actions = [parser.OFPActionOutput(action_out_port)]
                self.add_flow(self.net.node[sw]['conn'], 1, match, actions, buff_id)
        else:
            self.logger.info("===> Destino nao conhecido")
            for sw in self.net.nodes():
                access_ports = set(self.net.node[sw]['ports']) - set(self.net.node[sw]['backbone_ports'])
                self.logger.info("=====> sw=%s ports=%s backbone_ports=%s access_ports=%s" %
                        (sw, self.net.node[sw]['ports'],  self.net.node[sw]['backbone_ports'], access_ports))
                actions = []
                for p in access_ports:
                    actions = [parser.OFPActionOutput(p)]
                data = msg.data
                datapath = self.net.node[sw]['conn']
                out = parser.OFPPacketOut(datapath=datapath, 
                        in_port = ofproto.OFPP_LOCAL,
                        buffer_id=ofproto.OFP_NO_BUFFER,
                        actions=actions, data=data)
                datapath.send_msg(out)
