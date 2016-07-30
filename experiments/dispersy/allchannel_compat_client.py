#!/usr/bin/env python2

from gumby.experiments.dispersyclient import main
from allchannel_client import AllChannelClient

class AllChannelCompatibilityClient(AllChannelClient):

    def join(self):
        super(AllChannelCompatibilityClient, self).join()

        cid = self._community._channelcast_db.getChannelIdFromDispersyCID(None)
        self._logger.info("TRYING channel_cid = " + str(cid))
        if cid:
            self._logger.info("FOUND channel_community = " + str(self._community._get_channel_community(cid)))

if __name__ == '__main__':
    AllChannelCompatibilityClient.scenario_file = 'allchannel_1000.scenario'
    main(AllChannelCompatibilityClient)
