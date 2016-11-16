#!/usr/bin/env python2

from os import path
from sys import path as pythonpath

from twisted.internet.task import LoopingCall

from gumby.experiments.dispersyclient import main
from gumby.experiments.TriblerDispersyClient import TriblerDispersyExperimentScriptClient
from posix import environ


# TODO(emilon): Fix this crap
pythonpath.append(path.abspath(path.join(path.dirname(__file__), '..', '..', '..', "./tribler")))


class TunnelClient(TriblerDispersyExperimentScriptClient):

    def __init__(self, *argv, **kwargs):
        from Tribler.community.tunnel.pooled_tunnel_community import TestPooledTunnelCommunity
        super(TunnelClient, self).__init__(*argv, **kwargs)
        self.community_class = TestPooledTunnelCommunity
        self.master_private_key = None
        self.master_key = "3081a7301006072a8648ce3d020106052b810400270381920004073e6d578d7d9293bc45f00c07104f06b93b2223053e59aaaef1081f46e4b62f32812792bac56cff25edd7427d6e708dd1fe54aa4db767a1ed9bfac9d898ff574ffc7a629d7e811304d9f1bd4d8bb7a1a650a83c2e212ec3d85184f49b8b104ba2312450fcc74311e13285ed54e14a9ab4773c8a65b20e0eab1bc8732f8a3b07bd13659e78753aafd353aa38918817e3".decode("HEX")

    def init_community(self, become_exitnode=False):
        from Tribler.community.tunnel.tunnel_community import TunnelSettings
        tunnel_settings = TunnelSettings()
        tunnel_settings.max_circuits = 0
        tunnel_settings.socks_listen_ports = [23000 + (100 * (self.scenario_runner._peernumber)) + i for i in range(5)]
        tunnel_settings.become_exitnode = True if become_exitnode else False

        self.set_community_kwarg('settings', tunnel_settings)

        self.monitor_circuits_lc = None
        self._prev_scenario_statistics = {}

    def registerCallbacks(self):
        super(TunnelClient, self).registerCallbacks()
        self.scenario_runner.register(self.build_circuits, 'build_circuits')
        self.scenario_runner.register(self.init_community, 'init_community')

    def build_circuits(self):
        self._logger.info("build_circuits")
        self._community.settings.max_circuits = 8

    def setup_session_config(self):
        config = super(TunnelClient, self).setup_session_config()

        config.set_tunnel_community_enabled(False)

        return config

    def online(self):
        self.set_community_kwarg('tribler_session', self.session)
        super(TunnelClient, self).online()
        if not self.monitor_circuits_lc:
            self.monitor_circuits_lc = lc = LoopingCall(self.monitor_circuits)
            lc.start(5.0, now=True)

    def offline(self):
        super(TunnelClient, self).offline()
        if self.monitor_circuits_lc:
            self.monitor_circuits_lc.stop()
            self.monitor_circuits_lc = None

    def get_my_member(self):
        return self._dispersy.get_new_member(u"curve25519")

    def monitor_circuits(self):
        nr_circuits = len(self._community.active_data_circuits()) if self._community else 0
        self._prev_scenario_statistics = self.print_on_change("scenario-statistics",
                                                              self._prev_scenario_statistics,
                                                              {'nr_circuits': nr_circuits})

if __name__ == '__main__':
    TunnelClient.scenario_file = environ.get('SCENARIO_FILE', 'tunnel_pooled.scenario')
    main(TunnelClient)
