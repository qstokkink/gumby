#!/usr/bin/env python2

from gumby.experiments.dispersyclient import main
from allchannel_client import AllChannelClient

class AllChannelCompatibilityClient(AllChannelClient):

    def create(self):
        super(AllChannelCompatibilityClient, self).create()
        self.my_channel.compatibility_mode = False

    def join(self):
        super(AllChannelCompatibilityClient, self).join()
        if self.join_lc:
            self._community.compatibility_mode = False

if __name__ == '__main__':
    AllChannelCompatibilityClient.scenario_file = 'allchannel_1000.scenario'
    main(AllChannelCompatibilityClient)
