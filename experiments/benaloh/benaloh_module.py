from gumby.experiment import experiment_callback
from gumby.modules.community_experiment_module import CommunityExperimentModule
from gumby.modules.community_launcher import CommunityLauncher
from gumby.modules.experiment_module import static_module
from gumby.modules.isolated_community_loader import IsolatedCommunityLoader

from .benaloh_community import BenalohCommunity


class BenalohCommunityLoader(IsolatedCommunityLoader):
    """
    This provides the capability to run your communities in an isolated fashion.
    You can include multiple launchers here.
    """

    def __init__(self, session_id):
        super(BenalohCommunityLoader, self).__init__(session_id)
        self.set_launcher(BenalohCommunityLauncher())


class BenalohCommunityLauncher(CommunityLauncher):
    """
    This class forwards all the information Dispersy needs to launch our community.
    """
    def get_community_class(self):
        return BenalohCommunity

    def get_my_member(self, dispersy, session):
        return dispersy.get_new_member()

    def get_kwargs(self, session):
        return {}


@static_module
class BenalohModule(CommunityExperimentModule):
    """
    This is the module we reference through the scenario (note @static_module).
    All of the functionality we want to expose to the scenario is marked `@experiment_callback`.
    """
    def __init__(self, experiment):
        super(BenalohModule, self).__init__(experiment, BenalohCommunity)
        self.dispersy_provider.custom_community_loader = BenalohCommunityLoader(self.dispersy_provider.session_id)

    @experiment_callback
    def share_local(self):
        self.community.share_local()

    @experiment_callback
    def share_subset_sum(self):
        self.community.share_subset_sum()

    @experiment_callback
    def print_local_value(self):
        print "My secret value is", self.community.my_secret_share

    @experiment_callback
    def print_total_sum(self):
        print "My computed sum is", self.community.total_sum
