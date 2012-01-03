from django.db import models
from django.contrib.auth.models import User

import logging

#from django.db.models import Avg, Max, Min, Count

import random

_NAME_LENGTH=30

class Goal(models.Model):
    name = models.CharField(max_length=_NAME_LENGTH, primary_key=True)
    created = models.DateTimeField(auto_now_add=True)

    def __unicode__(self):
        return self.name

class GoalRecord(models.Model):
    goal = models.ForeignKey(Goal)
    user = models.ForeignKey(User)

    created = models.DateTimeField(auto_now_add=True, db_index=True)
    req_HTTP_REFERER = models.CharField(max_length=255, null=True, blank=True)
    req_REMOTE_ADDR = models.IPAddressField(null=True, blank=True)
    req_path = models.CharField(max_length=255, null=True, blank=True)

    extra = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        unique_together= (('user', 'goal'),)
        # never record the same goal twice for a given user

    @staticmethod
    def extract_request_info(request):
        return dict(
            req_HTTP_REFERER=request.META.get("HTTP_REFERER","")[:255],
            req_REMOTE_ADDR=request.META["REMOTE_ADDR"],
            req_path=request.path[:255])

    @classmethod
    def record(cls, user, goalname, request_info, extra=None):
        logging.warn("Splango:goalrecord %r" % [user, goalname, request_info, extra])
        goal, created = Goal.objects.get_or_create(name=goalname)

        gr,created = cls.objects.get_or_create(user=user, 
                                               goal=goal,
                                               defaults=request_info)

        if not(created) and not(gr.extra) and extra:
            # add my extra info to the existing goal record
            gr.extra = extra
            gr.save()

        return gr

    @classmethod
    def record_user_goal(cls, user, goalname):
        cls.record(user, goalname, {})

    def __unicode__(self):
        return u"%s by user #%d" % (self.goal, self.user_id)


class Enrollment(models.Model):
    """Identifies which variant a user is assigned to in a given
    experiment."""
    user = models.ForeignKey(User, editable=False)
    experiment = models.ForeignKey('splango.Experiment', editable=False)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    variant = models.CharField(max_length=_NAME_LENGTH)
    
    class Meta:
        unique_together= (('user', 'experiment'),)

    def __unicode__(self):
        return u"experiment '%s' user #%d -- variant %s" % (self.experiment.name, self.user_id, self.variant)


class Experiment(models.Model):
    """A named experiment."""
    name = models.CharField(max_length=_NAME_LENGTH, primary_key=True)
    variants = models.CharField(max_length=100, help_text="List variants separated by commas")
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    is_enrollable = models.BooleanField(default=False)

    users = models.ManyToManyField(User, through=Enrollment)
    
    def __unicode__(self):
        return self.name

    def set_variants(self, variantlist):
        self.variants = ",".join(variantlist)

    def get_variants(self):
        return [ x for x in self.variants.split(",") if x ]

    def get_random_variant(self):
        return random.choice(self.get_variants())

    def get_variant_for(self, user, enroll=False):
        if enroll:
            if not self.is_enrollable:
                raise Exception('Experiment %s is not enrollable' % (self.name))
            user_enrollment, created = Enrollment.objects.get_or_create(
                user=user,
                experiment=self,
                defaults={
                    "variant": self.get_random_variant()
                    })
            return user_enrollment
        else:
            try:
                user_enrollment = Enrollment.objects.get(
                    user=user,
                    experiment=self)
            except Enrollment.DoesNotExist:
                return None
            else:
                return user_enrollment

    def enroll_user_as_variant(self, user, variant):
        if not self.is_enrollable:
            raise Exception('Experiment %s is not enrollable' % (self.name))
        enrollment, _ = Enrollment.objects.get_or_create(
            user=user,
            experiment=self,
            defaults={
                "variant": variant
                })
        return enrollment

    @classmethod
    def declare(cls, name, variants):
        e,created = cls.objects.get_or_create(name=name, 
                                              defaults={
                "variants":",".join(variants) })
        return e


class ExperimentReport(models.Model):
    """A report on the results of an experiment."""
    experiment = models.ForeignKey(Experiment)
    title = models.CharField(max_length=100, blank=True)
    funnel = models.TextField(help_text="List the goals, in order and one per line, that constitute this report's funnel.")

    def __unicode__(self):
        return u"%s - %s" % (self.title, self.experiment.name)

    def get_funnel_goals(self):
        return [ x.strip() for x in self.funnel.split("\n") if x ]
    
    def generate(self):
        result = []
        exp = self.experiment

        variants = self.experiment.get_variants()
        goals = self.get_funnel_goals()

        # count initial participation
        variant_counts = []

        for v in variants:
            variant_counts.append(
                dict(val=Enrollment.objects.filter(experiment=exp, variant=v).count(),
                     variant_name=v,
                     pct=None,
                     pct_cumulative=1,
                     pct_cumulative_round=100))

        result.append({ "goal": None, 
                        "variant_names": variants,
                        "variant_counts": variant_counts })

        for previ, goal in enumerate(goals):
            try:
                g = Goal.objects.get(name=goal)
            except Goal.DoesNotExist:
                logging.warn("Splango: No such goal <<%s>>." % goal)
                g = None

            variant_counts = []

            for vi, v in enumerate(variants):

                if g:
                    vcount = Enrollment.objects.filter(experiment=exp, 
                                                       variant=v, 
                                                       user__goals=g
                                                       ).count()

                    prev_count = result[previ]["variant_counts"][vi]["val"]

                    if prev_count == 0:
                        pct = 0
                    else:
                        pct = float(vcount) / float(prev_count)

                else:
                    vcount = 0
                    pct = 0

                pct_cumulative = pct*result[previ]["variant_counts"][vi]["pct_cumulative"]

                variant_counts.append(dict(val=vcount,
                                           variant_name=variants[vi],
                                           pct=pct,
                                           pct_round=( "%0.2f" % (100*pct) ),
                                           pct_cumulative=pct_cumulative,
                                           pct_cumulative_round=( "%0.2f" % (100*pct_cumulative) ),
                                           )
                                      )

            result.append({ "goal": goal, "variant_counts": variant_counts })

        return result
