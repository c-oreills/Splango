from django.conf import settings

from logging import getLogger

from splango.models import Experiment, Enrollment, GoalRecord

logger = getLogger(__name__)

SPLANGO_QUEUED_UPDATES = "SPLANGO_QUEUED_UPDATES"

# borrowed from debug_toolbar
_HTML_TYPES = ('text/html', 'application/xhtml+xml')

# borrowed from debug_toolbar
def replace_insensitive(string, target, replacement):
    """
    Similar to string.replace() but is case insensitive
    Code borrowed from: http://forums.devshed.com/python-programming-11/case-insensitive-string-replace-490921.html
    """
    no_case = string.lower()
    index = no_case.rfind(target.lower())
    if index >= 0:
        return string[:index] + replacement + string[index + len(target):]
    else: # no results so return the original string
        return string


class RequestExperimentManager:
    def __init__(self, request):
        #logger.debug("REM init")
        self.request = request
        self.queued_actions = []

    def enqueue(self, action, params):
        self.queued_actions.append( (action, params) )

    def process_from_queue(self, action, params):
        logger.info("dequeued: %s (%s)" % (str(action), repr(params)))

        if action == "enroll":
            exp = Experiment.objects.get(name=params["exp_name"])
            exp.enroll_user_as_variant(self.request.user,
                                          params["variant"])

        elif action == "log_goal":
            g = GoalRecord.record(self.request.user, 
                                  params["goal_name"], 
                                  params["request_info"],
                                  extra=params.get("extra"))

            logger.info("goal! %s" % str(g))


        else:
            raise RuntimeError("Unknown queue action '%s'." % action)

    def finish(self, response):
        # run anything in my queue
        for (action, params) in self.queued_actions:
            self.process_from_queue(action, params)
        self.queued_actions = []

        return response
        

    def get_variant(self, exp_name, enroll=False):
        try:
            exp = Experiment.objects.get(name=exp_name)
        except Experiment.DoesNotExist:
            logger.warning("No experiment called %s" % (exp_name,))
            return None

        user = self.request.user

        enrollment = exp.get_variant_for(user, enroll)
        if enrollment is not None:
            var = enrollment.variant
            logger.info("got variant %s for user %s" % (var, user))
        else:
            var = None
            logger.info("No variant for user %s" % (user,))
        return var

    def log_goal(self, goal_name, extra=None):
        request_info = GoalRecord.extract_request_info(self.request)

        self.enqueue("log_goal", { "goal_name": goal_name,
                                   "request_info": request_info,
                                   "extra": extra })
