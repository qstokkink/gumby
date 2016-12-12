#!/usr/bin/env python2

import logging

from os import environ, path
from sys import path as pythonpath

from twisted.internet import reactor, threads

from gumby.experiments.dispersy_community_syncer import DispersyCommunitySyncer
from gumby.experiments.dispersyclient import main
from gumby.experiments.TriblerDispersyClient import BASE_DIR, TriblerDispersyExperimentScriptClient

# TODO(emilon): Fix this crap
pythonpath.append(path.abspath(path.join(path.dirname(__file__), '..', '..', '..', "./tribler")))

logging.basicConfig(level=logging.WARNING)

class DAS5NakedClient(TriblerDispersyExperimentScriptClient):

    def __init__(self, *argv, **kwargs):
        from Tribler.community.tunnel.hidden_community import HiddenTunnelCommunity
        super(DAS5NakedClient, self).__init__(*argv, **kwargs)
        self.community_class = HiddenTunnelCommunity
        self.candidate_ips = []
        self.peer_count = 2  # TODO
        self.dcs = DispersyCommunitySyncer(self.peer_count)
        self.testfilesize = 1024
        self.speed_download = {'download': 0}
        self.speed_upload = {'upload': 0}
        self.progress = {'progress': 0}

        self.set_community_kwarg('tribler_session', self.session)

    def get_my_member(self):
        return self._dispersy.get_new_member(u"curve25519")

    def log_progress_stats(self, ds):
        new_speed_download = {'download': ds.get_current_speed('down')}
        self.speed_download = self.print_on_change("speed-download",
                                                   self.speed_download,
                                                   new_speed_download)

        new_progress = {'progress': ds.get_progress() * 100}
        self.progress = self.print_on_change("progress-percentage",
                                             self.progress,
                                             new_progress)

        new_speed_upload = {'upload': ds.get_current_speed('up')}
        self.speed_upload = self.print_on_change("speed-upload",
                                                 self.speed_upload,
                                                 new_speed_upload)

    def registerCallbacks(self):
        super(DAS5NakedClient, self).registerCallbacks()
        self.scenario_runner.register(self.collect_peers, 'collect_peers')
        self.scenario_runner.register(self.setup_seeder, 'setup_seeder')

    def collect_peers(self):
        def wait_for_members():
            candidates = threads.blockingCallFromThread(reactor, self.dcs.start)
            self.candidate_ips = [c.sock_addr[0] for c in candidates]
            logging.critical("GOT CANDIDATE IPS: " + str(self.candidate_ips))

        reactor.callInThread(wait_for_members)

    def setup_session_config(self):
        config = super(DAS5NakedClient, self).setup_session_config()

        config.set_tunnel_community_enabled(False)

        return config

    def create_test_torrent(self, filename=''):
        logging.error("Create %s download" % filename)
        filename = path.join(BASE_DIR, "tribler", str(self.scenario_file) + str(filename))
        logging.info("Creating torrent..")
        with open(filename, 'wb') as fp:
            fp.write("0" * self.testfilesize)

        logging.error("Create a torrent")
        from Tribler.Core.TorrentDef import TorrentDef
        tdef = TorrentDef()
        tdef.add_content(filename)
        tdef.set_tracker("http://localhost/announce")
        tdef.finalize()
        tdef_file = path.join(BASE_DIR, "output", "gen.torrent")
        tdef.save(tdef_file)
        return tdef

    def setup_seeder(self, filename, hops=0):
        hops = int(hops)
        self.annotate('start seeding %d hop(s)' % hops)

        def cb_seeder_download():
            tdef = self.create_test_torrent(filename)

            logging.error("Start seeding")

            from Tribler.Core.DownloadConfig import DefaultDownloadStartupConfig
            defaultDLConfig = DefaultDownloadStartupConfig.getInstance()
            dscfg = defaultDLConfig.copy()
            dscfg.set_dest_dir(path.join(BASE_DIR, "tribler"))
            dscfg.set_hops(hops)

            def cb(ds):
                from Tribler.Core.simpledefs import dlstatus_strings
                logging.error('Seed infohash=%s, hops=%d, down=%d, up=%d, progress=%s, status=%s, peers=%s, cand=%d' %
                              (tdef.get_infohash().encode('hex')[:5],
                               hops,
                               ds.get_current_speed('down'),
                               ds.get_current_speed('up'),
                               ds.get_progress(),
                               dlstatus_strings[ds.get_status()],
                               sum(ds.get_num_seeds_peers()),
                               sum(1 for _ in self._community.dispersy_yield_verified_candidates())))

                self.log_progress_stats(ds)

                return 1.0, False

            download = self.session.start_download_from_tdef(tdef, dscfg)
            download.set_state_callback(cb)

            reactor.callFromThread(self.dcs.community.share, {"FILE_INFOHASH": download.get_def().get_infohash().encode("HEX")})

            session_port = self.session.get_listen_port()
            seeding_port = download.ltmgr.get_session().listen_port()
            for key in download.ltmgr.upnp_mapping_dict.keys() + [(seeding_port, "Hi mom!"), (session_port, "Hi mom!")]:
                seeding_port, _ = key
                logging.critical("SEEDING ON PORT: " + str(seeding_port))
                reactor.callFromThread(self.dcs.community.share, {"SEEDING_PORT": seeding_port})

        logging.error("Call to cb_seeder_download")
        reactor.callInThread(cb_seeder_download)

if __name__ == '__main__':
    DAS5NakedClient.scenario_file = environ.get('SCENARIO_FILE', 'das5_tunnel_pooled.scenario')
    main(DAS5NakedClient)