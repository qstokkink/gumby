#!/usr/bin/env python

# Code:
import sys
import random
import string
import yappi
import os
import logging

from os import path
from random import choice
from string import letters
from struct import pack
from sys import path as pythonpath
from tempfile import gettempdir
from time import time

from twisted.internet import reactor
from twisted.internet.task import LoopingCall
from twisted.python.log import msg
from twisted.internet.threads import deferToThread

from gumby.experiments.dispersyclient import DispersyExperimentScriptClient, main

# TODO(emilon): Fix this crap
pythonpath.append(path.abspath(path.join(path.dirname(__file__), '..', '..', '..', "./tribler")))

from Tribler.community.tunnel.tunnel_community import TunnelCommunity, TunnelSettings
from Tribler.Core.DownloadConfig import DownloadStartupConfig
from Tribler.Core.TorrentDef import TorrentDef

from Tribler.dispersy.candidate import Candidate
from Tribler.dispersy.endpoint import TUNNEL_PREFIX
from Tribler.community.tunnel.Socks5 import conversion

class TunnelClient(DispersyExperimentScriptClient):

    def __init__(self, *argv, **kwargs): 
        """Initialize the local Tunnel client
        
            We use the HiddenTunnelCommunity here because it 
            correctly initializes the dispersy meta-messages.
        """
        from Tribler.community.tunnel.hidden_community import HiddenTunnelCommunity
        DispersyExperimentScriptClient.__init__(self, *argv, **kwargs)
        self.community_class = HiddenTunnelCommunity

    def registerCallbacks(self):
        """Register scenario callbacks

                - build_circuits:   set the amount hops and circuits
                - reset_circuits:   kill all circuits
                - create_torrent:   create the torrent to be seeded by client 0
                - download:         start downloading the torrent for client 1
        """
        self.scenario_runner.register(self.build_circuits, 'build_circuits')
        self.scenario_runner.register(self.reset_circuits, 'reset_circuits')
        self.scenario_runner.register(self.send_packets, 'send_packets')
        self.scenario_runner.register(self.start_profiling, 'start_profiling')
        self.scenario_runner.register(self.stop_profiling, 'stop_profiling')
        self.scenario_runner.register(self.init_community, 'init_community')
        self.scenario_runner.register(self.start_dispersy, 'start_session') # Forward-compatability
        self.scenario_runner.register(self.identify, 'identify')

    def init_community(self):
        """Initialize the tunnel's settings

            Port ranges are mapped according to the id of the 
            current process. Note that this is done here as the
            id is not known at __init__ time.
        """
        tunnel_settings = TunnelSettings()
        tunnel_settings.max_circuits = 0
        tunnel_settings.max_packets_without_reply = 10000000
        tunnel_settings.socks_listen_ports = range(14000 + int(self.my_id)*100,14000 + int(self.my_id)*100 + 99)
        tunnel_settings.do_test = False
        tunnel_settings.become_exitnode = True if self.is_exit_node() else False
        self.set_community_kwarg('settings', tunnel_settings)

        logging.error("I became exitnode: %s" % ('True' if self.is_exit_node() else 'False'))
        logging.error("I became seednode: %s" % ('True' if self.is_head_node() else 'False'))
        logging.error("I became downloadnode: %s" % ('True' if self.is_dl_node() else 'False'))

    def is_head_node(self):
        """Is this node the main seeding node"""
        return self.scenario_runner._peernumber == 1

    def is_exit_node(self):
        """Is this node the designated exit node"""
        return self.scenario_runner._peernumber == 2

    def is_dl_node(self):
        """Is this node the downloading node"""
        return self.scenario_runner._peernumber == 3

    def identify(self):
        """Create a file that describes this node, with its name"""
        output = ""
        if self.is_head_node():
            output += "HEAD"
        if self.is_exit_node():
            output += "EXIT"
        if self.is_dl_node():
            output += "DL"
        output += ".id"
        open(output, 'w').close()

    def build_circuits(self, hops=3, count=4):
        """Increase the number of circuits to a certain count  
        """

        icount = int(count)
        ihops = int(hops)

        self.hops = ihops

        # Only the downloading node needs to actually build the circuits
        if self.is_head_node():
            self._community.settings.circuit_length = icount

            for x in range(0, icount):
                try:
                    self._community.create_circuit(ihops)
                except:
                    logger.error("FAILED TO CREATE CIRCUIT")

    def reset_circuits(self):
        """Force kill all circuits, relays and peers"""
        # Kill circuits
        keys = self._community.circuits.keys()
        for key in keys:
            self._community.remove_circuit(key, 'experiment reset')
        keys = self._community.relay_from_to.keys()
        for key in keys:
            self._community.remove_relay(key, 'experiment reset', both_sides=False)
        keys = self._community.exit_sockets.keys()
        for key in keys:
            self._community.remove_exit_socket(key, 'experiment reset')

        self._community.settings.circuit_length = 0
        self._community._statistics.msg_statistics.total_received_count = 0
    
    def online(self):
        """Bring this client online

            First curve25519 keys are generated to replace the 
            default M2Crypto keys which are otherwise used. Note
            this is required by code assertions.

            Secondly the DispersyExperimentScriptClient is brought
            online.
        """
        nkey = self._dispersy.crypto.generate_key(u"curve25519")
        self._my_member.__init__(self._dispersy, nkey, self._my_member._database_id, self._my_member._mid)

        nmkey = self._dispersy.crypto.generate_key(u"curve25519")
        self._master_member.__init__(self._dispersy, nmkey, self._master_member._database_id, self._master_member._mid)

        DispersyExperimentScriptClient.online(self)

    def send_packets(self, packets=3200):
        """Create a torrent containing random bytes
            
            Only peer 1 sends
        """
        if self.is_head_node():
            logging.error("SENDING")
            origin = ("127.0.0.1",12001) # This is us
            target = ("127.0.0.1",12002) # Send to client #2

            if len(self._community.circuits.keys()) == 0:
                logging.error("CIRCUITS NOT AVAILABLE - BAILING")
                return

            circuit_id = choice(self._community.circuits.keys())
            circuit = self._community.circuits[circuit_id]
            
            logging.error("SENDING - Constructing packets")

            length = 5
            data = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(length))

            logging.error("SENDING - Done constructing packets, starting send")
            starttime = time()
            for x in range(0, int(packets)):
                circuit.tunnel_data(target, data)
            endtime = time()
            logging.error("SENDING - Done sending packets")

            bps = (endtime - starttime)/(int(packets)*length*4) # Unicode characters consist of 4 bytes
            logging.error("SENDING - Sent %d packets" % int(packets))
            logging.error("SENDING - Sent in %f seconds" % (endtime - starttime))
            logging.error("SENDING - Done writing to statistics")

    def start_profiling(self, outputName=""):
        """Start profiling tunnel functions"""
        self.outputfile = open("profiling" + outputName + ".log", 'w')
        yappi.start()

    def stop_profiling(self):
        """Stop profiling tunnel functions"""
        yappi.stop()
        yappi_stats = yappi.get_func_stats()
        yappi_stats.sort("tsub")
        for func_stat in filter( lambda x: "Tribler/community/tunnel" in x.module, yappi_stats):
            self.outputfile.write("%10dx  %10.3fs %s\n" % (func_stat.ncall, func_stat.tsub, func_stat.full_name))
        self.outputfile.close()

if __name__ == '__main__':
    TunnelClient.scenario_file = 'tunnel_performance.scenario'
    main(TunnelClient)
