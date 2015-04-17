#!/usr/bin/env python

# Code:
import sys
import random
import string
import yappi

from os import path
from random import choice
from string import letters
from struct import pack
from sys import path as pythonpath
from tempfile import gettempdir
from time import time

from twisted.internet.task import LoopingCall
from twisted.python.log import msg

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

        self.monitor_circuits_lc = None         #The looping callback that reports the number of circuits
        self._prev_scenario_statistics = {}     #Stores previous state to track changes in the amount of circuits

    def registerCallbacks(self):
        """Initialize the tunnel's settings and register 
            scenario callbacks

            Port ranges are mapped according to the id of the 
            current process. Note that this is done here as the
            id is not known at __init__ time.

            Scenario callbacks:
                - build_circuits:   set the amount hops and circuits
                - reset_circuits:   kill all circuits
                - create_torrent:   create the torrent to be seeded by client 0
                - download:         start downloading the torrent for client 1
        """
        tunnel_settings = TunnelSettings()
        tunnel_settings.max_circuits = 0
        tunnel_settings.max_packets_without_reply = 10000000
        tunnel_settings.socks_listen_ports = range(14000 + int(self.my_id)*100,14000 + int(self.my_id)*100 + 99)
        self.set_community_kwarg('settings', tunnel_settings)

        self.scenario_runner.register(self.build_circuits, 'build_circuits')
        self.scenario_runner.register(self.reset_circuits, 'reset_circuits')
        self.scenario_runner.register(self.send_packets, 'send_packets')
	self.scenario_runner.register(self.start_profiling, 'start_profiling')
	self.scenario_runner.register(self.stop_profiling, 'stop_profiling')

    def build_circuits(self, hops=3, count=4):
        """Increase the number of circuits to a certain count

            This allows for monitoring the increase in circuits
            over time.        
        """
        msg("build_circuits")

        icount = int(count)
        ihops = int(hops)

        self._community.settings.circuit_length = icount

        for x in range(0, icount):
            self._community.create_circuit(ihops)

    def reset_circuits(self):
        """Kill all circuits, relays and peers"""
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

            Finally the looping callback to monitor the circuit
            changes is brought online.
        """
        nkey = self._dispersy.crypto.generate_key(u"curve25519")
        self._my_member.__init__(self._dispersy, nkey, self._my_member._database_id, self._my_member._mid)

        nmkey = self._dispersy.crypto.generate_key(u"curve25519")
        self._master_member.__init__(self._dispersy, nmkey, self._master_member._database_id, self._master_member._mid)

        DispersyExperimentScriptClient.online(self)
        if not self.monitor_circuits_lc:
            self.monitor_circuits_lc = lc = LoopingCall(self.monitor_circuits)
            lc.start(5.0, now=True)

    def offline(self):
        """Shut down this client

            Stops the DispersyExperimentScriptClient and the
            circuit monitoring looping callback.
        """
        DispersyExperimentScriptClient.offline(self)
        if self.monitor_circuits_lc:
            self.monitor_circuits_lc.stop()
            self.monitor_circuits_lc = None

    def monitor_circuits(self):
        """Monitor changes in the number of circuits and report these
        """
        nr_circuits = len(self._community.active_data_circuits()) if self._community else 0
        self._prev_scenario_statistics = self.print_on_change("scenario-statistics", self._prev_scenario_statistics, {'nr_circuits': nr_circuits})


    def send_packets(self, packets=1):
        """Create a torrent containing random bytes
            
            Only peer 1 sends
        """
        if int(self.my_id) == 1:
            print >>sys.stderr, "SENDING"
            origin = ("127.0.0.1",12001) # This is us
            target = ("127.0.0.1",12002) # Send to client #2
            circuit_id = choice(self._community.circuits.keys())
            circuit = self._community.circuits[circuit_id]
            
            print >>sys.stderr, "SENDING - Constructing packets"

            length = 5
            data = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(length))

            print >>sys.stderr, "SENDING - Done constructing packets, starting send"
            starttime = time()
            for x in range(0, int(packets)):
                circuit.tunnel_data(target, data)
            endtime = time()
            print >>sys.stderr, "SENDING - Done sending packets"

            bps = (endtime - starttime)/(int(packets)*length*4) # Unicode characters consist of 4 bytes
            print >>sys.stderr, "SENDING - Sent ", int(packets), " packets"
            print >>sys.stderr, "SENDING - Sent in ", (endtime - starttime), " seconds"
            self._prev_scenario_statistics = self.print_on_change("scenario-statistics", self._prev_scenario_statistics, {'send_speed': round(bps,4)})
            print >>sys.stderr, "SENDING - Done writing to statistics"

    def start_profiling(self, outputName=""):
        """Start profiling tunnel functions"""
        yappi.start()
        self.outputfile = open("profiling" + outputName + ".log", 'w')

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
