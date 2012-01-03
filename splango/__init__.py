from django.conf import settings

from logging import getLogger

from splango.models import Subject, Experiment, Enrollment, GoalRecord

logger = getLogger(__name__)

SPLANGO_SUBJECT = "SPLANGO_SUBJECT"
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
        self.user_at_init = request.user
        self.queued_actions = []

    def enqueue(self, action, params):
        self.queued_actions.append( (action, params) )

    def process_from_queue(self, action, params):
        logger.info("dequeued: %s (%s)" % (str(action), repr(params)))

        if action == "enroll":
            exp = Experiment.objects.get(name=params["exp_name"])
            exp.enroll_subject_as_variant(self.get_subject(),
                                          params["variant"])

        elif action == "log_goal":
            g = GoalRecord.record(self.get_subject(), 
                                  params["goal_name"], 
                                  params["request_info"],
                                  extra=params.get("extra"))

            logger.info("goal! %s" % str(g))


        else:
            raise RuntimeError("Unknown queue action '%s'." % action)

    def finish(self, response):
        curuser = self.request.user

        if self.user_at_init != curuser:
            logger.info("user status changed over request: %s --> %s" % (str(self.user_at_init), str(curuser)))

            if not(curuser.is_authenticated()):
                # User logged out. It's a new session, nothing special.
                pass

            else:
                # User has just logged in (or registered).
                # We'll merge the session's current Subject with 
                # an existing Subject for this user, if exists,
                # or simply set the subject.registered_as field.

                old_subject = self.request.session.get(SPLANGO_SUBJECT)

                try:
                    existing_subject = Subject.objects.get(registered_as=curuser)
                    # there is an existing registered subject!
                    if old_subject and old_subject.id != existing_subject.id:
                        # merge old subject's activity into new
                        old_subject.merge_into(existing_subject)

                    # whether we had an old_subject or not, we must 
                    # set session to use our existing_subject
                    self.request.session[SPLANGO_SUBJECT] = existing_subject

                except Subject.DoesNotExist:
                    # promote current subject to registered!
                    sub = self.get_subject()
                    sub.registered_as = curuser
                    sub.save()

        # run anything in my queue
        for (action, params) in self.queued_actions:
            self.process_from_queue(action, params)
        self.queued_actions = []

        return response
        
    def get_subject(self):
        sub = self.request.session.get(SPLANGO_SUBJECT)

        if not sub:
            sub = self.request.session[SPLANGO_SUBJECT] = Subject()
            sub.save()
            logger.info("created subject: %s" % str(sub))
        
        return sub

    def get_variant(self, exp_name, enroll=False):
        try:
            exp = Experiment.objects.get(name=exp_name)
        except Experiment.DoesNotExist:
            logger.warning("No experiment called %s" % (exp_name,))
            return None

        sub = self.get_subject()

        sub_enrollment = exp.get_variant_for(sub, enroll)
        if sub_enrollment is not None:
            var = sub_enrollment.variant
            logger.info("got variant %s for subject %s" % (var,sub))
        else:
            var = None
            logger.info("No variant for subject %s" % (sub,))
        return var

    def log_goal(self, goal_name, extra=None):

        request_info = GoalRecord.extract_request_info(self.request)

        self.enqueue("log_goal", { "goal_name": goal_name,
                                   "request_info": request_info,
                                   "extra": extra })
