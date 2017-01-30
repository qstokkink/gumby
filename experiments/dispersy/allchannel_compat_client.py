#!/usr/bin/env python2

from gumby.experiments.dispersyclient import main
from allchannel_client import AllChannelClient

class AllChannelCompatibilityClient(AllChannelClient):

    def online(self, dont_empty=False):
        super(AllChannelCompatibilityClient, self).online(dont_empty)
        for community in self._dispersy.get_communities():
            if hasattr(community, 'compatibility_mode'):
                community.compatibility_mode = False
        if hasattr(self._community, 'compatibility_mode'):
            self._community.compatibility_mode = False

    def create(self):
        super(AllChannelCompatibilityClient, self).create()
        if hasattr(self.my_channel, 'compatibility_mode'):
            self.my_channel.compatibility_mode = False

    def join(self):
        super(AllChannelCompatibilityClient, self).join()

        cid = self._community._channelcast_db.getChannelIdFromDispersyCID(None)
        self._logger.info("TRYING channel_cid = " + str(cid))
        if cid:
            self._logger.info("FOUND channel_community = " + str(self._community._get_channel_community(cid)))

if __name__ == '__main__':
    AllChannelCompatibilityClient.scenario_file = 'allchannel_1000.scenario'
    main(AllChannelCompatibilityClient)
