#!/usr/bin/env python2

from os import path
from sys import path as pythonpath

from hiddenservices_client import HiddenServicesClient
from gumby.experiments.dispersyclient import main
from posix import environ


# TODO(emilon): Fix this crap
pythonpath.append(path.abspath(path.join(path.dirname(__file__), '..', '..', '..', "./tribler")))


class TunnelClient(HiddenServicesClient):

    def __init__(self, *argv, **kwargs):
        #from Tribler.community.tunnel.pooled_tunnel_community import PooledTunnelCommunity
        from Tribler.community.tunnel.hidden_community import HiddenTunnelCommunity
        super(TunnelClient, self).__init__(*argv, **kwargs)
        #self.community_class = PooledTunnelCommunity
        self.community_class = HiddenTunnelCommunity
        self.master_private_key = None
        self.master_key = "3081a7301006072a8648ce3d020106052b810400270381920004073e6d578d7d9293bc45f00c07104f06b93b2223053e59aaaef1081f46e4b62f32812792bac56cff25edd7427d6e708dd1fe54aa4db767a1ed9bfac9d898ff574ffc7a629d7e811304d9f1bd4d8bb7a1a650a83c2e212ec3d85184f49b8b104ba2312450fcc74311e13285ed54e14a9ab4773c8a65b20e0eab1bc8732f8a3b07bd13659e78753aafd353aa38918817e3".decode("HEX")

    def setup_session_config(self):
        config = super(TunnelClient, self).setup_session_config()

        config.set_tunnel_community_enabled(False)

        return config

if __name__ == '__main__':
    TunnelClient.scenario_file = environ.get('SCENARIO_FILE', 'hiddenservices-1-gigabyte-1-hop.scenario')
    main(TunnelClient)
