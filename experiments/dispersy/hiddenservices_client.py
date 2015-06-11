#!/usr/bin/env python
# bartercast_client.py ---
#
# Filename: hiddenservices_client.py
# Description:
# Author: Rob Ruigrok
# Maintainer:
# Created: Wed Apr 22 11:44:23 2015 (+0200)

# Commentary:
#
#
#
#

# Change Log:
#
#
#
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 3, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; see the file COPYING.  If not, write to
# the Free Software Foundation, Inc., 51 Franklin Street, Fifth
# Floor, Boston, MA 02110-1301, USA.
#
#

# Code:

from os import path

from twisted.python.log import msg
from threading import Event
import os
from gumby.experiments.TriblerDispersyClient import TriblerDispersyExperimentScriptClient,\
    BASE_DIR
from gumby.experiments.dispersyclient import main
import logging
from twisted.internet import reactor
from posix import environ


class HiddenServicesClient(TriblerDispersyExperimentScriptClient):

    def __init__(self, *argv, **kwargs):
        from Tribler.community.tunnel.hidden_community import HiddenTunnelCommunity
        TriblerDispersyExperimentScriptClient.__init__(self, *argv, **kwargs)
        self.community_class = HiddenTunnelCommunity

    def init_community(self, become_exitnode=False):
        from Tribler.community.tunnel.tunnel_community import TunnelSettings
        tunnel_settings = TunnelSettings()
        tunnel_settings.max_circuits = 0
        tunnel_settings.min_circuits = 0
        tunnel_settings.do_test = False
        tunnel_settings.become_exitnode = True if become_exitnode else False
        logging.error("I became exitnode: %s" % ('True' if become_exitnode else 'False'))

        tunnel_settings.socks_listen_ports = [23000 + (100 * self.scenario_runner._peernumber) + i for i in range(5)]

        self.set_community_kwarg('tribler_session', self.session)
        self.set_community_kwarg('settings', tunnel_settings)

    def get_my_member(self):
        return self._dispersy.get_new_member(u"curve25519")

    def start_download(self):
        from Tribler.Main.globals import DefaultDownloadStartupConfig
        defaultDLConfig = DefaultDownloadStartupConfig.getInstance()
        dscfg = defaultDLConfig.copy()
        dscfg.set_hops(1)
        dscfg.set_dest_dir(path.join(os.getcwd(), 'downloader%s' % self.session.get_dispersy_port()))

        def cb_start_download():
            from Tribler.Core.TorrentDef import TorrentDef
            from Tribler.Core.simpledefs import dlstatus_strings
            tdef = TorrentDef.load(path.join(BASE_DIR, "output", "gen.torrent"))

            def cb(ds):
                logging.error('Download infohash=%s, down=%s, progress=%s, status=%s, seedpeers=%s, candidates=%d' %
                    (tdef.get_infohash().encode('hex')[:10],
                     ds.get_current_speed('down'),
                     ds.get_progress(),
                     dlstatus_strings[ds.get_status()],
                     sum(ds.get_num_seeds_peers()),
                     sum(1 for _ in self._community.dispersy_yield_verified_candidates())))
                return 1.0, False

            download = self.session.start_download(tdef, dscfg)
            download.set_state_callback(cb, delay=1)

        self.session.uch.perform_usercallback(cb_start_download)

    def online(self, dont_empty=False):
        TriblerDispersyExperimentScriptClient.online(self, dont_empty)
        self.session.set_anon_proxy_settings(2, ("127.0.0.1", self.session.get_tunnel_community_socks5_listen_ports()))

        class FakeDHT(object):

            def __init__(self, dht_dict, mainline_dht):
                self.dht_dict = dht_dict
                self.mainline_dht = mainline_dht

            def get_peers(self, lookup_id, _, callback_f, bt_port=0):
                if bt_port != 0:
                    self.dht_dict[lookup_id] = self.dht_dict.get(lookup_id, []) + [('127.0.0.1', bt_port)]
                callback_f(lookup_id, ('127.0.0.1', 18001), None)

            def stop(self):
                self.mainline_dht.stop()

        dht_dict = {}
        logging.error("Replace pymdht with a fake one")
        self.session.lm.mainline_dht = FakeDHT(dht_dict, self.session.lm.mainline_dht)

        def monitor_downloads(dslist):
            self._community.monitor_downloads(dslist)
            return (1.0, [])
        self.session.set_download_states_callback(monitor_downloads, False)

    def setup_seeder(self):

        def cb_seeder_download():
            logging.error("Create an anonymous torrent")
            from Tribler.Core.TorrentDef import TorrentDef
            from Tribler.Core.simpledefs import dlstatus_strings
            tdef = TorrentDef()
            tdef.add_content(path.join(BASE_DIR, "tribler", "Tribler", "Test", "data", "video.avi"))
            tdef.set_tracker("http://fake.net/announce")
            tdef.set_private()  # disable dht
            tdef.set_anonymous(True)
            tdef.finalize()
            tdef_file = path.join(BASE_DIR, "output", "gen.torrent")
            tdef.save(tdef_file)

            logging.error("Start seeding")
            from Tribler.Main.globals import DefaultDownloadStartupConfig
            defaultDLConfig = DefaultDownloadStartupConfig.getInstance()
            dscfg = defaultDLConfig.copy()
            dscfg.set_dest_dir(path.join(BASE_DIR, "tribler", "Tribler", "Test", "data"))
            dscfg.set_hops(1)

            def cb(ds):
                logging.error('Seed infohash=%s, up=%s, progress=%s, status=%s, seedpeers=%s, candidates=%d' %
                    (tdef.get_infohash().encode('hex')[:10],
                     ds.get_current_speed('up'),
                     ds.get_progress(),
                     dlstatus_strings[ds.get_status()],
                     sum(ds.get_num_seeds_peers()),
                     sum(1 for _ in self._community.dispersy_yield_verified_candidates())))
                return 1.0, False

            download = self.session.start_download(tdef, dscfg)
            download.set_state_callback(cb, delay=1)

        logging.error("Call to cb_seeder_download")
        reactor.callInThread(cb_seeder_download)

        # Wait for the introduction point to announce itself to the DHT
        dht = Event()

        def dht_announce(info_hash, community):
            from Tribler.Core.DecentralizedTracking.pymdht.core.identifier import Id

            def cb_dht(info_hash, peers, source):
                self._logger.debug("announced %s to the DHT", info_hash.encode('hex'))
                dht.set()
            port = community.session.get_dispersy_port()
            community.session.lm.mainline_dht.get_peers(info_hash, Id(info_hash), cb_dht, bt_port=port)

        self._community.dht_announce = lambda ih, com = self._community: dht_announce(ih, com)

    def registerCallbacks(self):
        TriblerDispersyExperimentScriptClient.registerCallbacks(self)
        self.scenario_runner.register(self.setup_seeder, 'setup_seeder')
        self.scenario_runner.register(self.start_download, 'start_download')
        self.scenario_runner.register(self.init_community, 'init_community')

if __name__ == '__main__':
    HiddenServicesClient.scenario_file = environ.get('SCENARIO_FILE', 'hiddenservices10.scenario')
    main(HiddenServicesClient)
