from allchannel_client import AllChannelClient

class AllChannelCompatibilityClient(AllChannelClient):

    def join(self):
        if self.join_lc:
            self._community.compatibility_mode = False
            self.my_channel.compatibility_mode = False
        super(AllChannelCompatibilityClient, self).join()
