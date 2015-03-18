#!/usr/bin/env python

# Code:
from os import path
from random import choice
from string import letters
from sys import path as pythonpath
from time import time

from twisted.internet.task import LoopingCall
from twisted.python.log import msg

from gumby.experiments.dispersyclient import DispersyExperimentScriptClient, main


# TODO(emilon): Fix this crap
pythonpath.append(path.abspath(path.join(path.dirname(__file__), '..', '..', '..', "./tribler")))

from Tribler.community.tunnel.tunnel_community import TunnelCommunity, TunnelSettings


class TunnelClient(DispersyExperimentScriptClient):

    def __init__(self, *argv, **kwargs): 
        from Tribler.community.tunnel.hidden_community import HiddenTunnelCommunity
        DispersyExperimentScriptClient.__init__(self, *argv, **kwargs)
        self.community_class = HiddenTunnelCommunity
        self.my_channel = None
        self.joined_community = None
        self.torrentindex = 1
        
        self.set_community_kwarg('tribler_session', None)

        self.monitor_circuits_lc = None
        self._prev_scenario_statistics = {}

    def registerCallbacks(self):
        tunnel_settings = TunnelSettings()
        tunnel_settings.max_circuits = 0
        tunnel_settings.socks_listen_ports = range(11000 + int(self.my_id)*100,11000 + int(self.my_id)*100 + 99)
        self.set_community_kwarg('settings', tunnel_settings)
        self.scenario_runner.register(self.build_circuits, 'build_circuits')

    def build_circuits(self):
        msg("build_circuits")
        self._community.settings.max_circuits = 8

    def online(self):
        nkey = self._dispersy.crypto.generate_key(u"curve25519")
        self._my_member.__init__(self._dispersy, nkey, self._my_member._database_id, self._my_member._mid)

        nmkey = self._dispersy.crypto.generate_key(u"curve25519")
        self._master_member.__init__(self._dispersy, nmkey, self._master_member._database_id, self._master_member._mid)

        DispersyExperimentScriptClient.online(self)
        if not self.monitor_circuits_lc:
            self.monitor_circuits_lc = lc = LoopingCall(self.monitor_circuits)
            lc.start(5.0, now=True)

    def offline(self):
        DispersyExperimentScriptClient.offline(self)
        if self.monitor_circuits_lc:
            self.monitor_circuits_lc.stop()
            self.monitor_circuits_lc = None

    def monitor_circuits(self):
        nr_circuits = len(self._community.circuits) if self._community else 0
        self._prev_scenario_statistics = self.print_on_change("scenario-statistics", self._prev_scenario_statistics, {'nr_circuits': nr_circuits})


if __name__ == '__main__':
    TunnelClient.scenario_file = 'tunnel.scenario'
    main(TunnelClient)
