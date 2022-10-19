import random
from django.db.models import Q, Count
from utils.api import APIView
from account.decorators import check_contest_permission
from ..models import QuizTag, Quiz, QuizRuleType
from ..serializers import QuizSerializer, TagSerializer, QuizSafeSerializer
from contest.models import ContestRuleType


class QuizTagAPI(APIView):
    def get(self, request):
        qs = QuizTag.objects
        keyword = request.GET.get("keyword")
        if keyword:
            qs = QuizTag.objects.filter(name__icontains=keyword)
        tags = qs.annotate(quiz_count=Count("quiz")).filter(quiz_count__gt=0)
        return self.success(TagSerializer(tags, many=True).data)


class PickOneAPI(APIView):
    def get(self, request):
        quizs = Quiz.objects.filter(contest_id__isnull=True, visible=True)
        count = quizs.count()
        if count == 0:
            return self.error("No quiz to pick")
        return self.success(quizs[random.randint(0, count - 1)]._id)


class QuizAPI(APIView):
    @staticmethod
    def _add_quiz_status(request, queryset_values):
        if request.user.is_authenticated:
            profile = request.user.userprofile
            acm_quizs_status = profile.acm_quizs_status.get("quizs", {})
            oi_quizs_status = profile.oi_quizs_status.get("quizs", {})
            # paginate data
            results = queryset_values.get("results")
            if results is not None:
                quizs = results
            else:
                quizs = [queryset_values, ]
            for quiz in quizs:
                if quiz["rule_type"] == QuizRuleType.ACM:
                    quiz["my_status"] = acm_quizs_status.get(str(quiz["id"]), {}).get("status")
                else:
                    quiz["my_status"] = oi_quizs_status.get(str(quiz["id"]), {}).get("status")

    def get(self, request):
        # 问题详情页
        quiz_id = request.GET.get("quiz_id")
        if quiz_id:
            try:
                quiz = Quiz.objects.select_related("created_by") \
                    .get(_id=quiz_id, contest_id__isnull=True, visible=True)
                quiz_data = QuizSerializer(quiz).data
                self._add_quiz_status(request, quiz_data)
                return self.success(quiz_data)
            except Quiz.DoesNotExist:
                return self.error("Quiz does not exist")

        limit = request.GET.get("limit")
        if not limit:
            return self.error("Limit is needed")

        quizs = Quiz.objects.select_related("created_by").filter(contest_id__isnull=True, visible=True)
        # 按照标签筛选
        tag_text = request.GET.get("tag")
        if tag_text:
            quizs = quizs.filter(tags__name=tag_text)

        # 搜索的情况
        keyword = request.GET.get("keyword", "").strip()
        if keyword:
            quizs = quizs.filter(Q(title__icontains=keyword) | Q(_id__icontains=keyword))

        # 难度筛选
        difficulty = request.GET.get("difficulty")
        if difficulty:
            quizs = quizs.filter(difficulty=difficulty)
        # 根据profile 为做过的题目添加标记
        data = self.paginate_data(request, quizs, QuizSerializer)
        self._add_quiz_status(request, data)
        return self.success(data)


class ContestQuizAPI(APIView):
    def _add_quiz_status(self, request, queryset_values):
        if request.user.is_authenticated:
            profile = request.user.userprofile
            if self.contest.rule_type == ContestRuleType.ACM:
                quizs_status = profile.acm_quizs_status.get("contest_quizs", {})
            else:
                quizs_status = profile.oi_quizs_status.get("contest_quizs", {})
            for quiz in queryset_values:
                quiz["my_status"] = quizs_status.get(str(quiz["id"]), {}).get("status")

    @check_contest_permission(check_type="quizs")
    def get(self, request):
        quiz_id = request.GET.get("quiz_id")
        if quiz_id:
            try:
                quiz = Quiz.objects.select_related("created_by").get(_id=quiz_id,
                                                                           contest=self.contest,
                                                                           visible=True)
            except Quiz.DoesNotExist:
                return self.error("Quiz does not exist.")
            if self.contest.quiz_details_permission(request.user):
                quiz_data = QuizSerializer(quiz).data
                self._add_quiz_status(request, [quiz_data, ])
            else:
                quiz_data = QuizSafeSerializer(quiz).data
            return self.success(quiz_data)

        contest_quizs = Quiz.objects.select_related("created_by").filter(contest=self.contest, visible=True)
        if self.contest.quiz_details_permission(request.user):
            data = QuizSerializer(contest_quizs, many=True).data
            self._add_quiz_status(request, data)
        else:
            data = QuizSafeSerializer(contest_quizs, many=True).data
        return self.success(data)
